# 小实验：能否把按键真的送进 pygame 窗口
#
# 背景：SetForegroundWindow 对**非前台进程**经常直接返回 false（Windows 的防抢焦点机制），
# 所以 v3 的 SendKeys 全打空了 —— 01 和 03 两张截图的 SHA 又相同。
# 标准解法是 AttachThreadInput：把自己线程"挂"到当前前台窗口的输入队列上，
# 这样系统就认为我们有资格设置前台了。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class Fg {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool fAttach);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder buf, int max);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int v);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();

    static string TitleOf(IntPtr h) { var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString(); }

    public static IntPtr FindSdlWindow(uint targetPid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            uint pid; GetWindowThreadProcessId(hWnd, out pid);
            if (pid != targetPid) return true;
            string t = TitleOf(hWnd);
            if (t.Length == 0) return true;
            if (t.IndexOf("python.exe", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (t.IndexOf("IME", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            RECT r; GetWindowRect(hWnd, out r);
            if ((r.Right - r.Left) < 200 || (r.Bottom - r.Top) < 200) return true;
            found = hWnd; return false;
        }, IntPtr.Zero);
        return found;
    }

    public static int HideConsoleOf(uint targetPid) {
        int n = 0;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            uint pid; GetWindowThreadProcessId(hWnd, out pid);
            if (pid != targetPid) return true;
            if (TitleOf(hWnd).IndexOf("python.exe", StringComparison.OrdinalIgnoreCase) >= 0) {
                ShowWindow(hWnd, 0); n++;
            }
            return true;
        }, IntPtr.Zero);
        return n;
    }

    // 强制把窗口设为前台：先把自己挂到当前前台线程的输入队列上
    public static bool ForceForeground(IntPtr hWnd) {
        IntPtr fg = GetForegroundWindow();
        uint fgPid;
        uint fgThread = GetWindowThreadProcessId(fg, out fgPid);
        uint myThread = GetCurrentThreadId();

        bool attached = false;
        if (fgThread != myThread) { attached = AttachThreadInput(myThread, fgThread, true); }

        ShowWindow(hWnd, 9);
        BringWindowToTop(hWnd);
        bool ok = SetForegroundWindow(hWnd);

        if (attached) { AttachThreadInput(myThread, fgThread, false); }
        return ok;
    }

    public static bool IsForeground(IntPtr hWnd) { return GetForegroundWindow() == hWnd; }
}
"@

try { [void][Fg]::SetProcessDpiAwareness(2) } catch {}

$py = 'E:\PythonProject\.venv\Scripts\python.exe'
$log = 'E:\PythonProject\data\logs\focus_probe.log'
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try { $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $c = '' }
    if ($c -match 'client\.main') { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Milliseconds 400

$client = Start-Process -FilePath $py `
    -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1','9527','--api','http://127.0.0.1:8000') `
    -PassThru -WorkingDirectory 'E:\PythonProject' `
    -RedirectStandardOutput $log -RedirectStandardError 'E:\PythonProject\data\logs\focus_probe_err.log'
Start-Sleep -Seconds 5
[void][Fg]::HideConsoleOf([uint32]$client.Id)
Start-Sleep -Milliseconds 400

$h = [Fg]::FindSdlWindow([uint32]$client.Id)
if ($h -eq [IntPtr]::Zero) { throw "找不到窗口" }
Write-Host ("  窗口 0x{0:X}" -f $h.ToInt64())

$ok = [Fg]::ForceForeground($h)
Start-Sleep -Milliseconds 600
Write-Host "  ForceForeground 返回: $ok"
Write-Host "  现在它是不是前台: $([Fg]::IsForeground($h))"

# 试着打几个字符
[System.Windows.Forms.SendKeys]::SendWait("abc")
Start-Sleep -Milliseconds 800

# 截图看有没有出现 "abc"
Add-Type -AssemblyName System.Drawing
$rect = New-Object Fg+RECT
[void][Fg]::GetWindowRect($h, [ref]$rect)
$w = $rect.Right - $rect.Left; $hh = $rect.Bottom - $rect.Top
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $hh))
$bmp.Save('E:\PythonProject\data\focus_probe.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Host "  截图: data\focus_probe.png"

Stop-Process -Id $client.Id -Force -ErrorAction SilentlyContinue
Write-Host "  --- stdout ---"
Get-Content $log -Encoding utf8 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
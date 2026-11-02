# 小实验 2：直接用 PostMessage 把按键/字符投递到 pygame 窗口（不依赖前台焦点）
#
# 为什么换这条路：v3/v4 里 SetForegroundWindow + AttachThreadInput 都成功了
# （IsForeground 返回 True），但 SDL 依然收不到字符 —— 它内部的键盘焦点状态
# 可能没被 WM_SETFOCUS 更新。PostMessage 直接把消息塞进目标窗口的消息队列，
# 绕开焦点这一层。
#
# 两件事要验证：
#   ① WM_KEYDOWN/WM_KEYUP（0x0100/0x0101）—— pygame 的 key.get_pressed 靠它
#   ② WM_CHAR（0x0102）—— 登录框的文字输入靠它

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class Pm {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder buf, int max);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int v);

    public const uint WM_KEYDOWN = 0x0100;
    public const uint WM_KEYUP   = 0x0101;
    public const uint WM_CHAR    = 0x0102;

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

    public static void KeyDown(IntPtr h, int vk) { PostMessage(h, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero); }
    public static void KeyUp(IntPtr h, int vk)   { PostMessage(h, WM_KEYUP,   (IntPtr)vk, IntPtr.Zero); }
    public static void Char(IntPtr h, char c)    { PostMessage(h, WM_CHAR,    (IntPtr)c,  IntPtr.Zero); }

    public static void TypeText(IntPtr h, string text) {
        foreach (char c in text) { Char(h, c); System.Threading.Thread.Sleep(30); }
    }

    public static void HoldKey(IntPtr h, int vk, int ms) {
        KeyDown(h, vk); System.Threading.Thread.Sleep(ms); KeyUp(h, vk);
    }
}
"@

try { [void][Pm]::SetProcessDpiAwareness(2) } catch {}

$py = 'E:\PythonProject\.venv\Scripts\python.exe'
$log = 'E:\PythonProject\data\logs\pm_probe.log'
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try { $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $c = '' }
    if ($c -match 'client\.main') { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Milliseconds 400

$client = Start-Process -FilePath $py `
    -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1','9527','--api','http://127.0.0.1:8000') `
    -PassThru -WorkingDirectory 'E:\PythonProject' `
    -RedirectStandardOutput $log -RedirectStandardError 'E:\PythonProject\data\logs\pm_probe_err.log'
Start-Sleep -Seconds 5
[void][Pm]::HideConsoleOf([uint32]$client.Id)
Start-Sleep -Milliseconds 400

$h = [Pm]::FindSdlWindow([uint32]$client.Id)
if ($h -eq [IntPtr]::Zero) { throw "找不到窗口" }
Write-Host ("  窗口 0x{0:X}" -f $h.ToInt64())

# 用 PostMessage 打字符
[Pm]::TypeText($h, "abc")
Start-Sleep -Milliseconds 800

$rect = New-Object Pm+RECT
[void][Pm]::GetWindowRect($h, [ref]$rect)
$w = $rect.Right - $rect.Left; $hh = $rect.Bottom - $rect.Top
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $hh))
$bmp.Save('E:\PythonProject\data\pm_probe.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Host "  截图: data\pm_probe.png"

Stop-Process -Id $client.Id -Force -ErrorAction SilentlyContinue
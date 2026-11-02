# 探针：按键到底进没进窗口？用 ESC 做二元判断（ESC 会让客户端退出）
#
# 两个通道各测一次：
#   A. keybd_event（真实输入，走前台窗口）
#   B. PostMessage WM_KEYDOWN（直接投递到窗口队列）
# 客户端进程死了 = 按键进去了；还活着 = 没进去。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class Probe {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder buf, int max);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int v);

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

    public static bool ForceForeground(IntPtr hWnd) {
        IntPtr fg = GetForegroundWindow();
        uint fgPid;
        uint fgThread = GetWindowThreadProcessId(fg, out fgPid);
        uint myThread = GetCurrentThreadId();
        bool attached = false;
        if (fgThread != myThread) attached = AttachThreadInput(myThread, fgThread, true);
        ShowWindow(hWnd, 9);
        BringWindowToTop(hWnd);
        bool ok = SetForegroundWindow(hWnd);
        if (attached) AttachThreadInput(myThread, fgThread, false);
        return ok;
    }

    public static void RealKey(byte vk) {
        keybd_event(vk, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(60);
        keybd_event(vk, 0, 0x0002, UIntPtr.Zero);
    }

    public static void PostKey(IntPtr h, int vk) {
        PostMessage(h, 0x0100, (IntPtr)vk, IntPtr.Zero);
        System.Threading.Thread.Sleep(60);
        PostMessage(h, 0x0101, (IntPtr)vk, IntPtr.Zero);
    }
}
"@

try { [void][Probe]::SetProcessDpiAwareness(2) } catch {}

function Start-Client {
    $py = 'E:\PythonProject\.venv\Scripts\python.exe'
    $p = Start-Process -FilePath $py `
        -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1','9527','--api','http://127.0.0.1:8000') `
        -PassThru -WorkingDirectory 'E:\PythonProject' `
        -RedirectStandardOutput 'E:\PythonProject\data\logs\probe_k.log' `
        -RedirectStandardError 'E:\PythonProject\data\logs\probe_k_err.log'
    Start-Sleep -Seconds 5
    [void][Probe]::HideConsoleOf([uint32]$p.Id)
    Start-Sleep -Milliseconds 400
    return $p
}

function Kill-Clients {
    Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
        try { $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $c = '' }
        if ($c -match 'client\.main') { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Milliseconds 500
}

# ---------------- A. keybd_event ----------------
Kill-Clients
$c = Start-Client
$h = [Probe]::FindSdlWindow([uint32]$c.Id)
Write-Host ("  A. 窗口 0x{0:X}" -f $h.ToInt64())
$fg = [Probe]::ForceForeground($h)
Write-Host "     设为前台: $fg   当前前台是否它: $([Probe]::GetForegroundWindow() -eq $h)"
Start-Sleep -Milliseconds 500
[Probe]::RealKey(0x1B)   # ESC
Start-Sleep -Seconds 2
$c.Refresh()
Write-Host "     【A 结果】进程是否已退出: $($c.HasExited)   -> " + $(if ($c.HasExited) { "✅ keybd_event 有效" } else { "❌ 无效" })
if (-not $c.HasExited) { Stop-Process -Id $c.Id -Force -ErrorAction SilentlyContinue }

# ---------------- B. PostMessage ----------------
Kill-Clients
$c2 = Start-Client
$h2 = [Probe]::FindSdlWindow([uint32]$c2.Id)
Write-Host ("  B. 窗口 0x{0:X}" -f $h2.ToInt64())
[Probe]::PostKey($h2, 0x1B)
Start-Sleep -Seconds 2
$c2.Refresh()
Write-Host "     【B 结果】进程是否已退出: $($c2.HasExited)   -> " + $(if ($c2.HasExited) { "✅ PostMessage 有效" } else { "❌ 无效" })
if (-not $c2.HasExited) { Stop-Process -Id $c2.Id -Force -ErrorAction SilentlyContinue }

Kill-Clients
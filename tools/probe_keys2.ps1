# 探针 3：分离"消息能不能到"与"键盘为什么不生效"
#
#   C. WM_CLOSE（0x0010）   —— 只看消息通道是否通畅
#   D. WM_SETFOCUS 后再发 ESC —— 看是不是 SDL 的键盘焦点状态没被更新
#
# 判定全靠进程是否退出（客户端收到 QUIT / ESC 都会退出）。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class P3 {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder buf, int max);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetFocus(IntPtr hWnd);
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

    public static void Post(IntPtr h, uint msg, IntPtr wp) { PostMessage(h, msg, wp, IntPtr.Zero); }
    public static IntPtr Send(IntPtr h, uint msg, IntPtr wp) { return SendMessage(h, msg, wp, IntPtr.Zero); }
}
"@

try { [void][P3]::SetProcessDpiAwareness(2) } catch {}

function Start-Client {
    $py = 'E:\PythonProject\.venv\Scripts\python.exe'
    $p = Start-Process -FilePath $py `
        -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1','9527','--api','http://127.0.0.1:8000') `
        -PassThru -WorkingDirectory 'E:\PythonProject' `
        -RedirectStandardOutput 'E:\PythonProject\data\logs\probe3.log' `
        -RedirectStandardError 'E:\PythonProject\data\logs\probe3_err.log'
    Start-Sleep -Seconds 5
    [void][P3]::HideConsoleOf([uint32]$p.Id)
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

# ---------------- C. WM_CLOSE ----------------
Kill-Clients
$c = Start-Client
$h = [P3]::FindSdlWindow([uint32]$c.Id)
Write-Host ("  C. 窗口 0x{0:X}" -f $h.ToInt64())
[P3]::Post($h, 0x0010, [IntPtr]::Zero)     # WM_CLOSE
Start-Sleep -Seconds 2
$c.Refresh()
Write-Host "     【C】进程退出: $($c.HasExited)  -> " + $(if ($c.HasExited) { "✅ 消息通道是通的" } else { "❌ 连 WM_CLOSE 都不响应" })
if (-not $c.HasExited) { Stop-Process -Id $c.Id -Force -ErrorAction SilentlyContinue }

# ---------------- D. WM_SETFOCUS + ESC ----------------
Kill-Clients
$c2 = Start-Client
$h2 = [P3]::FindSdlWindow([uint32]$c2.Id)
Write-Host ("  D. 窗口 0x{0:X}" -f $h2.ToInt64())
[P3]::Post($h2, 0x0007, [IntPtr]::Zero)    # WM_SETFOCUS
Start-Sleep -Milliseconds 300
[P3]::Post($h2, 0x0100, [IntPtr]0x1B)      # WM_KEYDOWN ESC
Start-Sleep -Milliseconds 80
[P3]::Post($h2, 0x0101, [IntPtr]0x1B)      # WM_KEYUP ESC
Start-Sleep -Seconds 2
$c2.Refresh()
Write-Host "     【D】进程退出: $($c2.HasExited)  -> " + $(if ($c2.HasExited) { "✅ 补 WM_SETFOCUS 后键盘生效" } else { "❌ 仍然无效" })
if (-not $c2.HasExited) { Stop-Process -Id $c2.Id -Force -ErrorAction SilentlyContinue }

Kill-Clients
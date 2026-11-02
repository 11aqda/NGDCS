# 探针 4：把焦点真正"给"到 SDL 窗口
#
# 前三轮已经确认：消息通道是通的（WM_CLOSE 能让客户端退出），
# 但 WM_KEYDOWN 被 SDL 丢掉 —— 因为它内部的键盘焦点状态是空的。
#
# 关键点：SetFocus 只能作用于**调用线程**的输入队列，
# 所以必须 AttachThreadInput 挂到**目标窗口所属线程**（不是前台窗口线程），
# 调完 SetFocus 再解挂。这样会真实产生 WM_SETFOCUS。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class P4 {
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
    [DllImport("user32.dll")] public static extern IntPtr SetFocus(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetFocus();
    [DllImport("user32.dll")] public static extern IntPtr SetActiveWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
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

    // 把焦点真正交给目标窗口：挂到**它所属线程**的输入队列 → SetActiveWindow + SetFocus
    public static string GiveFocus(IntPtr hWnd) {
        uint pid;
        uint appThread = GetWindowThreadProcessId(hWnd, out pid);
        uint myThread = GetCurrentThreadId();
        bool attached = false;
        if (appThread != myThread) attached = AttachThreadInput(myThread, appThread, true);

        ShowWindow(hWnd, 9);
        SetForegroundWindow(hWnd);
        SetActiveWindow(hWnd);
        IntPtr prev = SetFocus(hWnd);
        IntPtr now = GetFocus();

        if (attached) AttachThreadInput(myThread, appThread, false);
        return String.Format("attached={0} appThread={1} myThread={2} focused={3} fg={4}",
            attached, appThread, myThread, (now == hWnd), (GetForegroundWindow() == hWnd));
    }

    public static void Post(IntPtr h, uint msg, IntPtr wp) { PostMessage(h, msg, wp, IntPtr.Zero); }
}
"@

try { [void][P4]::SetProcessDpiAwareness(2) } catch {}

Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try { $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $c = '' }
    if ($c -match 'client\.main') { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Milliseconds 500

$py = 'E:\PythonProject\.venv\Scripts\python.exe'
$c = Start-Process -FilePath $py `
    -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1','9527','--api','http://127.0.0.1:8000') `
    -PassThru -WorkingDirectory 'E:\PythonProject' `
    -RedirectStandardOutput 'E:\PythonProject\data\logs\probe4.log' `
    -RedirectStandardError 'E:\PythonProject\data\logs\probe4_err.log'
Start-Sleep -Seconds 5
[void][P4]::HideConsoleOf([uint32]$c.Id)
Start-Sleep -Milliseconds 400

$h = [P4]::FindSdlWindow([uint32]$c.Id)
Write-Host ("  窗口 0x{0:X}" -f $h.ToInt64())
Start-Sleep -Milliseconds 300
Write-Host "  GiveFocus: " ([P4]::GiveFocus($h))

Start-Sleep -Milliseconds 600
[P4]::Post($h, 0x0100, [IntPtr]0x1B)
Start-Sleep -Milliseconds 80
[P4]::Post($h, 0x0101, [IntPtr]0x1B)
Start-Sleep -Seconds 2

$c.Refresh()
Write-Host "  【结果】进程退出: $($c.HasExited)  -> " + $(if ($c.HasExited) { "✅ 焦点修复有效，按键可用" } else { "❌ 仍然无效" })
if (-not $c.HasExited) { Stop-Process -Id $c.Id -Force -ErrorAction SilentlyContinue }
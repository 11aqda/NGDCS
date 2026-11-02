# 诊断：列出某个 PID 的所有顶层窗口（标题 / 可见性 / 矩形）
# 用途：搞清 PyGame 窗口到底挂在哪个 PID 上、为什么 EnumWindows 找不到。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class WinDiag {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder buf, int max);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);

    public static List<string> ListFor(uint targetPid) {
        var rows = new List<string>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (pid != targetPid) return true;
            var sb = new StringBuilder(512);
            GetWindowTextW(hWnd, sb, 512);
            RECT r;
            GetWindowRect(hWnd, out r);
            rows.Add(String.Format("hwnd=0x{0:X}  visible={1}  rect=({2},{3})-({4},{5})  title='{6}'",
                hWnd.ToInt64(), IsWindowVisible(hWnd), r.Left, r.Top, r.Right, r.Bottom, sb.ToString()));
            return true;
        }, IntPtr.Zero);
        return rows;
    }
}
"@

$targets = @()
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try { $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $c = '' }
    if ($c -match 'client\.main') { $targets += [pscustomobject]@{ Id = $_.Id; Cmd = $c } }
}

if ($targets.Count -eq 0) {
    Write-Host "  没有在跑的客户端进程"
} else {
    foreach ($t in $targets) {
        Write-Host "  === PID $($t.Id) ==="
        $rows = [WinDiag]::ListFor([uint32]$t.Id)
        if ($rows.Count -eq 0) { Write-Host "    （该 PID 没有任何顶层窗口）" }
        foreach ($row in $rows) { Write-Host "    $row" }
    }
}
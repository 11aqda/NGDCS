# 诊断：cmd 窗口到底存不存在、标题是什么
#
# 现象：按 title 找不到窗口。可能是
#   a) bat 根本没被执行
#   b) cmd 窗口被创建但没有标题（title 命令没生效 / 被 cmd /c 忽略）
#   c) 窗口不可见

$ErrorActionPreference = 'Stop'
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class Diag3 {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder buf, int max);

    public static List<string> AllVisible() {
        var rows = new List<string>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            if (!IsWindowVisible(hWnd)) return true;
            var sb = new StringBuilder(512);
            GetWindowTextW(hWnd, sb, 512);
            string title = sb.ToString();
            if (title.Length == 0) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            RECT r;
            GetWindowRect(hWnd, out r);
            rows.Add(String.Format("pid={0,-7} {1}x{2}  '{3}'",
                pid, r.Right - r.Left, r.Bottom - r.Top, title));
            return true;
        }, IntPtr.Zero);
        return rows;
    }
}
"@

$batDir = 'E:\PythonProject\data\logs\shots'
New-Item -ItemType Directory -Path $batDir -Force | Out-Null
$batPath = Join-Path $batDir 'diag.bat'
$marker = 'E:\PythonProject\data\logs\shots\diag_marker.txt'
if (Test-Path $marker) { Remove-Item $marker -Force }

Set-Content -LiteralPath $batPath -Encoding ascii -Value @(
    '@echo off',
    'chcp 65001 >nul',
    'title NGDCS-DIAG',
    'cd /d E:\PythonProject',
    "echo ran > $marker",
    'echo === hello from diag ===',
    'timeout /t 20 >nul'
)

Write-Host "  启动: $batPath"
$p = Start-Process cmd -ArgumentList @('/c', $batPath) -PassThru -WindowStyle Normal
Start-Sleep -Seconds 4

Write-Host "  cmd PID = $($p.Id)   已退出: $($p.HasExited)"
Write-Host "  marker 存在: $(Test-Path $marker)"
Write-Host ""
Write-Host "  当前所有可见窗口："
foreach ($row in [Diag3]::AllVisible()) { Write-Host "    $row" }

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
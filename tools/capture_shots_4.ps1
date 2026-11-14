# 截图脚本 阶段 4：补拍 02（认证成功）和 07（MySQL+Redis）
#
#   - 02 需要重新截：check_persist 的横扫逻辑已经改了（原来每秒换向、只在原地抖，
#     经常打不到分导致 3 项断言假失败），现在每 3 秒换向、24 个敌机、14 秒。
#   - 07 需要重新截：上次控制台太矮，SHOW TABLES 和 auth_user 的输出被顶出了可视区；
#     这次先 `mode con: cols=115 lines=55` 把窗口撑大。

$ErrorActionPreference = 'Stop'
# MySQL 密码只从环境变量来（不写进仓库）：
if ($env:NGDCS_DB_PASSWORD) { $env:MYSQL_PWD = $env:NGDCS_DB_PASSWORD }
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class C4 {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder buf, int max);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int n);
    [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int v);

    static string TitleOf(IntPtr h) { var sb = new StringBuilder(512); GetWindowTextW(h, sb, 512); return sb.ToString(); }

    public static IntPtr ByTitle(string wanted) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            if (!IsWindowVisible(hWnd)) return true;
            if (TitleOf(hWnd).IndexOf(wanted, StringComparison.Ordinal) < 0) return true;
            found = hWnd;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    public static void Front(IntPtr h) { ShowWindow(h, 9); SetForegroundWindow(h); }
}
"@

try { [void][C4]::SetProcessDpiAwareness(2) } catch {}

$outDir = 'E:\PythonProject\docs\screenshots'
$batDir = 'E:\PythonProject\data\logs\shots'
New-Item -ItemType Directory -Path $batDir -Force | Out-Null

function ShotWindow([IntPtr]$hWnd, [string]$path) {
    $rect = New-Object C4+RECT
    [void][C4]::GetWindowRect($hWnd, [ref]$rect)
    $w = $rect.Right - $rect.Left; $h = $rect.Bottom - $rect.Top
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Host ("  [OK] {0}  ({1}x{2})" -f $path, $w, $h)
}

function ShotBat([string]$title, [string[]]$batBody, [string]$file, [int]$waitSec) {
    Write-Host "  --- $title ---"
    $batPath = Join-Path $batDir "$title.bat"
    $lines = @("@echo off", "chcp 65001 >nul", "title $title", "cd /d E:\PythonProject") + $batBody +
             @("echo.", "echo [done]", "timeout /t 120 /nobreak >nul")
    Set-Content -LiteralPath $batPath -Value $lines -Encoding ascii

    $p = Start-Process cmd -ArgumentList @('/c', $batPath) -PassThru -WindowStyle Normal
    Start-Sleep -Seconds $waitSec

    $h = [C4]::ByTitle($title)
    if ($h -eq [IntPtr]::Zero) {
        Write-Host "    no window titled '$title'"
    } else {
        [C4]::Front($h)
        Start-Sleep -Milliseconds 900
        ShotWindow $h (Join-Path $outDir $file)
    }
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

# ---------- 02 认证成功（11 项检查全过） ----------
ShotBat 'NGDCS-02b-auth' @('.venv\Scripts\python.exe -X utf8 -m tools.check_persist') '02-auth-ok.png' 55

# ---------- 07 MySQL + Redis（窗口撑到 55 行，输出全放得下） ----------
ShotBat 'NGDCS-07b-db' @(
    'mode con: cols=115 lines=55',
    '"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -e "USE myproject; SHOW TABLES; SELECT id,username FROM auth_user; SELECT user_id,score,level,kills FROM score_record ORDER BY score DESC LIMIT 5;"',
    'echo.',
    'echo === Redis ZSET lb:best_score  (ZREVRANGE 0 4 WITHSCORES) ===',
    '"D:\Tools\Redis\redis-cli.exe" ZREVRANGE lb:best_score 0 4 WITHSCORES'
) '07-mysql-redis.png' 8

Write-Host "  stage 4 done"
# 截图脚本 阶段 3（v3）：终端类截图
#
# 前三版的问题，都记下来（都是真实踩的）：
#   ① v1 按 powershell 的 PID 找窗口 —— 控制台窗口其实归 **conhost.exe**，找不到，
#      截到的是别的窗口（截出来是 `[plot] ...` 那种不相干的旧输出）。
#   ② cmd 默认代码页 GBK，中文日志全是乱码。
#   ③ v2 用 `Start-Process cmd -ArgumentList $一整串` —— PowerShell 会**按空格拆参数**，
#      cmd 只收到 `/c chcp 65001` 就退出了，窗口根本没留下来。
#
# 现在的做法：每条命令写一个 **.bat**（ASCII 内容，绕开所有引号问题），
# `cmd /c xxx.bat` 启动，按 `title` 设的标题找窗口，按窗口矩形裁剪。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class C3 {
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
            // ⚠️ 控制台标题会被系统加前缀：管理员会话下实测是
            // "Administrator:  NGDCS-06-tests"（冒号后两个空格），精确匹配永远失败 → 用包含匹配
            if (TitleOf(hWnd).IndexOf(wanted, StringComparison.Ordinal) < 0) return true;
            found = hWnd;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    public static void Front(IntPtr h) { ShowWindow(h, 9); SetForegroundWindow(h); }
}
"@

try { [void][C3]::SetProcessDpiAwareness(2) } catch {}

$outDir = 'E:\PythonProject\docs\screenshots'
$batDir = 'E:\PythonProject\data\logs\shots'
New-Item -ItemType Directory -Path $batDir -Force | Out-Null

function ShotWindow([IntPtr]$hWnd, [string]$path) {
    $rect = New-Object C3+RECT
    [void][C3]::GetWindowRect($hWnd, [ref]$rect)
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
    # ⚠️ 末尾必须留一条阻塞命令：`cmd /c xxx.bat` 跑完会**立刻关窗口**，
    # 而我们要等几秒才截图 —— 实测 `type 日志` 一闪就没，截不到。
    $lines = @("@echo off", "chcp 65001 >nul", "title $title", "cd /d E:\PythonProject") + $batBody +
             @("echo.", "echo [done]", "timeout /t 90 /nobreak >nul")
    Set-Content -LiteralPath $batPath -Value $lines -Encoding ascii

    $p = Start-Process cmd -ArgumentList @('/c', $batPath) -PassThru -WindowStyle Normal
    Start-Sleep -Seconds $waitSec

    $h = [C3]::ByTitle($title)
    if ($h -eq [IntPtr]::Zero) {
        Write-Host "    no window titled '$title'"
    } else {
        [C3]::Front($h)
        Start-Sleep -Milliseconds 800
        ShotWindow $h (Join-Path $outDir $file)
    }
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

# ---------- 05 服务端启动日志 ----------
ShotBat 'NGDCS-05-server' @('type data\logs\server_demo.log') '05-server-log.png' 5

# ---------- 06 测试通过 ----------
ShotBat 'NGDCS-06-tests' @('.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -t .') '06-tests.png' 25

# ---------- 07 MySQL + Redis ----------
ShotBat 'NGDCS-07-db' @(
    '"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p123456 -e "USE myproject; SHOW TABLES; SELECT id,username FROM auth_user LIMIT 6; SELECT user_id,score,level,kills FROM score_record ORDER BY score DESC LIMIT 6;"',
    'echo.',
    'echo === Redis ZSET lb:best_score ===',
    '"D:\Tools\Redis\redis-cli.exe" ZREVRANGE lb:best_score 0 6 WITHSCORES'
) '07-mysql-redis.png' 7

# ---------- 02 认证成功（端到端） ----------
ShotBat 'NGDCS-02-auth' @('.venv\Scripts\python.exe -X utf8 -m tools.check_persist') '02-auth-ok.png' 45

Write-Host "  stage 3 done"
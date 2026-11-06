# 一键启动游戏模式：服务端（隐藏）+ 客户端（前台显示）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\start_game.ps1
#   powershell -ExecutionPolicy Bypass -File tools\start_game.ps1 -Port 9527 -Seed 1
#
# 说明：
#   - 服务端后台跑，日志写到 data\logs\play_server.log（卡住/报错先看它）
#   - 客户端正常显示，启动后自动提到前台（SDL 窗口，不是控制台窗口）
#   - 停止：关掉客户端窗口即可；服务端用 tools\stop_game.ps1，或直接关这个脚本对应的进程

param(
    [int]$Port = 9527,
    [int]$Seed = 1,
    [switch]$NoFocus
)

$ErrorActionPreference = "Stop"
$py = "E:\PythonProject\.venv\Scripts\python.exe"
$root = "E:\PythonProject"
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# 清掉上一次残留（否则端口占用 / 两个客户端抢窗口）
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try { $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $cmd = "" }
    if ($cmd -match 'server\.main|client\.main|bot\.main') {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 700

Write-Host "[1/3] 启动服务端（--game-mode，端口 $Port，seed $Seed）..."
$srv = Start-Process -FilePath $py -WindowStyle Hidden -PassThru -WorkingDirectory $root `
    -ArgumentList @('-X','utf8','-u','-m','server.main', "$Port", '--game-mode','--game-seed',"$Seed",'--no-metrics') `
    -RedirectStandardOutput (Join-Path $logDir 'play_server.log') `
    -RedirectStandardError  (Join-Path $logDir 'play_server.err')
Start-Sleep -Seconds 2

if ($srv.HasExited) {
    Write-Host "  [FAIL] 服务端没起来，看 data\logs\play_server.err"
    Get-Content (Join-Path $logDir 'play_server.err') -Encoding utf8 -ErrorAction SilentlyContinue | Select-Object -First 8
    exit 1
}

Write-Host "[2/3] 启动客户端（游客身份）..."
# ⚠️ 客户端**不要重定向 stdout/stderr**：重定向会把管道句柄挂在父进程上，
# 父进程（这个脚本 / 调用它的 shell）一结束，客户端就跟着被回收 —— 实测踩过：
# 启动脚本超时转后台后，客户端直接没了，服务端却还活着。
$cli = Start-Process -FilePath $py -PassThru -WorkingDirectory $root `
    -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1',"$Port",'--guest')
Start-Sleep -Seconds 3

Write-Host "[3/3] 把游戏窗口提到前台..."
if (-not $NoFocus) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
    # 客户端进程有两个窗口：控制台 + SDL。按标题挑 SDL 那个（标题含 "C/S"）
    $game = $null
    for ($i = 0; $i -lt 20; $i++) {
        $game = Get-Process python -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowTitle -like "*C/S*" } | Select-Object -First 1
        if ($game) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($game) {
        [void][Win]::ShowWindow($game.MainWindowHandle, 9)   # SW_RESTORE
        [void][Win]::SetForegroundWindow($game.MainWindowHandle)
        Write-Host "  窗口标题: $($game.MainWindowTitle)"
    } else {
        Write-Host "  [WARN] 没找到游戏窗口（客户端可能还在初始化），手动点一下任务栏即可"
    }
}

Write-Host ""
Write-Host "  ✅ 已启动。操作："
Write-Host "     ← / → 或 A / D    移动"
Write-Host "     空格              开火（按住连发，射速由服务端控制）"
Write-Host "     B                 排行榜（需要 Django 服务在跑）"
Write-Host "     ESC               退出"
Write-Host ""
Write-Host "  服务端日志: data\logs\play_server.log"
Write-Host "  （客户端不写日志文件：重定向会让它在启动脚本退出时被一起回收）"
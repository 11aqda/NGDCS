# 截图脚本 阶段 2：游戏画面（已登录身份）
#
# 用 --login 免交互登录（走和登录界面同一条 HTTP 路径），这样 HUD 上显示的是
# 真实用户名而不是「游客」。窗口裁剪 + DPI 感知沿用阶段 1 的经验。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class W2 {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder buf, int max);
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
}
"@

try { [void][W2]::SetProcessDpiAwareness(2) } catch {}

function ShotWindow([IntPtr]$hWnd, [string]$path) {
    $rect = New-Object W2+RECT
    [void][W2]::GetWindowRect($hWnd, [ref]$rect)
    $w = $rect.Right - $rect.Left; $h = $rect.Bottom - $rect.Top
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Host ("  [OK] {0}  ({1}x{2})" -f $path, $w, $h)
}

$py = 'E:\PythonProject\.venv\Scripts\python.exe'
$outDir = 'E:\PythonProject\docs\screenshots'
$log = 'E:\PythonProject\data\logs\shot_game.log'

Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try { $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $c = '' }
    if ($c -match 'client\.main') { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Milliseconds 500

$client = Start-Process -FilePath $py `
    -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1','9527',
                    '--api','http://127.0.0.1:8000','--login',("demo01:" + $env:NGDCS_DEMO_PASSWORD)) `
    -PassThru -WorkingDirectory 'E:\PythonProject' `
    -RedirectStandardOutput $log -RedirectStandardError 'E:\PythonProject\data\logs\shot_game_err.log'
Start-Sleep -Seconds 7
[void][W2]::HideConsoleOf([uint32]$client.Id)
Start-Sleep -Milliseconds 500

$h = [W2]::FindSdlWindow([uint32]$client.Id)
if ($h -eq [IntPtr]::Zero) { throw "找不到 SDL 窗口" }

# 多等一会儿，让实体跑起来、画面有内容
Start-Sleep -Seconds 3
ShotWindow $h "$outDir\03-game.png"

Stop-Process -Id $client.Id -Force -ErrorAction SilentlyContinue
Write-Host "  --- 客户端 stdout ---"
Get-Content $log -Encoding utf8 -ErrorAction SilentlyContinue | Select-Object -Last 8 | ForEach-Object { Write-Host "    $_" }
# 截图脚本 阶段 1（v3）：登录界面 / 游戏画面 / 排行榜
#
# 三次踩坑记录（都是真实发生的，写下来免得再犯）：
#   ① v1：客户端没隐藏控制台 → 黑色控制台窗口抢走焦点，
#          SendKeys 全打在控制台上，登录框一个字没收到（01 和 03 两张 SHA 相同）。
#   ② v1：全屏截图把桌面图标和浏览器都拍进去 → 改成**按窗口矩形裁剪**。
#   ③ v2：用 `-WindowStyle Hidden` → 它会把 **SDL 窗口一起隐藏**（visible=False），
#          但窗口标题还在，看起来像"找不到窗口"。
#          正确做法：正常启动，然后**只隐藏控制台窗口**。
#
# 找窗口不能用 $proc.MainWindowHandle —— 对 SDL 程序它常是 0 或指向控制台。
# 这里枚举该 PID 的所有顶层窗口，按"标题不像 python.exe / 不是 Default IME / 面积够大"来挑。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class Win {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder buf, int max);

    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public static void Down(byte vk) { keybd_event(vk, 0, 0, UIntPtr.Zero); }
    public static void Up(byte vk)   { keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero); }
    public static void Hold(byte vk, int ms) { Down(vk); System.Threading.Thread.Sleep(ms); Up(vk); }

    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int value);

    static string TitleOf(IntPtr h) {
        var sb = new StringBuilder(512);
        GetWindowTextW(h, sb, 512);
        return sb.ToString();
    }

    // 隐藏该进程的**控制台窗口**（标题是 python.exe 的完整路径），SDL 窗口不动
    public static int HideConsoleOf(uint targetPid) {
        int hidden = 0;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            uint pid; GetWindowThreadProcessId(hWnd, out pid);
            if (pid != targetPid) return true;
            string title = TitleOf(hWnd);
            if (title.IndexOf("python.exe", StringComparison.OrdinalIgnoreCase) >= 0) {
                ShowWindow(hWnd, 0);   // SW_HIDE
                hidden++;
            }
            return true;
        }, IntPtr.Zero);
        return hidden;
    }

    // 挑 SDL 窗口：排除 python.exe 控制台、默认 IME、面积过小的辅助窗口
    public static IntPtr FindSdlWindow(uint targetPid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            uint pid; GetWindowThreadProcessId(hWnd, out pid);
            if (pid != targetPid) return true;
            string title = TitleOf(hWnd);
            if (title.Length == 0) return true;
            if (title.IndexOf("python.exe", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            if (title.IndexOf("IME", StringComparison.OrdinalIgnoreCase) >= 0) return true;
            RECT r; GetWindowRect(hWnd, out r);
            if ((r.Right - r.Left) < 200 || (r.Bottom - r.Top) < 200) return true;
            found = hWnd;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    public static bool BringToFront(IntPtr hWnd) {
        ShowWindow(hWnd, 9);           // SW_RESTORE
        return SetForegroundWindow(hWnd);
    }
}
"@

# DPI：客户端是 DPI-aware（物理像素），而 PowerShell 默认不是（虚拟像素）。
# 两套坐标系一混，GetWindowRect 算出的矩形和 CopyFromScreen 抓的像素就对不上 ——
# 实测裁出来是桌面左上角 + 窗口的一角。所以**脚本一开头就把自己也变 DPI-aware**。
try { [void][Win]::SetProcessDpiAwareness(2) } catch { try { [void][Win]::SetProcessDPIAware() } catch {} }

$VK_TAB = 0x09; $VK_ENTER = 0x0D; $VK_LEFT = 0x25; $VK_RIGHT = 0x27; $VK_B = 0x42; $VK_ESC = 0x1B

function ShotWindow([IntPtr]$hWnd, [string]$path) {
    $rect = New-Object Win+RECT
    [void][Win]::GetWindowRect($hWnd, [ref]$rect)
    $w = $rect.Right - $rect.Left
    $h = $rect.Bottom - $rect.Top
    if ($w -le 0 -or $h -le 0) { throw "窗口矩形无效：$w x $h" }

    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Host ("  [OK] {0}  ({1}x{2})" -f $path, $w, $h)
}

$outDir = 'E:\PythonProject\docs\screenshots'
$py = 'E:\PythonProject\.venv\Scripts\python.exe'
$logOut = 'E:\PythonProject\data\logs\client_shots.log'

Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try { $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { $c = '' }
    if ($c -match 'client\.main') { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Milliseconds 500

$client = Start-Process -FilePath $py `
    -ArgumentList @('-X','utf8','-u','-m','client.main','127.0.0.1','9527','--api','http://127.0.0.1:8000') `
    -PassThru -WorkingDirectory 'E:\PythonProject' `
    -RedirectStandardOutput $logOut -RedirectStandardError 'E:\PythonProject\data\logs\client_shots_err.log'
Start-Sleep -Seconds 5

$hidden = [Win]::HideConsoleOf([uint32]$client.Id)
Write-Host "  隐藏控制台窗口：$hidden 个"
Start-Sleep -Milliseconds 400

$hWnd = [Win]::FindSdlWindow([uint32]$client.Id)
if ($hWnd -eq [IntPtr]::Zero) { throw "找不到 SDL 窗口（PID=$($client.Id)）" }
Write-Host ("  窗口句柄 0x{0:X}" -f $hWnd.ToInt64())
[void][Win]::BringToFront($hWnd)
Start-Sleep -Milliseconds 900

# ---------- ① 登录界面（空表单） ----------
ShotWindow $hWnd "$outDir\01-login.png"

# ---------- 输入账号密码并登录 ----------
[System.Windows.Forms.SendKeys]::SendWait("demo01")
Start-Sleep -Milliseconds 400
[Win]::Hold($VK_TAB, 90)
Start-Sleep -Milliseconds 250
[System.Windows.Forms.SendKeys]::SendWait("secret123")
Start-Sleep -Milliseconds 400
[Win]::Hold($VK_ENTER, 90)
Start-Sleep -Seconds 5

# ---------- 左右横扫打一会儿攒分数 ----------
for ($i = 0; $i -lt 30; $i++) {
    if ($i % 2 -eq 0) { [Win]::Hold($VK_RIGHT, 380) } else { [Win]::Hold($VK_LEFT, 380) }
}
Start-Sleep -Milliseconds 600

# ---------- ③ 游戏画面（有分数） ----------
ShotWindow $hWnd "$outDir\03-game.png"

# ---------- ④ 排行榜 ----------
[Win]::Hold($VK_B, 90)
Start-Sleep -Seconds 2
ShotWindow $hWnd "$outDir\04-leaderboard.png"

# 回游戏 → 退出
[Win]::Hold($VK_ESC, 90)
Start-Sleep -Milliseconds 500
[Win]::Hold($VK_ESC, 90)
Start-Sleep -Seconds 2

Write-Host "  --- 客户端 stdout ---"
Get-Content $logOut -Encoding utf8 -ErrorAction SilentlyContinue | Select-Object -Last 10 |
    ForEach-Object { Write-Host "    $_" }
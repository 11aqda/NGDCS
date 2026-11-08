@echo off
chcp 936 >nul
setlocal

rem ============================================================
rem  一键启动：TCP 服务端 + Django + 客户端
rem  三个窗口都用 cmd /k 留着，报错不会一闪而过
rem  不碰 MySQL/Redis 的启停，也不杀任何已有的 python 进程
rem ============================================================

set "ROOT=E:\PythonProject"
set "PY=%ROOT%\.venv\Scripts\python.exe"

rem 双击运行时当前目录通常是 C:\Windows\System32，必须先切过去
cd /d "%ROOT%"
if errorlevel 1 (
    echo [错误] 进不去 %ROOT%
    pause
    exit /b 1
)

if not exist "%PY%" (
    echo [错误] 找不到虚拟环境解释器：
    echo        %PY%
    echo        先确认 .venv 存在。
    pause
    exit /b 1
)

rem MySQL 只提示、不代劳启动（脚本不去动系统服务）
sc query MySQL80 | findstr /i "RUNNING" >nul
if errorlevel 1 (
    echo [提示] MySQL80 服务没在运行。
    echo        登录、排行榜、战绩入库都会失败，请先手动启动 MySQL。
    echo.
)

rem 端口冲突先说清楚，省得三个窗口里各报一次错
call :port_busy 9527 "TCP 服务端"
call :port_busy 8000 "Django Web"

echo [1/3] 启动 TCP 服务端（端口 9527）...
rem 注意：--game-mode 自带"击杀生效"，而且**不能**再带 --enemies/--bullets
rem       那两个是"补满固定数量"的参数，和波次生成会打架。
start "NGDCS Server" cmd /k "%PY% -X utf8 -m server.main --game-mode --persist-scores"

echo [2/3] 启动 Django（端口 8000）...
start "NGDCS Django" cmd /k "%PY% manage.py runserver 127.0.0.1:8000"

echo      等 4 秒，让服务端和 Django 先起来
ping -n 5 127.0.0.1 >nul

echo [3/3] 启动客户端（会先停在登录界面，不要直接进游戏）
start "NGDCS Client" cmd /k "%PY% -X utf8 -m client.main"

echo.
echo ---------------------------------------------
echo   NGDCS Server   TCP 9527（三波游戏，击杀生效，战绩入库）
echo   NGDCS Django   http://127.0.0.1:8000/  （登录/排行榜/战绩入库）
echo   NGDCS Client   先注册/登录，再进游戏
echo.
echo   要看看板：先关掉这个 Django，再双击 start_dashboard.bat
echo   （看板在 E:\NGDCS-web，两个 Django 不能同时占 8000）
echo.
echo   关的时候把三个窗口直接关掉就行。
echo ---------------------------------------------
ping -n 6 127.0.0.1 >nul
exit /b 0


rem ============================================================
rem  子过程：端口被占用就提示，但**不**替用户杀进程
rem  参数：%1 = 端口，%2 = 用途
rem ============================================================
:port_busy
netstat -ano | findstr ":%1 " | findstr "LISTENING" >nul
if not errorlevel 1 exit /b 0
echo [警告] 端口 %1（%2）已被占用，新进程会起不来。
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%1 " ^| findstr "LISTENING"') do (
    echo        占用者 PID %%p，确认是什么之后再处理
)
echo.
exit /b 0
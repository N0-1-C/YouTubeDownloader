@echo off
chcp 65001 >nul
:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   YouTube 视频下载器 - 请求管理员权限
    echo.
    echo   Windows 将弹出 UAC 提示，请点击 [是]
    echo.
    :: 创建临时 VBS 脚本来请求 UAC 提权
    echo Set UAC = CreateObject("Shell.Application") > "%temp%\yt_uac.vbs"
    echo UAC.ShellExecute "cmd", "/c cd /d ""%~dp0"" && python app.py && pause", "", "runas", 1 >> "%temp%\yt_uac.vbs"
    wscript "%temp%\yt_uac.vbs"
    del "%temp%\yt_uac.vbs" >nul 2>&1
    exit /b
)
cd /d "%~dp0"
title YouTube 视频下载器 [管理员模式]
echo ================================================
echo   YouTube 视频下载器
echo ================================================
echo.
echo   [管理员模式] - 可自动读取浏览器 cookies
echo   启动中... 浏览器将自动打开 http://127.0.0.1:5000
echo.
echo   关闭此窗口即可停止服务
echo ================================================
echo.
start "" "http://127.0.0.1:5000"
python app.py
pause

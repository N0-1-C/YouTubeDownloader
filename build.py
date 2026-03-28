"""
YouTube Downloader - PyInstaller 打包配置
"""
import os
import sys
import shutil
import subprocess

# ============ 配置 ============
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = 'YouTubeDownloader'
BUILD_DIR = os.path.join(PROJECT_DIR, 'build')
DIST_DIR = os.path.join(PROJECT_DIR, 'dist')
RELEASE_DIR = os.path.join(PROJECT_DIR, 'release')

# 外部工具源路径（需要根据本机实际情况调整）
FFMPEG_SRC_DIR = r'C:\Users\pc\ffmpeg\bin'
NODE_SRC_DIR = r'C:\Program Files\nodejs'
COOKIES_SRC = r'C:\Users\pc\Downloads\www.youtube.com_cookies.txt'


def check_tools():
    """检查所有必要工具是否就绪"""
    print("=" * 50)
    print("  检查打包环境...")
    print("=" * 50)
    
    errors = []
    
    # Python
    print(f"  [OK] Python: {sys.version}")
    
    # PyInstaller
    try:
        import PyInstaller
        print(f"  [OK] PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        errors.append("PyInstaller 未安装，请运行: pip install pyinstaller")
    
    # ffmpeg
    ffmpeg = shutil.which('ffmpeg') or os.path.join(FFMPEG_SRC_DIR, 'ffmpeg.exe')
    if os.path.isfile(ffmpeg):
        print(f"  [OK] FFmpeg: {ffmpeg}")
    else:
        errors.append(f"未找到 ffmpeg，请修改 FFMPEG_SRC_DIR")
    
    # node
    node = shutil.which('node') or os.path.join(NODE_SRC_DIR, 'node.exe')
    if os.path.isfile(node):
        print(f"  [OK] Node.js: {node}")
    else:
        errors.append(f"未找到 Node.js，请修改 NODE_SRC_DIR")
    
    # yt-dlp
    try:
        import yt_dlp
        print(f"  [OK] yt-dlp: {yt_dlp.version.__version__}")
    except ImportError:
        errors.append("yt-dlp 未安装")
    
    # flask
    try:
        import flask
        print(f"  [OK] Flask: {flask.__version__}")
    except ImportError:
        errors.append("Flask 未安装")

    # pycryptodomex (for cookie decryption)
    try:
        from Cryptodome.Cipher import AES
        print("  [OK] pycryptodomex")
    except ImportError:
        errors.append("pycryptodomex 未安装 (pip install pycryptodomex)")

    if errors:
        print("\n  [错误] 以下问题需要修复:")
        for e in errors:
            print(f"    - {e}")
        return False
    
    print("\n  所有检查通过!")
    return True


def build():
    """执行打包"""
    if not check_tools():
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("  开始打包...")
    print("=" * 50)
    
    # 清理旧构建
    for d in [BUILD_DIR, DIST_DIR, RELEASE_DIR]:
        if os.path.exists(d):
            print(f"  清理: {d}")
            shutil.rmtree(d, ignore_errors=True)
    
    # PyInstaller 参数
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', APP_NAME,
        '--noconfirm',
        '--clean',
        # 目录模式（比 onefile 更稳定，且启动更快）
        '--onedir',
        # 不自动包含 pip 等无关包
        '--exclude-module', 'pip',
        '--exclude-module', 'setuptools',
        '--exclude-module', 'wheel',
        '--exclude-module', 'tkinter',
        '--exclude-module', 'unittest',
        '--exclude-module', 'pydoc',
        # 隐式导入
        '--hidden-import', 'cookies_reader',
        # 添加 yt_dlp_ejs 数据
        '--collect-all', 'yt_dlp_ejs',
        # 主脚本
        os.path.join(PROJECT_DIR, 'app.py'),
    ]
    
    print(f"  执行: {' '.join(cmd[:8])}...")
    result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=False)
    if result.returncode != 0:
        print("\n  [错误] PyInstaller 打包失败!")
        sys.exit(1)
    
    print("  PyInstaller 打包完成!")
    
    # ============ 复制外部工具到 dist 目录 ============
    app_dist_dir = os.path.join(DIST_DIR, APP_NAME)
    
    # 1. ffmpeg + ffprobe
    tools_ffmpeg = os.path.join(app_dist_dir, 'tools', 'ffmpeg', 'bin')
    os.makedirs(tools_ffmpeg, exist_ok=True)
    for exe in ['ffmpeg.exe', 'ffprobe.exe']:
        src = os.path.join(FFMPEG_SRC_DIR, exe)
        if os.path.isfile(src):
            dst = os.path.join(tools_ffmpeg, exe)
            shutil.copy2(src, dst)
            print(f"  复制: {exe}")
        else:
            print(f"  [跳过] {exe} 不存在")
    
    # 2. Node.js（只需要 node.exe）
    tools_node = os.path.join(app_dist_dir, 'tools', 'nodejs')
    os.makedirs(tools_node, exist_ok=True)
    node_src = os.path.join(NODE_SRC_DIR, 'node.exe')
    if os.path.isfile(node_src):
        shutil.copy2(node_src, os.path.join(tools_node, 'node.exe'))
        print(f"  复制: node.exe")
    else:
        print(f"  [跳过] node.exe 不存在")
    
    # 3. Cookies 文件
    if os.path.isfile(COOKIES_SRC):
        shutil.copy2(COOKIES_SRC, os.path.join(app_dist_dir, 'cookies.txt'))
        print(f"  复制: cookies.txt")
    
    # 4. 创建使用说明
    readme = """# YouTube 视频下载器 使用说明

## 使用方法
1. 双击"启动下载器.bat"启动服务（会请求管理员权限）
2. 浏览器自动打开 http://127.0.0.1:5000
3. 在设置中选择浏览器，点击"自动读取"提取 cookies
4. 粘贴 YouTube 视频链接，选择格式，点击下载

## 启动方式
- 启动下载器.bat    管理员模式（推荐，可自动读取浏览器 cookies）
- 普通模式启动.bat  普通模式（cookies 需手动导入）

## 注意事项
- 需要代理/VPN 才能访问 YouTube
- 程序会自动检测系统代理设置
- 下载的视频保存在 downloads 文件夹中
- 可以在设置中修改保存目录
- cookies 自动读取会暂时关闭目标浏览器
- 如 cookies 过期，重新点击"自动读取"即可

## 文件结构
- YouTubeDownloader.exe  主程序
- tools/ffmpeg/           视频处理工具
- tools/nodejs/           JS 运行时（YouTube 解析必需）
- cookies.txt             YouTube 登录凭据（自动生成）
- downloads/              下载的视频文件

## 关闭程序
- 关闭命令行窗口，或按 Ctrl+C 停止服务
"""
    with open(os.path.join(app_dist_dir, '使用说明.txt'), 'w', encoding='utf-8') as f:
        f.write(readme)
    print("  创建: 使用说明.txt")
    
    # 5. 创建启动脚本（自动请求管理员权限）
    # 使用 VBS helper 请求 UAC 提权（比 PowerShell 更可靠）
    start_bat = '@echo off\r\n'
    start_bat += 'chcp 65001 >nul\r\n'
    start_bat += 'net session >nul 2>&1\r\n'
    start_bat += 'if %errorlevel% neq 0 (\r\n'
    start_bat += '    echo.\r\n'
    start_bat += '    echo   YouTube 视频下载器 - 请求管理员权限\r\n'
    start_bat += '    echo.\r\n'
    start_bat += '    echo   Windows 将弹出 UAC 提示，请点击 [是]\r\n'
    start_bat += '    echo.\r\n'
    start_bat += '    echo Set UAC = CreateObject("Shell.Application") > "%temp%\\yt_uac.vbs"\r\n'
    start_bat += '    echo UAC.ShellExecute "cmd", "/c cd /d ""%~dp0"" && YouTubeDownloader.exe && pause", "", "runas", 1 >> "%temp%\\yt_uac.vbs"\r\n'
    start_bat += '    wscript "%temp%\\yt_uac.vbs"\r\n'
    start_bat += '    del "%temp%\\yt_uac.vbs" >nul 2>&1\r\n'
    start_bat += '    exit /b\r\n'
    start_bat += ')\r\n'
    start_bat += 'cd /d "%~dp0"\r\n'
    start_bat += 'title YouTube 视频下载器 [管理员模式]\r\n'
    start_bat += 'echo ================================================\r\n'
    start_bat += 'echo   YouTube 视频下载器\r\n'
    start_bat += 'echo ================================================\r\n'
    start_bat += 'echo.\r\n'
    start_bat += 'echo   [管理员模式] - 可自动读取浏览器 cookies\r\n'
    start_bat += 'echo   启动中... 浏览器将自动打开 http://127.0.0.1:5000\r\n'
    start_bat += 'echo.\r\n'
    start_bat += 'echo   关闭此窗口即可停止服务\r\n'
    start_bat += 'echo ================================================\r\n'
    start_bat += 'echo.\r\n'
    start_bat += 'start "" "http://127.0.0.1:5000"\r\n'
    start_bat += 'YouTubeDownloader.exe\r\n'
    start_bat += 'pause\r\n'
    with open(os.path.join(app_dist_dir, '启动下载器.bat'), 'w', encoding='utf-8') as f:
        f.write(start_bat)
    print("  创建: 启动下载器.bat")

    # 6. 创建普通模式启动脚本（不请求管理员权限，cookies 需手动导入）
    start_normal_bat = f"""@echo off
chcp 65001 >nul
title YouTube 视频下载器 [普通模式]
echo ================================================
echo   YouTube 视频下载器
echo ================================================
echo.
echo   [普通模式] - cookies 读取功能不可用
echo   如需自动读取浏览器 cookies，请使用"启动下载器.bat"
echo.
echo   启动中... 浏览器将自动打开 http://127.0.0.1:5000
echo.
start "" "http://127.0.0.1:5000"
YouTubeDownloader.exe
pause
"""
    with open(os.path.join(app_dist_dir, '普通模式启动.bat'), 'w', encoding='utf-8') as f:
        f.write(start_normal_bat)
    print("  创建: 普通模式启动.bat")

    # 7. 创建静默启动脚本（无控制台窗口）
    start_silent_bat = f"""@echo off
start "" "http://127.0.0.1:5000"
start /min "" YouTubeDownloader.exe
"""
    with open(os.path.join(app_dist_dir, '静默启动.bat'), 'w', encoding='utf-8') as f:
        f.write(start_silent_bat)
    print("  创建: 静默启动.bat")
    
    # 7. 复制 requirements.txt（方便用户看依赖）
    if os.path.exists(os.path.join(PROJECT_DIR, 'requirements.txt')):
        shutil.copy2(os.path.join(PROJECT_DIR, 'requirements.txt'), 
                     os.path.join(app_dist_dir, 'requirements.txt'))
    
    print("\n" + "=" * 50)
    print("  打包完成!")
    print(f"  输出目录: {app_dist_dir}")
    
    # 计算大小
    total_size = 0
    for root, dirs, files in os.walk(app_dist_dir):
        for f in files:
            total_size += os.path.getsize(os.path.join(root, f))
    print(f"  总大小: {total_size / 1024 / 1024:.1f} MB")
    print("=" * 50)


if __name__ == '__main__':
    build()

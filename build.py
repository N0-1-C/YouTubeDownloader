"""
YouTube Downloader - PyInstaller 打包配置
打包为独立可分发的目录，包含所有依赖和外部工具
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

    # flask-cors
    try:
        import flask_cors
        print(f"  [OK] Flask-CORS: {flask_cors.__version__}")
    except ImportError:
        errors.append("Flask-CORS 未安装")

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
        # 不自动包含无关包
        '--exclude-module', 'pip',
        '--exclude-module', 'setuptools',
        '--exclude-module', 'wheel',
        '--exclude-module', 'tkinter',
        '--exclude-module', 'unittest',
        '--exclude-module', 'pydoc',
        '--exclude-module', 'pytest',
        '--exclude-module', 'IPython',
        '--exclude-module', 'jupyter',
        '--exclude-module', 'notebook',
        '--exclude-module', 'matplotlib',
        '--exclude-module', 'numpy',
        '--exclude-module', 'pandas',
        # 收集 yt_dlp_ejs 数据文件
        '--collect-all', 'yt_dlp_ejs',
        # 收集 certifi 的 CA 证书（HTTPS 信任链）
        '--collect-data', 'certifi',
        # 主脚本
        os.path.join(PROJECT_DIR, 'app.py'),
    ]

    print(f"  执行 PyInstaller...")
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
            print(f"  [跳过] {exe} 不存在于 {FFMPEG_SRC_DIR}")

    # 2. Node.js（只需要 node.exe）
    tools_node = os.path.join(app_dist_dir, 'tools', 'nodejs')
    os.makedirs(tools_node, exist_ok=True)
    node_src = os.path.join(NODE_SRC_DIR, 'node.exe')
    if os.path.isfile(node_src):
        shutil.copy2(node_src, os.path.join(tools_node, 'node.exe'))
        print(f"  复制: node.exe")
    else:
        print(f"  [跳过] node.exe 不存在于 {NODE_SRC_DIR}")

    # 3. 创建使用说明
    readme = """# YouTube 视频下载器 使用说明

## 使用方法
1. 双击 "启动下载器.bat" 启动服务
2. 浏览器自动打开 http://127.0.0.1:5000
3. 粘贴 YouTube 视频链接，选择格式，点击下载

## 启动方式
- 启动下载器.bat    标准启动（推荐）
- 静默启动.bat      最小化窗口启动

## Cookies 导入（可选，用于下载会员/受限视频）
1. 在 Chrome 安装插件 "Get cookies.txt LOCALLY"
2. 在浏览器中登录 YouTube
3. 访问 youtube.com，点击插件导出 cookies 文件
4. 在下载器网页设置中点击「选择文件」导入

## 注意事项
- 需要代理/VPN 才能访问 YouTube
- 程序会自动检测系统代理设置
- 默认下载到桌面，可在设置中修改保存目录
- 下载完成后默认自动打开文件夹，可在设置中关闭

## 文件结构
- YouTubeDownloader.exe  主程序
- tools/ffmpeg/           视频处理工具
- tools/nodejs/           JS 运行时（YouTube 解析必需）
- 使用说明.txt             本文件

## 关闭程序
- 关闭命令行窗口即可停止服务
"""
    with open(os.path.join(app_dist_dir, '使用说明.txt'), 'w', encoding='utf-8') as f:
        f.write(readme)
    print("  创建: 使用说明.txt")

    # 4. 创建启动脚本
    start_bat = '@echo off\r\n'
    start_bat += 'chcp 65001 >nul\r\n'
    start_bat += 'cd /d "%~dp0"\r\n'
    start_bat += 'title YouTube 视频下载器\r\n'
    start_bat += 'echo ================================================\r\n'
    start_bat += 'echo   YouTube 视频下载器\r\n'
    start_bat += 'echo ================================================\r\n'
    start_bat += 'echo.\r\n'
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

    # 5. 创建静默启动脚本（最小化窗口）
    start_silent_bat = '@echo off\r\n'
    start_silent_bat += 'cd /d "%~dp0"\r\n'
    start_silent_bat += 'start "" "http://127.0.0.1:5000"\r\n'
    start_silent_bat += 'start /min "" YouTubeDownloader.exe\r\n'
    with open(os.path.join(app_dist_dir, '静默启动.bat'), 'w', encoding='utf-8') as f:
        f.write(start_silent_bat)
    print("  创建: 静默启动.bat")

    # 6. 复制使用文档
    doc_src = os.path.join(PROJECT_DIR, '使用文档.md')
    if os.path.exists(doc_src):
        shutil.copy2(doc_src, os.path.join(app_dist_dir, '使用文档.md'))
        print("  复制: 使用文档.md")

    # ============ 打包为 ZIP 发行 ============
    print("\n  正在打包 ZIP...")
    zip_name = f'{APP_NAME}'
    zip_path = os.path.join(PROJECT_DIR, f'{zip_name}.zip')
    if os.path.exists(zip_path):
        os.remove(zip_path)
    shutil.make_archive(os.path.join(PROJECT_DIR, zip_name), 'zip', DIST_DIR, APP_NAME)

    print("\n" + "=" * 50)
    print("  打包完成!")
    print(f"  输出目录: {app_dist_dir}")
    print(f"  ZIP 文件: {zip_path}")

    # 计算大小
    total_size = 0
    for root, dirs, files in os.walk(app_dist_dir):
        for f in files:
            total_size += os.path.getsize(os.path.join(root, f))
    print(f"  目录大小: {total_size / 1024 / 1024:.1f} MB")
    print(f"  ZIP 大小: {os.path.getsize(zip_path) / 1024 / 1024:.1f} MB")
    print("=" * 50)


if __name__ == '__main__':
    build()

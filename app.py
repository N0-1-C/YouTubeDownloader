"""
YouTube 视频下载器 - 基于 yt-dlp + Flask 的 Web 应用
支持：视频链接解析、格式选择、实时下载进度、文件下载
"""
import os
import re
import sys
import json
import shutil
import threading
import uuid
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
import yt_dlp

# ============ 路径配置（兼容开发模式和 PyInstaller 打包模式）============
def _get_base_dir():
    """获取应用根目录，兼容 PyInstaller 打包"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后：exe 所在目录
        return os.path.dirname(sys.executable)
    else:
        # 开发模式：项目根目录
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _get_base_dir()

def _find_executable(name, extra_paths=None):
    """在系统 PATH 和额外路径中查找可执行文件"""
    # 1. 系统 PATH
    found = shutil.which(name)
    if found:
        return found
    # 2. 额外路径
    if extra_paths:
        for p in extra_paths:
            if not p:
                continue
            exe_path = os.path.join(p, name)
            if os.name == 'nt':
                exe_path += '.exe'
            if os.path.isfile(exe_path):
                return exe_path
    return None

# ffmpeg / ffprobe 路径
_FFMPEG_EXTRA_PATHS = [
    os.path.join(BASE_DIR, 'tools', 'ffmpeg', 'bin'),
    os.path.join(BASE_DIR, 'ffmpeg', 'bin'),
    r'C:\ffmpeg\bin',
    r'C:\Users\pc\ffmpeg\bin',
]
FFMPEG_PATH = _find_executable('ffmpeg', _FFMPEG_EXTRA_PATHS)
FFPROBE_PATH = _find_executable('ffprobe', _FFMPEG_EXTRA_PATHS)

# Node.js 路径
_NODE_EXTRA_PATHS = [
    os.path.join(BASE_DIR, 'tools', 'nodejs'),
    os.path.join(BASE_DIR, 'tools', 'node'),
    r'C:\Program Files\nodejs',
    r'C:\Program Files (x86)\nodejs',
    os.path.join(os.environ.get('ProgramFiles', ''), 'nodejs'),
    os.path.join(os.environ.get('ProgramFiles(x86)', ''), 'nodejs'),
]
NODE_PATH = _find_executable('node', _NODE_EXTRA_PATHS)

# 下载目录
DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Desktop')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 将外部工具目录加入 PATH（让子进程能找到）
if FFMPEG_PATH:
    ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
    os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')
if NODE_PATH:
    node_dir = os.path.dirname(NODE_PATH)
    os.environ['PATH'] = node_dir + os.pathsep + os.environ.get('PATH', '')

app = Flask(__name__)
CORS(app)

# ============ 代理检测 ============
def _detect_proxy():
    for key in ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy'):
        val = os.environ.get(key, '')
        if val:
            return val
    import urllib.request
    try:
        proxy = urllib.request.getproxies().get('https') or urllib.request.getproxies().get('http')
        if proxy:
            return proxy
    except Exception:
        pass
    return ''

PROXY_URL = _detect_proxy()
if not PROXY_URL:
    for port in [7890, 11649, 10808, 10809, 1080, 8080]:
        import urllib.request
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}', timeout=1)
            PROXY_URL = f'http://127.0.0.1:{port}'
            break
        except Exception:
            continue

# 手动 cookies 文件路径
COOKIES_FILE = ''

# 下载完成后自动打开文件夹
AUTO_OPEN_FOLDER = True

# ============ 工具函数 ============
def _build_js_runtimes():
    """构建 js_runtimes 配置"""
    if NODE_PATH:
        return {'node': {'path': NODE_PATH}}
    return {}

def _get_ffmpeg_location():
    """获取 ffmpeg 路径配置"""
    if FFMPEG_PATH:
        return FFMPEG_PATH
    return ''

# 任务存储
tasks = {}


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def is_youtube_url(url):
    """验证是否为有效的 YouTube 链接"""
    patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/shorts/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/embed/[\w-]+',
        r'(https?://)?youtu\.be/[\w-]+',
    ]
    return any(re.match(p, url) for p in patterns)


class DownloadProgressHook:
    """下载进度钩子"""
    def __init__(self, task_id):
        self.task_id = task_id
        self._last_update = 0

    def __call__(self, d):
        if self.task_id not in tasks:
            return
        task = tasks[self.task_id]
        now = datetime.now().timestamp()

        # 限制更新频率，避免过于频繁
        if now - self._last_update < 0.3 and d['status'] == 'downloading':
            return
        self._last_update = now

        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)

            if total > 0:
                percent = round(downloaded / total * 100, 1)
            else:
                percent = 0

            task['progress'] = percent
            task['status'] = 'downloading'
            task['downloaded'] = downloaded
            task['total'] = total
            task['speed'] = speed
            task['eta'] = eta

        elif d['status'] == 'finished':
            task['progress'] = 100
            task['status'] = 'finished'
            task['message'] = '下载完成，正在处理文件...'

        elif d['status'] == 'error':
            task['status'] = 'error'
            task['message'] = f"下载出错: {d.get('error', '未知错误')}"

        elif d['status'] == 'processing':
            task['status'] = 'processing'
            task['message'] = '正在处理视频...'


def get_format_options(url):
    """获取视频可用格式列表"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        # 不自动选择格式，只获取格式列表
        'format': 'best',
        # 只在下载时忽略错误，解析时仍然报告
        'ignoreerrors': 'only_download',
        # 代理设置（自动检测）
        'proxy': PROXY_URL or '',
        # SSL 相关
        'legacy_server_connect': True,
        'no_check_certificates': True,
        # 超时设置
        'socket_timeout': 120,
        # 启用 Node.js 运行时（解决 YouTube n parameter challenge）
        'js_runtimes': _build_js_runtimes(),
        # ffmpeg 路径
        'ffmpeg_location': _get_ffmpeg_location() or None,
    }
    # Cookies：手动导入的 cookies 文件
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        if info is None:
            raise Exception('无法获取视频信息，可能视频不可用或被限制访问')
        
        if not isinstance(info, dict):
            raise Exception(f'视频信息格式异常: {type(info).__name__}')
        
        # 视频信息
        video_info = {
            'id': info.get('id'),
            'title': info.get('title'),
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration'),
            'description': info.get('description', '')[:200],
            'uploader': info.get('uploader'),
        }

        # 格式列表
        formats = []
        seen = set()

        # 添加预设选项
        formats.append({
            'format_id': 'best',
            'label': '最佳画质 (视频+音频)',
            'ext': 'mp4',
            'resolution': info.get('resolution', '自动'),
            'filesize': info.get('filesize') or info.get('filesize_approx'),
            'vcodec': '-',
            'acodec': '-',
            'preset': True,
        })
        formats.append({
            'format_id': 'bestaudio',
            'label': '最佳音频 (MP3)',
            'ext': 'mp3',
            'resolution': '仅音频',
            'filesize': None,
            'vcodec': '无',
            'acodec': 'mp3',
            'preset': True,
        })

        for f in info.get('formats', []):
            if not f.get('vcodec') or f.get('vcodec') == 'none':
                # 纯音频格式，跳过（已有预设）
                continue
            fid = f.get('format_id', '')
            if fid in seen:
                continue
            seen.add(fid)

            resolution = f.get('resolution') or f"{f.get('width', '?')}x{f.get('height', '?')}"
            filesize = f.get('filesize') or f.get('filesize_approx')
            vcodec = f.get('vcodec', '?')
            # 简化编码显示
            if 'avc' in vcodec or 'h264' in vcodec:
                vcodec = 'H.264'
            elif 'hev' in vcodec or 'h265' in vcodec:
                vcodec = 'H.265'
            elif 'vp9' in vcodec:
                vcodec = 'VP9'
            elif 'av01' in vcodec:
                vcodec = 'AV1'

            acodec = f.get('acodec', '?')
            if 'opus' in str(acodec).lower():
                acodec = 'Opus'
            elif 'aac' in str(acodec).lower():
                acodec = 'AAC'
            elif 'mp4a' in str(acodec).lower():
                acodec = 'AAC'

            formats.append({
                'format_id': fid,
                'label': f"{resolution} {f.get('ext', '?')} {vcodec}",
                'ext': f.get('ext', '?'),
                'resolution': resolution,
                'filesize': filesize,
                'vcodec': vcodec,
                'acodec': acodec,
                'preset': False,
            })

        return video_info, formats


def download_video(task_id, url, format_id, is_audio, save_dir):
    """在后台线程中下载视频"""
    task = tasks[task_id]
    task['status'] = 'fetching'
    task['message'] = '正在获取视频信息...'

    try:
        ydl_opts = {
            'progress_hooks': [DownloadProgressHook(task_id)],
            'outtmpl': os.path.join(save_dir, '%(title)s.%(ext)s'),
            'restrictfilenames': True,
            'max_filename_length': 200,
            'nooverwrites': True,
            # 代理设置（自动检测）
            'proxy': PROXY_URL or '',
            # SSL 相关
            'legacy_server_connect': True,
            'no_check_certificates': True,
            # 超时设置（秒）
            'socket_timeout': 120,
            # 网络相关：增强稳定性
            'retries': 20,
            'fragment_retries': 20,
            'skip_unavailable_fragments': True,
            'keep_fragments': False,
            'http_chunk_size': 10485760,
            # 限速：避免触发 YouTube 反爬
            'throttledratelimit': 100000,
            # buffering
            'buffersize': 16384,
            # 启用 Node.js 运行时（解决 YouTube n parameter challenge）
            'js_runtimes': _build_js_runtimes(),
            # ffmpeg 路径
            'ffmpeg_location': _get_ffmpeg_location() or None,
        }
        # 使用手动导入的 cookies 文件
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE

        if is_audio:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif format_id == 'best':
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'
            ydl_opts['merge_output_format'] = 'mp4'
        else:
            ydl_opts['format'] = f'{format_id}+bestaudio[ext=m4a]/bestaudio/best'

        task['message'] = '开始下载...'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if info is None:
                raise Exception('下载失败：无法获取视频信息')
            
            filename = ydl.prepare_filename(info)
            
            # 如果是音频提取，查找实际生成的文件
            if is_audio:
                basename = os.path.splitext(os.path.basename(filename))[0]
                mp3_file = os.path.join(save_dir, basename + '.mp3')
                if os.path.exists(mp3_file):
                    filename = mp3_file
                else:
                    # 查找下载目录中最近的 mp3 文件
                    mp3_files = [f for f in os.listdir(save_dir) if f.endswith('.mp3')]
                    if mp3_files:
                        mp3_files.sort(key=lambda x: os.path.getmtime(os.path.join(save_dir, x)), reverse=True)
                        filename = os.path.join(save_dir, mp3_files[0])

            task['status'] = 'completed'
            task['progress'] = 100
            task['message'] = '下载完成！'
            task['filename'] = filename
            task['display_name'] = os.path.basename(filename)

            # 下载完成后自动打开文件夹
            if AUTO_OPEN_FOLDER and os.path.isdir(save_dir):
                try:
                    subprocess.Popen(f'explorer "{os.path.normpath(save_dir)}"')
                except Exception:
                    pass

    except Exception as e:
        task['status'] = 'error'
        task['message'] = f'下载失败: {str(e)}'
        task['progress'] = 0


# ============ 路由 ============

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/info', methods=['POST'])
def get_info():
    """解析视频链接，获取视频信息和格式列表"""
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'success': False, 'message': '请输入视频链接'}), 400

    if not is_youtube_url(url):
        return jsonify({'success': False, 'message': '请输入有效的 YouTube 链接'}), 400

    try:
        video_info, formats = get_format_options(url)
        return jsonify({
            'success': True,
            'video': video_info,
            'formats': formats,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'解析失败: {str(e)}'}), 500


@app.route('/api/download', methods=['POST'])
def start_download():
    """开始下载任务"""
    data = request.get_json()
    url = data.get('url', '').strip()
    format_id = data.get('format_id', 'best')
    save_dir = data.get('save_dir', '').strip()

    if not url:
        return jsonify({'success': False, 'message': '请输入视频链接'}), 400

    if not is_youtube_url(url):
        return jsonify({'success': False, 'message': '请输入有效的 YouTube 链接'}), 400

    # 确定保存目录
    if not save_dir:
        save_dir = DOWNLOAD_DIR
    if not os.path.isdir(save_dir):
        return jsonify({'success': False, 'message': f'目录不存在: {save_dir}'}), 400

    task_id = str(uuid.uuid4())[:8]
    is_audio = format_id == 'bestaudio'

    tasks[task_id] = {
        'id': task_id,
        'url': url,
        'format_id': format_id,
        'status': 'pending',
        'progress': 0,
        'message': '任务已创建，等待开始...',
        'filename': None,
        'display_name': None,
        'downloaded': 0,
        'total': 0,
        'speed': 0,
        'eta': 0,
        'created_at': datetime.now().isoformat(),
    }

    thread = threading.Thread(
        target=download_video,
        args=(task_id, url, format_id, is_audio, save_dir),
        daemon=True
    )
    thread.start()

    return jsonify({'success': True, 'task_id': task_id})


@app.route('/api/progress/<task_id>')
def get_progress(task_id):
    """查询下载进度"""
    if task_id not in tasks:
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    task = tasks[task_id]
    return jsonify({
        'success': True,
        'task_id': task['id'],
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'speed': task.get('speed', 0),
        'eta': task.get('eta', 0),
        'downloaded': task.get('downloaded', 0),
        'total': task.get('total', 0),
        'display_name': task.get('display_name'),
    })


@app.route('/api/file/<task_id>')
def download_file(task_id):
    """下载已完成的文件"""
    if task_id not in tasks:
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    task = tasks[task_id]
    filename = task.get('filename')

    if not filename or not os.path.exists(filename):
        return jsonify({'success': False, 'message': '文件不存在'}), 404

    display_name = task.get('display_name', os.path.basename(filename))
    return send_file(
        filename,
        as_attachment=True,
        download_name=display_name,
    )


@app.route('/api/tasks')
def list_tasks():
    """列出所有任务"""
    result = []
    for tid, task in tasks.items():
        result.append({
            'id': task['id'],
            'status': task['status'],
            'progress': task['progress'],
            'message': task['message'],
            'display_name': task.get('display_name'),
            'created_at': task.get('created_at'),
        })
    result.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify({'success': True, 'tasks': result})


@app.route('/api/save-dir', methods=['GET', 'POST'])
def save_dir():
    """获取或设置下载目录"""
    global DOWNLOAD_DIR

    if request.method == 'GET':
        return jsonify({'success': True, 'dir': DOWNLOAD_DIR})

    data = request.get_json()
    new_dir = data.get('dir', '').strip()
    if not new_dir:
        return jsonify({'success': False, 'message': '请提供目录路径'}), 400

    if not os.path.isdir(new_dir):
        return jsonify({'success': False, 'message': f'目录不存在: {new_dir}'}), 400

    DOWNLOAD_DIR = new_dir
    return jsonify({'success': True, 'dir': DOWNLOAD_DIR, 'message': f'下载目录已更新为: {DOWNLOAD_DIR}'})


@app.route('/api/cookies', methods=['GET', 'POST'])
def cookies_setting():
    """获取或设置手动 cookies 文件"""
    global COOKIES_FILE

    if request.method == 'GET':
        return jsonify({
            'success': True,
            'cookies_file': COOKIES_FILE,
        })

    # 支持两种方式：JSON 传路径 或 FormData 上传文件
    content_type = request.content_type or ''

    if 'multipart/form-data' in content_type:
        # 文件上传方式
        f = request.files.get('cookies_file')
        if not f:
            return jsonify({'success': False, 'message': '未接收到文件'}), 400
        # 保存到应用目录下
        save_path = os.path.join(BASE_DIR, 'cookies.txt')
        f.save(save_path)
        COOKIES_FILE = save_path
        return jsonify({'success': True, 'cookies_file': COOKIES_FILE, 'message': f'已导入 cookies 文件 (cookies.txt)'})
    else:
        # JSON 传路径方式（兼容）
        data = request.get_json()
        cookies_file = data.get('cookies_file', '').strip() if data else ''

        if not cookies_file:
            COOKIES_FILE = ''
            return jsonify({'success': True, 'cookies_file': '', 'message': '已清除 cookies 文件'})

        # 如果是相对路径，尝试在应用目录下查找
        if not os.path.isabs(cookies_file):
            cookies_file = os.path.join(BASE_DIR, cookies_file)

        if not os.path.exists(cookies_file):
            return jsonify({'success': False, 'message': f'cookies 文件不存在: {cookies_file}'}), 400

        COOKIES_FILE = cookies_file
        return jsonify({'success': True, 'cookies_file': COOKIES_FILE, 'message': f'已加载 cookies 文件'})


@app.route('/api/auto-open', methods=['GET', 'POST'])
def auto_open_setting():
    """获取或设置下载完成后是否自动打开文件夹"""
    global AUTO_OPEN_FOLDER

    if request.method == 'GET':
        return jsonify({'success': True, 'auto_open': AUTO_OPEN_FOLDER})

    data = request.get_json()
    auto_open = data.get('auto_open', True) if data else True
    AUTO_OPEN_FOLDER = bool(auto_open)
    return jsonify({'success': True, 'auto_open': AUTO_OPEN_FOLDER, 'message': f'已{"开启" if AUTO_OPEN_FOLDER else "关闭"}自动打开文件夹'})


@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """关闭服务器"""
    threading.Thread(target=shutdown_server, daemon=True).start()
    return jsonify({'success': True, 'message': '服务正在关闭...'})







def format_size(size_bytes):
    """格式化文件大小"""
    if size_bytes is None:
        return '未知'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds):
    """格式化时长"""
    if not seconds:
        return '未知'
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ============ HTML 模板 ============

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube 视频下载器</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --bg: #0f0f0f;
            --surface: #1a1a1a;
            --surface2: #242424;
            --border: #333;
            --text: #e8e8e8;
            --text2: #888;
            --accent: #ff4444;
            --accent2: #ff6666;
            --green: #00c853;
            --blue: #448aff;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            line-height: 1.6;
        }

        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
        }

        .header {
            text-align: center;
            margin-bottom: 40px;
        }

        .header h1 {
            font-size: 2rem;
            background: linear-gradient(135deg, var(--accent), #ff8a80);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }

        .header p {
            color: var(--text2);
            font-size: 0.9rem;
        }

        .shutdown-btn {
            position: fixed;
            top: 16px;
            right: 16px;
            padding: 6px 16px;
            font-size: 0.8rem;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--surface2);
            color: var(--text2);
            cursor: pointer;
            transition: all 0.2s;
            z-index: 100;
        }

        .shutdown-btn:hover {
            background: rgba(255, 68, 68, 0.15);
            border-color: var(--accent);
            color: var(--accent);
        }

        .input-section {
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }

        .url-input {
            flex: 1;
            padding: 14px 18px;
            background: var(--surface);
            border: 2px solid var(--border);
            border-radius: 12px;
            color: var(--text);
            font-size: 1rem;
            outline: none;
            transition: border-color 0.3s;
        }

        .url-input:focus {
            border-color: var(--accent);
        }

        .url-input::placeholder {
            color: var(--text2);
        }

        .btn {
            padding: 14px 28px;
            border: none;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            white-space: nowrap;
        }

        .btn-primary {
            background: var(--accent);
            color: white;
        }

        .btn-primary:hover {
            background: var(--accent2);
            transform: translateY(-1px);
        }

        .btn-primary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .btn-small {
            padding: 6px 14px;
            font-size: 0.85rem;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--card);
            color: var(--text);
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-small:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        .btn-small:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-secondary {
            background: var(--surface2);
            color: var(--text);
            border: 1px solid var(--border);
        }

        .btn-secondary:hover {
            background: var(--border);
        }

        .btn-download {
            background: var(--green);
            color: white;
            padding: 8px 16px;
            font-size: 0.85rem;
        }

        .btn-download:hover {
            filter: brightness(1.1);
        }

        .btn-sm {
            padding: 8px 14px;
            font-size: 0.8rem;
            border-radius: 8px;
        }

        /* 设置区域 */
        .settings-section {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
        }

        .settings-section h3 {
            font-size: 0.95rem;
            color: var(--text2);
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            user-select: none;
        }

        .settings-section h3 .arrow {
            transition: transform 0.3s;
            font-size: 0.8rem;
        }

        .settings-section h3 .arrow.open {
            transform: rotate(90deg);
        }

        .settings-body {
            display: none;
        }

        .settings-body.show { display: block; }

        .save-dir-row {
            display: flex;
            gap: 10px;
            align-items: center;
        }

        .dir-input {
            flex: 1;
            padding: 10px 14px;
            background: var(--surface2);
            border: 2px solid var(--border);
            border-radius: 10px;
            color: var(--text);
            font-size: 0.9rem;
            font-family: 'Consolas', 'Monaco', monospace;
            outline: none;
            transition: border-color 0.3s;
        }

        .dir-input:focus {
            border-color: var(--accent);
        }

        .dir-hint {
            color: var(--text2);
            font-size: 0.8rem;
            margin-top: 8px;
        }

        .dir-current {
            color: var(--green);
            font-size: 0.85rem;
            margin-top: 10px;
        }

        /* Cookies 手动导入 */
        .cookies-row {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--border);
        }

        .cookies-label {
            font-size: 0.9rem;
            color: var(--text2);
            margin-bottom: 8px;
            display: block;
        }

        .cookies-file-row {
            display: flex;
            gap: 10px;
            align-items: center;
        }

        .cookies-file-input {
            flex: 1;
            padding: 8px 12px;
            background: var(--surface2);
            border: 2px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-size: 0.85rem;
            font-family: 'Consolas', 'Monaco', monospace;
            outline: none;
            transition: border-color 0.3s;
        }

        .cookies-file-input:focus {
            border-color: var(--accent);
        }

        .cookies-file-label {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            background: var(--surface2);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.2s;
        }

        .cookies-file-label:hover {
            background: var(--border);
        }

        .cookies-file-label input[type="file"] {
            display: none;
        }

        .cookies-hint {
            color: var(--text2);
            font-size: 0.8rem;
            margin-top: 8px;
        }

        .cookies-warning {
            color: #ffab00;
            font-size: 0.8rem;
            margin-top: 8px;
            padding: 8px 12px;
            background: rgba(255, 171, 0, 0.1);
            border-radius: 6px;
        }

        /* 自动打开文件夹开关 */
        .setting-row {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--border);
        }

        .setting-label {
            font-size: 0.9rem;
            color: var(--text2);
            flex: 1;
        }

        .switch-toggle {
            position: relative;
            width: 40px;
            height: 22px;
            background: var(--border);
            border-radius: 11px;
            cursor: pointer;
            transition: background 0.3s;
            flex-shrink: 0;
        }

        .switch-toggle.active {
            background: var(--green);
        }

        .switch-toggle::after {
            content: '';
            position: absolute;
            top: 2px;
            left: 2px;
            width: 18px;
            height: 18px;
            background: white;
            border-radius: 50%;
            transition: transform 0.3s;
        }

        .switch-toggle.active::after {
            transform: translateX(18px);
        }

        .video-info {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            display: none;
        }

        .video-info.show { display: block; }

        .video-meta {
            display: flex;
            gap: 16px;
            margin-bottom: 16px;
        }

        .video-thumb {
            width: 200px;
            height: 112px;
            border-radius: 8px;
            object-fit: cover;
            background: var(--surface2);
            flex-shrink: 0;
        }

        .video-details { flex: 1; }

        .video-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 6px;
            line-height: 1.4;
        }

        .video-stats {
            color: var(--text2);
            font-size: 0.85rem;
        }

        .format-section h3 {
            font-size: 0.95rem;
            margin-bottom: 12px;
            color: var(--text2);
        }

        .format-grid {
            display: grid;
            gap: 8px;
            margin-bottom: 16px;
            max-height: 320px;
            overflow-y: auto;
            padding-right: 4px;
        }

        .format-grid::-webkit-scrollbar {
            width: 6px;
        }

        .format-grid::-webkit-scrollbar-track {
            background: transparent;
        }

        .format-grid::-webkit-scrollbar-thumb {
            background: var(--border);
            border-radius: 3px;
        }

        .format-grid::-webkit-scrollbar-thumb:hover {
            background: var(--text3);
        }

        .format-option {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: var(--surface2);
            border: 2px solid transparent;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .format-option:hover {
            border-color: var(--border);
        }

        .format-option.selected {
            border-color: var(--accent);
            background: rgba(255, 68, 68, 0.1);
        }

        .format-option input[type="radio"] {
            display: none;
        }

        .format-radio {
            width: 18px;
            height: 18px;
            border: 2px solid var(--border);
            border-radius: 50%;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }

        .format-option.selected .format-radio {
            border-color: var(--accent);
        }

        .format-option.selected .format-radio::after {
            content: '';
            width: 10px;
            height: 10px;
            background: var(--accent);
            border-radius: 50%;
        }

        .format-label { flex: 1; }

        .format-name {
            font-weight: 600;
            font-size: 0.9rem;
            margin-bottom: 2px;
        }

        .format-detail {
            color: var(--text2);
            font-size: 0.8rem;
        }

        .format-size {
            color: var(--text2);
            font-size: 0.85rem;
            flex-shrink: 0;
        }

        .preset-badge {
            display: inline-block;
            background: var(--accent);
            color: white;
            font-size: 0.7rem;
            padding: 1px 6px;
            border-radius: 4px;
            margin-left: 6px;
        }

        .download-actions {
            display: flex;
            gap: 12px;
            position: sticky;
            bottom: -24px;
            padding: 16px 0 4px;
            margin: 0 -24px -24px;
            padding-left: 24px;
            padding-right: 24px;
            background: linear-gradient(to top, var(--surface) 70%, transparent);
            z-index: 10;
        }

        .progress-section {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
            display: none;
        }

        .progress-section.show { display: block; }

        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .progress-status {
            font-weight: 600;
        }

        .progress-percent {
            font-size: 1.2rem;
            font-weight: 700;
            color: var(--accent);
        }

        .progress-bar-bg {
            width: 100%;
            height: 8px;
            background: var(--surface2);
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 12px;
        }

        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--accent), var(--accent2));
            border-radius: 4px;
            transition: width 0.3s;
            width: 0%;
        }

        .progress-details {
            display: flex;
            justify-content: space-between;
            color: var(--text2);
            font-size: 0.85rem;
        }

        .error-msg {
            color: var(--accent);
            padding: 16px;
            background: rgba(255, 68, 68, 0.1);
            border-radius: 10px;
            margin-bottom: 20px;
            display: none;
        }

        .error-msg.show { display: block; }

        .success-section {
            text-align: center;
            padding: 24px;
            background: rgba(0, 200, 83, 0.1);
            border: 1px solid var(--green);
            border-radius: 16px;
            display: none;
        }

        .success-section.show { display: block; }

        .success-icon {
            font-size: 3rem;
            margin-bottom: 12px;
        }

        .success-text {
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 6px;
        }

        .success-filename {
            color: var(--text2);
            font-size: 0.9rem;
            word-break: break-all;
            margin-bottom: 16px;
        }

        .history-section {
            margin-top: 40px;
        }

        .history-section h2 {
            font-size: 1.1rem;
            margin-bottom: 16px;
            color: var(--text2);
        }

        .history-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            margin-bottom: 8px;
        }

        .history-status {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .history-status.completed { background: var(--green); }
        .history-status.error { background: var(--accent); }
        .history-status.downloading { background: var(--blue); animation: pulse 1.5s infinite; }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        .history-info { flex: 1; }
        .history-name { font-size: 0.9rem; font-weight: 500; }
        .history-time { color: var(--text2); font-size: 0.8rem; }

        .loading-spinner {
            display: inline-block;
            width: 18px;
            height: 18px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        @media (max-width: 600px) {
            .input-section { flex-direction: column; }
            .video-meta { flex-direction: column; }
            .video-thumb { width: 100%; height: auto; }
        }
    </style>
</head>
<body>
    <button class="shutdown-btn" id="shutdownBtn" onclick="shutdownServer()">✕ 关闭服务</button>
    <div class="container">
        <div class="header">
            <h1>▶ YouTube 视频下载器</h1>
            <p>粘贴 YouTube 链接，选择格式，一键下载</p>
        </div>

        <!-- 设置区域 -->
        <div class="settings-section">
            <h3 onclick="toggleSettings()">
                <span class="arrow" id="settingsArrow">▶</span>
                ⚙️ 下载设置
            </h3>
            <div class="settings-body" id="settingsBody">
                <label style="font-size:0.9rem; color:var(--text2); margin-bottom:8px; display:block;">保存位置</label>
                <div class="save-dir-row">
                    <input type="text" class="dir-input" id="saveDirInput" placeholder="输入保存目录路径...">
                    <button class="btn btn-secondary btn-sm" onclick="updateSaveDir()">确认</button>
                </div>
                <div class="dir-current" id="dirCurrent"></div>
                <div class="dir-hint">输入绝对路径，如 D:/Videos/YouTube 或 C:/Users/你的用户名/Downloads</div>

                <div class="cookies-row">
                    <div style="flex:1;">
                        <label class="cookies-label">🍪 手动导入 Cookies 文件（可选）</label>
                        <div class="cookies-file-row">
                            <input type="text" class="cookies-file-input" id="cookiesFilePath" placeholder="cookies.txt 路径..." readonly>
                            <label class="cookies-file-label">
                                📁 选择文件
                                <input type="file" id="cookiesFileInput" accept=".txt,.cookies" onchange="onCookiesFileSelected(event)">
                            </label>
                        </div>
                        <div class="cookies-hint">使用浏览器插件 "Get cookies.txt LOCALLY" 导出，格式：Netscape cookies.txt</div>
                        <div class="cookies-warning" id="cookiesWarning" style="display:none;"></div>
                    </div>
                </div>

                <div class="setting-row">
                    <span class="setting-label">📂 下载完成后自动打开文件夹</span>
                    <div class="switch-toggle active" id="autoOpenToggle" onclick="toggleAutoOpen()"></div>
                </div>
            </div>
        </div>

        <!-- URL 输入 -->
        <div class="input-section">
            <input type="text" class="url-input" id="urlInput" 
                   placeholder="粘贴 YouTube 视频链接..." 
                   value="">
            <button class="btn btn-primary" id="parseBtn" onclick="parseUrl()">解析</button>
        </div>

        <!-- 错误信息 -->
        <div class="error-msg" id="errorMsg"></div>

        <!-- 视频信息 -->
        <div class="video-info" id="videoInfo">
            <div class="video-meta">
                <img class="video-thumb" id="videoThumb" src="" alt="">
                <div class="video-details">
                    <div class="video-title" id="videoTitle"></div>
                    <div class="video-stats" id="videoStats"></div>
                </div>
            </div>
            <div class="format-section">
                <h3>选择下载格式</h3>
                <div class="format-grid" id="formatGrid"></div>
                <div class="download-actions">
                    <button class="btn btn-primary" id="downloadBtn" onclick="startDownload()">开始下载</button>
                </div>
            </div>
        </div>

        <!-- 下载进度 -->
        <div class="progress-section" id="progressSection">
            <div class="progress-header">
                <span class="progress-status" id="progressStatus">准备中...</span>
                <span class="progress-percent" id="progressPercent">0%</span>
            </div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" id="progressBar"></div>
            </div>
            <div class="progress-details">
                <span id="progressSpeed"></span>
                <span id="progressEta"></span>
            </div>
        </div>

        <!-- 下载完成 -->
        <div class="success-section" id="successSection">
            <div class="success-icon">✅</div>
            <div class="success-text">下载完成！</div>
            <div class="success-filename" id="successFilename"></div>
            <a id="downloadLink" href="#" class="btn btn-download">保存文件</a>
        </div>

        <!-- 历史记录 -->
        <div class="history-section" id="historySection" style="display:none;">
            <h2>下载历史</h2>
            <div id="historyList"></div>
        </div>

    </div>

    <script>
        let currentUrl = '';
        let selectedFormat = 'best';
        let currentTaskId = null;
        let progressInterval = null;
        let currentSaveDir = '';

        // ======== 设置相关 ========
        function toggleSettings() {
            const body = document.getElementById('settingsBody');
            const arrow = document.getElementById('settingsArrow');
            body.classList.toggle('show');
            arrow.classList.toggle('open');
        }

        async function loadSaveDir() {
            try {
                const res = await fetch('/api/save-dir');
                const data = await res.json();
                if (data.success) {
                    currentSaveDir = data.dir;
                    document.getElementById('saveDirInput').value = data.dir;
                    document.getElementById('dirCurrent').textContent = '当前目录: ' + data.dir;
                }
            } catch (e) {}
        }

        async function updateSaveDir() {
            const newDir = document.getElementById('saveDirInput').value.trim();
            if (!newDir) return;

            try {
                const res = await fetch('/api/save-dir', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ dir: newDir })
                });
                const data = await res.json();
                if (data.success) {
                    currentSaveDir = data.dir;
                    document.getElementById('dirCurrent').textContent = '✅ ' + data.message;
                    setTimeout(() => {
                        document.getElementById('dirCurrent').textContent = '当前目录: ' + data.dir;
                    }, 3000);
                } else {
                    alert(data.message);
                }
            } catch (e) {
                alert('设置失败，请重试');
            }
        }

        // ======== 自动打开文件夹 ========
        let autoOpenFolder = true;

        function toggleAutoOpen() {
            autoOpenFolder = !autoOpenFolder;
            const toggle = document.getElementById('autoOpenToggle');
            toggle.classList.toggle('active', autoOpenFolder);
            fetch('/api/auto-open', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ auto_open: autoOpenFolder })
            }).catch(() => {});
        }

        async function loadAutoOpenSetting() {
            try {
                const res = await fetch('/api/auto-open');
                const data = await res.json();
                if (data.success) {
                    autoOpenFolder = data.auto_open;
                    document.getElementById('autoOpenToggle').classList.toggle('active', autoOpenFolder);
                }
            } catch (e) {}
        }

        // ======== Cookies 相关 ========
        let cookiesFilePath = '';

        function onCookiesFileSelected(event) {
            const file = event.target.files[0];
            if (!file) return;
            document.getElementById('cookiesFilePath').value = file.name;

            const formData = new FormData();
            formData.append('cookies_file', file);

            fetch('/api/cookies', {
                method: 'POST',
                body: formData
            }).then(r => r.json()).then(data => {
                if (data.success) {
                    showCookiesWarning('✅ ' + data.message, false);
                } else {
                    showCookiesWarning('❌ ' + data.message, true);
                }
            }).catch(() => {
                showCookiesWarning('❌ 上传失败，请重试', true);
            });
        }

        function showCookiesWarning(msg, isError) {
            const el = document.getElementById('cookiesWarning');
            el.textContent = msg;
            el.style.display = 'block';
            el.style.background = isError ? 'rgba(255,68,68,0.1)' : 'rgba(0,200,83,0.1)';
            el.style.color = isError ? 'var(--accent)' : 'var(--green)';
        }

        async function loadCookiesSetting() {
            try {
                const res = await fetch('/api/cookies');
                const data = await res.json();
                if (data.success && data.cookies_file) {
                    document.getElementById('cookiesFilePath').value = data.cookies_file;
                    showCookiesWarning('已加载 cookies 文件: ' + data.cookies_file, false);
                }
            } catch (e) {}
        }

        // ======== 解析与下载 ========

        async function parseUrl() {
            const url = document.getElementById('urlInput').value.trim();
            if (!url) return;

            const btn = document.getElementById('parseBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="loading-spinner"></span>';

            hideAll();
            currentUrl = url;

            try {
                const res = await fetch('/api/info', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                const data = await res.json();

                if (!data.success) {
                    showError(data.message);
                    return;
                }

                showVideoInfo(data.video, data.formats);
            } catch (e) {
                showError('网络错误，请重试');
            } finally {
                btn.disabled = false;
                btn.textContent = '解析';
            }
        }

        function showVideoInfo(video, formats) {
            document.getElementById('videoThumb').src = video.thumbnail;
            document.getElementById('videoTitle').textContent = video.title;
            document.getElementById('videoStats').textContent = 
                `作者: ${video.uploader || '未知'}  |  时长: ${formatDuration(video.duration)}`;

            const grid = document.getElementById('formatGrid');
            grid.innerHTML = '';
            selectedFormat = 'best';

            formats.forEach((f, i) => {
                const div = document.createElement('div');
                div.className = 'format-option' + (i === 0 ? ' selected' : '');
                div.onclick = () => selectFormat(f.format_id, div);

                const sizeStr = f.filesize ? formatFileSize(f.filesize) : '';

                div.innerHTML = `
                    <div class="format-radio"></div>
                    <div class="format-label">
                        <div class="format-name">${f.label}${f.preset ? '<span class="preset-badge">推荐</span>' : ''}</div>
                        <div class="format-detail">编码: ${f.vcodec} / ${f.acodec}${sizeStr ? '  |  大小: ' + sizeStr : ''}</div>
                    </div>
                    <div class="format-size">${sizeStr || ''}</div>
                `;
                div.dataset.formatId = f.format_id;
                grid.appendChild(div);
            });

            document.getElementById('videoInfo').classList.add('show');
        }

        function selectFormat(formatId, element) {
            selectedFormat = formatId;
            document.querySelectorAll('.format-option').forEach(el => el.classList.remove('selected'));
            element.classList.add('selected');
        }

        async function startDownload() {
            if (!currentUrl) return;

            try {
                const res = await fetch('/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: currentUrl, format_id: selectedFormat, save_dir: currentSaveDir })
                });
                const data = await res.json();

                if (!data.success) {
                    showError(data.message);
                    return;
                }

                currentTaskId = data.task_id;
                document.getElementById('videoInfo').style.display = 'none';
                showProgress();
                pollProgress();
            } catch (e) {
                showError('启动下载失败');
            }
        }

        function showProgress() {
            document.getElementById('progressSection').classList.add('show');
        }

        function pollProgress() {
            if (progressInterval) clearInterval(progressInterval);
            progressInterval = setInterval(async () => {
                try {
                    const res = await fetch(`/api/progress/${currentTaskId}`);
                    const data = await res.json();
                    if (!data.success) return;

                    updateProgress(data);

                    if (data.status === 'completed' || data.status === 'error') {
                        clearInterval(progressInterval);
                        progressInterval = null;

                        if (data.status === 'completed') {
                            showSuccess(currentTaskId, data.display_name);
                        } else {
                            showError(data.message);
                        }
                        loadHistory();
                    }
                } catch (e) {}
            }, 500);
        }

        function updateProgress(data) {
            const statusMap = {
                'fetching': '获取信息中...',
                'downloading': '下载中...',
                'processing': '处理中...',
                'finished': '下载完成',
                'completed': '完成',
                'error': '出错',
            };

            document.getElementById('progressStatus').textContent = statusMap[data.status] || data.message || '处理中...';
            document.getElementById('progressPercent').textContent = Math.round(data.progress) + '%';
            document.getElementById('progressBar').style.width = data.progress + '%';
            document.getElementById('progressSpeed').textContent = data.speed ? formatFileSize(data.speed) + '/s' : '';
            document.getElementById('progressEta').textContent = data.eta ? '剩余 ' + formatEta(data.eta) : '';
        }

        function showSuccess(taskId, filename) {
            document.getElementById('progressSection').classList.remove('show');
            document.getElementById('successSection').classList.add('show');
            document.getElementById('successFilename').textContent = filename || '下载完成';
            document.getElementById('downloadLink').href = `/api/file/${taskId}`;
        }

        async function loadHistory() {
            try {
                const res = await fetch('/api/tasks');
                const data = await res.json();
                if (!data.success || data.tasks.length === 0) {
                    document.getElementById('historySection').style.display = 'none';
                    return;
                }

                const list = document.getElementById('historyList');
                list.innerHTML = '';
                data.tasks.forEach(t => {
                    const status = t.status === 'completed' ? 'completed' : 
                                   t.status === 'error' ? 'error' : 'downloading';
                    const statusText = t.status === 'completed' ? '完成' : 
                                       t.status === 'error' ? '失败' : t.status;
                    const time = t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : '';

                    let action = '';
                    if (t.status === 'completed') {
                        action = `<a href="/api/file/${t.id}" class="btn btn-download">保存</a>`;
                    }

                    list.innerHTML += `
                        <div class="history-item">
                            <div class="history-status ${status}"></div>
                            <div class="history-info">
                                <div class="history-name">${t.display_name || statusText}</div>
                                <div class="history-time">${time}  |  ${statusText}</div>
                            </div>
                            ${action}
                        </div>
                    `;
                });
                document.getElementById('historySection').style.display = 'block';
            } catch (e) {}
        }

        function showError(msg) {
            const el = document.getElementById('errorMsg');
            el.textContent = msg;
            el.classList.add('show');
        }

        function hideAll() {
            document.getElementById('errorMsg').classList.remove('show');
            document.getElementById('videoInfo').classList.remove('show');
            document.getElementById('progressSection').classList.remove('show');
            document.getElementById('successSection').classList.remove('show');
        }

        function formatFileSize(bytes) {
            if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
            if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
            if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return bytes + ' B';
        }

        function shutdownServer() {
            if (!confirm('确定要关闭服务吗？关闭后需要重新启动程序才能继续使用。')) return;
            const btn = document.getElementById('shutdownBtn');
            btn.textContent = '正在关闭...';
            btn.disabled = true;
            fetch('/api/shutdown', { method: 'POST' })
                .then(() => {
                    document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#666;font-family:sans-serif;font-size:1.2rem;">服务已关闭，可以关闭此页面。</div>';
                })
                .catch(() => {
                    document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#666;font-family:sans-serif;font-size:1.2rem;">服务已关闭，可以关闭此页面。</div>';
                });
        }

        function formatDuration(seconds) {
            if (!seconds) return '未知';
            const m = Math.floor(seconds / 60);
            const s = Math.floor(seconds % 60);
            const h = Math.floor(m / 60);
            if (h > 0) return `${h}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
            return `${m}:${String(s).padStart(2, '0')}`;
        }

        function formatEta(seconds) {
            if (seconds >= 3600) return Math.floor(seconds / 3600) + '小时' + Math.floor((seconds % 3600) / 60) + '分';
            if (seconds >= 60) return Math.floor(seconds / 60) + '分' + (seconds % 60) + '秒';
            return seconds + '秒';
        }

        // Enter 键触发解析
        document.getElementById('urlInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') parseUrl();
        });

        // 初始化：加载历史和设置
        loadHistory();
        loadSaveDir();
        loadCookiesSetting();
        loadAutoOpenSetting();
    </script>
</body>
</html>'''


def shutdown_server():
    """关闭 Flask 服务器"""
    import os
    os._exit(0)


if __name__ == '__main__':
    print("=" * 50)
    print("  YouTube 视频下载器已启动！")
    print(f"  应用目录: {BASE_DIR}")
    print(f"  下载目录: {DOWNLOAD_DIR}")
    print(f"  FFmpeg: {FFMPEG_PATH or '未找到（音频提取和合并将不可用）'}")
    print(f"  Node.js: {NODE_PATH or '未找到（视频解析可能失败）'}")
    print(f"  Cookies: {COOKIES_FILE or '未配置'}")
    print(f"  代理设置: {PROXY_URL or '未检测到代理（直连）'}")
    print("  访问地址: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)

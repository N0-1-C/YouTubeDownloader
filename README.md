# YouTube 视频下载器

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) + [Flask](https://flask.palletsprojects.com/) 的 Web 视频下载工具，提供浏览器图形界面，支持格式选择、实时进度、Cookies 导入等功能。

## 特性

- 🔗 粘贴链接即解析，支持标准 / Shorts / 嵌入式链接
- 📹 多格式选择：最佳画质、最佳音频、指定分辨率 / 编码
- 📊 实时下载进度：百分比、速度、剩余时间
- 🍪 Cookies 导入：支持下载会员 / 年龄限制 / 私有视频
- 📂 自定义保存目录，下载完成自动打开文件夹
- 🌐 自动检测系统代理，无需手动配置
- 📦 一键打包为独立 EXE，无需安装 Python

## 快速开始

### 环境要求

- Python 3.9+
- FFmpeg（音频提取 / 视频合并）
- Node.js（YouTube 解析必需）
- 代理 / VPN（访问 YouTube）

### 安装与运行

```bash
# 1. 克隆项目
git clone <repo-url>
cd YouTubeDownloader

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python app.py
```

访问 http://127.0.0.1:5000

### EXE 分发版

直接解压 `YouTubeDownloader.zip`，双击 `启动下载器.bat` 即可，无需安装任何依赖。

## 项目结构

```
YouTubeDownloader/
├── app.py              # 主程序（Flask 后端 + 前端 HTML/CSS/JS）
├── build.py            # PyInstaller 打包脚本
├── cookies_reader.py   # 浏览器 Cookies 读取模块（备用）
├── requirements.txt    # Python 依赖
├── YouTubeDownloader.spec  # PyInstaller 配置
├── 使用文档.md          # 用户使用说明
├── API文档.md           # API 接口文档
├── 项目工程文档.md       # 工程技术文档
├── README.md           # 本文件
└── dist/               # 打包输出
    └── YouTubeDownloader/
        ├── YouTubeDownloader.exe
        ├── 启动下载器.bat
        ├── 静默启动.bat
        ├── tools/
        │   ├── ffmpeg/bin/     # FFmpeg
        │   └── nodejs/         # Node.js
        └── 使用说明.txt
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python / Flask / Flask-CORS |
| 下载引擎 | yt-dlp |
| 视频处理 | FFmpeg |
| JS 运行时 | Node.js（YouTube n parameter challenge） |
| 前端 | 原生 HTML + CSS + JavaScript |
| 打包 | PyInstaller (--onedir) |

## API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/info` | POST | 解析视频链接 |
| `/api/download` | POST | 创建下载任务 |
| `/api/progress/<task_id>` | GET | 查询下载进度 |
| `/api/file/<task_id>` | GET | 下载已完成文件 |
| `/api/tasks` | GET | 列出所有任务 |
| `/api/save-dir` | GET/POST | 获取/设置保存目录 |
| `/api/cookies` | GET/POST | 获取/设置 Cookies |
| `/api/auto-open` | GET/POST | 自动打开文件夹开关 |
| `/api/shutdown` | POST | 关闭服务 |

详细文档见 [API文档.md](API文档.md)

## 许可证

MIT

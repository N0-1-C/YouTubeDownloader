# 长期记忆

## 项目
- **YouTube 视频下载器**: 基于 yt-dlp + Flask 的 Web 应用，端口 5000，下载目录为项目下 `downloads/`。文件: `app.py`
- **cookies_reader.py**: 浏览器 cookies 自动读取模块（支持 Chrome v10/v11/v20 解密）
- 打包脚本: `build.py`，使用 PyInstaller `--onedir` 模式打包
- 打包输出: `dist/YouTubeDownloader/`，包含 exe、ffmpeg、node、cookies.txt
- 打包后总大小约 322 MB（主要是 ffmpeg + node）
- 启动方式: `启动下载器.bat`（自动请求管理员权限）, `普通模式启动.bat`
- **Cookies 方案变更**: 从手动解密 SQLite → yt-dlp 内置 `cookiesfrombrowser` → 最终仅保留手动导入 cookies.txt 文件功能（2026-03-28）。移除了浏览器自动获取、toggle 开关、浏览器选择下拉框、`/api/cookies/check` 路由等。`/api/cookies` 仅支持 GET 查询和 POST 设置 cookies 文件路径。

## 偏好
- 用户语言: 中文
- 代理: `http://127.0.0.1:11649`（系统代理）
- 浏览器: Edge + Chrome

# YouTube 视频下载器 - API 文档

基础地址：`http://127.0.0.1:5000`

所有 API 返回 JSON 格式，统一结构：

```json
{
  "success": true/false,
  "message": "描述信息",
  ...  // 业务数据
}
```

---

## 1. 解析视频信息

**POST** `/api/info`

解析 YouTube 视频链接，返回视频信息和可用格式列表。

### 请求

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}
```

### 响应

```json
{
  "success": true,
  "video": {
    "id": "dQw4w9WgXcQ",
    "title": "视频标题",
    "thumbnail": "https://i.ytimg.com/vi/xxx/maxresdefault.jpg",
    "duration": 212,
    "description": "视频描述前200字...",
    "uploader": "上传者名称"
  },
  "formats": [
    {
      "format_id": "best",
      "label": "最佳画质 (视频+音频)",
      "ext": "mp4",
      "resolution": "自动",
      "filesize": null,
      "vcodec": "-",
      "acodec": "-",
      "preset": true
    },
    {
      "format_id": "bestaudio",
      "label": "最佳音频 (MP3)",
      "ext": "mp3",
      "resolution": "仅音频",
      "filesize": null,
      "vcodec": "无",
      "acodec": "mp3",
      "preset": true
    },
    {
      "format_id": "137",
      "label": "1920x1080 mp4 H.264",
      "ext": "mp4",
      "resolution": "1920x1080",
      "filesize": 50000000,
      "vcodec": "H.264",
      "acodec": "AAC",
      "preset": false
    }
  ]
}
```

### 错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 链接为空或格式不正确 |
| 500 | 解析失败（网络问题、视频不可用等） |

---

## 2. 开始下载

**POST** `/api/download`

创建下载任务，返回任务 ID。下载在后台线程异步执行。

### 请求

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "format_id": "best",
  "save_dir": "C:\\Users\\pc\\Desktop"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| url | string | ✅ | YouTube 视频链接 |
| format_id | string | ❌ | 格式 ID，默认 `best`。`bestaudio` 为纯音频 |
| save_dir | string | ❌ | 保存目录，默认桌面 |

### 响应

```json
{
  "success": true,
  "task_id": "a1b2c3d4"
}
```

### 错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 链接为空、格式错误、目录不存在 |

---

## 3. 查询下载进度

**GET** `/api/progress/<task_id>`

### 响应

```json
{
  "success": true,
  "task_id": "a1b2c3d4",
  "status": "downloading",
  "progress": 65.3,
  "message": "正在下载...",
  "speed": 5242880,
  "eta": 32,
  "downloaded": 33554432,
  "total": 52428800,
  "display_name": null
}
```

### 任务状态

| status | 说明 |
|--------|------|
| pending | 已创建，等待开始 |
| fetching | 正在获取视频信息 |
| downloading | 正在下载 |
| processing | 正在处理（合并/转码） |
| finished | 下载完成，处理中 |
| completed | 全部完成 |
| error | 出错 |

### 错误码

| 状态码 | 说明 |
|--------|------|
| 404 | 任务不存在 |

---

## 4. 下载文件

**GET** `/api/file/<task_id>`

任务完成后，通过此接口下载文件到本地。

### 响应

直接返回文件二进制流（`Content-Disposition: attachment`）。

### 错误码

| 状态码 | 说明 |
|--------|------|
| 404 | 任务不存在或文件不存在 |

---

## 5. 列出所有任务

**GET** `/api/tasks`

### 响应

```json
{
  "success": true,
  "tasks": [
    {
      "id": "a1b2c3d4",
      "status": "completed",
      "progress": 100,
      "message": "下载完成！",
      "display_name": "视频标题.mp4",
      "created_at": "2026-03-28T18:00:00"
    }
  ]
}
```

任务按创建时间倒序排列。

---

## 6. 获取/设置保存目录

**GET** `/api/save-dir`

### 响应

```json
{
  "success": true,
  "dir": "C:\\Users\\pc\\Desktop"
}
```

**POST** `/api/save-dir`

### 请求

```json
{
  "dir": "D:\\Downloads"
}
```

### 响应

```json
{
  "success": true,
  "dir": "D:\\Downloads",
  "message": "下载目录已更新为: D:\\Downloads"
}
```

### 错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 路径为空或目录不存在 |

---

## 7. 获取/设置 Cookies

**GET** `/api/cookies`

### 响应

```json
{
  "success": true,
  "cookies_file": "C:\\path\\to\\cookies.txt"
}
```

**POST** `/api/cookies`

支持两种提交方式：

#### 方式一：文件上传（推荐）

`Content-Type: multipart/form-data`

| 字段 | 类型 | 说明 |
|------|------|------|
| cookies_file | File | cookies.txt 文件 |

文件会被保存到应用目录下的 `cookies.txt`。

```bash
curl -X POST http://127.0.0.1:5000/api/cookies \
  -F "cookies_file=@/path/to/cookies.txt"
```

#### 方式二：JSON 路径

```json
{
  "cookies_file": "C:\\path\\to\\cookies.txt"
}
```

传空字符串可清除 cookies：

```json
{
  "cookies_file": ""
}
```

### 响应

```json
{
  "success": true,
  "cookies_file": "C:\\app\\cookies.txt",
  "message": "已导入 cookies 文件 (cookies.txt)"
}
```

### 错误码

| 状态码 | 说明 |
|--------|------|
| 400 | 未接收到文件或文件路径不存在 |

---

## 8. 获取/设置自动打开文件夹

**GET** `/api/auto-open`

### 响应

```json
{
  "success": true,
  "auto_open": true
}
```

**POST** `/api/auto-open`

### 请求

```json
{
  "auto_open": false
}
```

### 响应

```json
{
  "success": true,
  "auto_open": false,
  "message": "已关闭自动打开文件夹"
}
```

---

## 9. 关闭服务

**POST** `/api/shutdown`

关闭服务器进程，释放端口。

### 响应

```json
{
  "success": true,
  "message": "服务正在关闭..."
}
```

> 调用后服务器将在短时间内终止，后续请求将无法响应。

---

## 状态码汇总

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在（任务/文件） |
| 500 | 服务器内部错误 |

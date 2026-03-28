"""
YouTube 视频下载器 - API 自动化测试脚本

使用方法:
    python test_api.py

依赖:
    pip install requests

注意:
    - 运行前需先启动服务: python app.py
    - 测试会创建实际下载任务（仅测试 API 流程，不测试完整下载）
"""

import requests
import json
import time
import sys
import io

# 修复 Windows 终端编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_URL = "http://127.0.0.1:5000"


class Colors:
    """终端颜色"""
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def log_test(name, passed, detail=""):
    """打印测试结果"""
    status = f"{Colors.GREEN}✓ PASS{Colors.END}" if passed else f"{Colors.RED}✗ FAIL{Colors.END}"
    print(f"  {status}  {name}")
    if detail:
        indent = "         "
        print(f"{indent}{detail}")


def log_section(name):
    """打印测试分组标题"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'─' * 50}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {name}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'─' * 50}{Colors.END}")


# ============================================================
# 测试用例
# ============================================================

passed = 0
failed = 0


def test_health_check():
    """基础连通性测试"""
    log_section("基础连通性测试")
    global passed, failed

    try:
        r = requests.get(BASE_URL, timeout=5)
        log_test("服务是否启动 (GET /)", r.status_code == 200, f"HTTP {r.status_code}")
        passed += 1
    except requests.ConnectionError:
        log_test("服务是否启动 (GET /)", False, "无法连接到服务，请先运行 python app.py")
        failed += 1
        sys.exit(1)
    except Exception as e:
        log_test("服务是否启动 (GET /)", False, str(e))
        failed += 1
        sys.exit(1)


def test_api_info():
    """视频信息解析测试"""
    log_section("POST /api/info — 视频信息解析")
    global passed, failed

    # 测试 1: 空链接
    r = requests.post(f"{BASE_URL}/api/info", json={"url": ""})
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("空链接应返回 400", ok, f"HTTP {r.status_code}, body: {r.json()}")
    passed if ok else (failed := failed + 1) if not ok else None
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 2: 无效链接
    r = requests.post(f"{BASE_URL}/api/info", json={"url": "https://example.com/not-youtube"})
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("非 YouTube 链接应返回 400", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 3: 有效链接（需要网络能访问 YouTube）
    # 跳过自动测试（依赖网络），仅记录
    log_test("有效 YouTube 链接解析", None, "跳过 — 需要网络连接，请手动测试")


def test_api_download():
    """下载任务测试"""
    log_section("POST /api/download — 下载任务")
    global passed, failed

    # 测试 1: 空链接
    r = requests.post(f"{BASE_URL}/api/download", json={"url": ""})
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("空链接应返回 400", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 2: 无效链接
    r = requests.post(f"{BASE_URL}/api/download", json={"url": "https://example.com"})
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("非 YouTube 链接应返回 400", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 3: 无效目录
    r = requests.post(f"{BASE_URL}/api/download", json={
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "save_dir": "C:\\nonexistent_dir_12345"
    })
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("无效保存目录应返回 400", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1


def test_api_progress():
    """下载进度测试"""
    log_section("GET /api/progress/<task_id> — 进度查询")
    global passed, failed

    # 测试 1: 不存在的任务
    r = requests.get(f"{BASE_URL}/api/progress/nonexistent")
    ok = r.status_code == 404 and not r.json().get("success")
    log_test("不存在的任务应返回 404", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1


def test_api_file():
    """文件下载测试"""
    log_section("GET /api/file/<task_id> — 文件下载")
    global passed, failed

    # 测试 1: 不存在的任务
    r = requests.get(f"{BASE_URL}/api/file/nonexistent")
    ok = r.status_code == 404 and not r.json().get("success")
    log_test("不存在的任务应返回 404", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1


def test_api_tasks():
    """任务列表测试"""
    log_section("GET /api/tasks — 任务列表")
    global passed, failed

    r = requests.get(f"{BASE_URL}/api/tasks")
    ok = r.status_code == 200 and r.json().get("success")
    data = r.json()
    log_test("获取任务列表", ok, f"共 {len(data.get('tasks', []))} 个任务")
    if ok:
        passed += 1
    else:
        failed += 1

    # 验证字段完整性
    if ok and data.get("tasks"):
        task = data["tasks"][0]
        required_fields = {"id", "status", "progress", "message", "created_at"}
        has_fields = required_fields.issubset(task.keys())
        log_test("任务字段完整性", has_fields,
                 f"字段: {list(task.keys())}")
        if has_fields:
            passed += 1
        else:
            failed += 1


def test_api_save_dir():
    """保存目录设置测试"""
    log_section("GET/POST /api/save-dir — 保存目录")
    global passed, failed

    # 测试 GET
    r = requests.get(f"{BASE_URL}/api/save-dir")
    ok = r.status_code == 200 and r.json().get("success") and r.json().get("dir")
    original_dir = r.json().get("dir")
    log_test("GET 保存目录", ok, f"当前目录: {original_dir}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 POST 设置新目录
    r = requests.post(f"{BASE_URL}/api/save-dir", json={"dir": "C:\\Windows\\Temp"})
    ok = r.status_code == 200 and r.json().get("success")
    log_test("POST 设置有效目录", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 POST 无效目录
    r = requests.post(f"{BASE_URL}/api/save-dir", json={"dir": "C:\\nonexistent_12345"})
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("POST 设置无效目录应返回 400", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 POST 空路径
    r = requests.post(f"{BASE_URL}/api/save-dir", json={"dir": ""})
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("POST 空路径应返回 400", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 恢复原始目录
    if original_dir:
        requests.post(f"{BASE_URL}/api/save-dir", json={"dir": original_dir})


def test_api_cookies():
    """Cookies 设置测试"""
    log_section("GET/POST /api/cookies — Cookies 设置")
    global passed, failed

    # 测试 GET
    r = requests.get(f"{BASE_URL}/api/cookies")
    ok = r.status_code == 200 and r.json().get("success")
    log_test("GET cookies 状态", ok, f"当前: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 POST 清除 cookies
    r = requests.post(f"{BASE_URL}/api/cookies", json={"cookies_file": ""})
    ok = r.status_code == 200 and r.json().get("success")
    log_test("POST 清除 cookies", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 POST 无效路径
    r = requests.post(f"{BASE_URL}/api/cookies",
                       json={"cookies_file": "C:\\nonexistent\\cookies.txt"})
    ok = r.status_code == 400 and not r.json().get("success")
    log_test("POST 无效路径应返回 400", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 FormData 上传（空文件测试）
    import io
    files = {"cookies_file": ("test.txt", io.BytesIO(b"# Netscape HTTP Cookie File\ntest\tTRUE\t/\tFALSE\t0\ttest\tvalue\n"), "text/plain")}
    r = requests.post(f"{BASE_URL}/api/cookies", files=files)
    ok = r.status_code == 200 and r.json().get("success")
    log_test("POST FormData 文件上传", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 清除测试 cookies
    requests.post(f"{BASE_URL}/api/cookies", json={"cookies_file": ""})


def test_api_auto_open():
    """自动打开文件夹设置测试"""
    log_section("GET/POST /api/auto-open — 自动打开文件夹")
    global passed, failed

    # 测试 GET
    r = requests.get(f"{BASE_URL}/api/auto-open")
    ok = r.status_code == 200 and r.json().get("success") and isinstance(r.json().get("auto_open"), bool)
    original = r.json().get("auto_open")
    log_test("GET 自动打开设置", ok, f"当前: {original}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 POST 关闭
    r = requests.post(f"{BASE_URL}/api/auto-open", json={"auto_open": False})
    ok = r.status_code == 200 and r.json().get("auto_open") == False
    log_test("POST 关闭自动打开", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 POST 开启
    r = requests.post(f"{BASE_URL}/api/auto-open", json={"auto_open": True})
    ok = r.status_code == 200 and r.json().get("auto_open") == True
    log_test("POST 开启自动打开", ok, f"响应: {r.json()}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 恢复原始设置
    requests.post(f"{BASE_URL}/api/auto-open", json={"auto_open": original})


def test_api_shutdown():
    """关闭服务接口测试（不实际关闭）"""
    log_section("POST /api/shutdown — 关闭服务")
    global passed, failed

    # 仅验证接口存在且返回正确格式，不实际关闭
    log_test("POST /api/shutdown", None,
             "跳过 — 实际调用会关闭服务。手动测试: curl -X POST http://127.0.0.1:5000/api/shutdown")


def test_api_pause_resume_cancel():
    """暂停/恢复/取消测试"""
    log_section("POST /api/task/<id>/pause|resume|cancel — 暂停/恢复/取消")
    global passed, failed

    # 测试 1: 暂停不存在的任务
    r = requests.post(f"{BASE_URL}/api/task/nonexistent/pause")
    ok = r.status_code == 404 and not r.json().get("success")
    log_test("暂停不存在的任务应返回 404", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 2: 恢复不存在的任务
    r = requests.post(f"{BASE_URL}/api/task/nonexistent/resume")
    ok = r.status_code == 404 and not r.json().get("success")
    log_test("恢复不存在的任务应返回 404", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 3: 取消不存在的任务
    r = requests.post(f"{BASE_URL}/api/task/nonexistent/cancel")
    ok = r.status_code == 404 and not r.json().get("success")
    log_test("取消不存在的任务应返回 404", ok, f"HTTP {r.status_code}")
    if ok:
        passed += 1
    else:
        failed += 1

    # 测试 4: 对不存在任务进度查询应返回 paused/cancelled 状态
    # （通过 /api/progress 验证 status 字段包含新状态值）
    log_test("暂停/恢复/取消完整流程", None,
             "跳过 — 需要实际下载任务才能测试。手动测试流程: 下载 → 暂停 → 恢复 → 取消")


# ============================================================
# 主测试流程
# ============================================================

def main():
    print(f"\n{Colors.BOLD}YouTube 视频下载器 API 测试{Colors.END}")
    print(f"目标: {BASE_URL}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    test_health_check()
    test_api_info()
    test_api_download()
    test_api_progress()
    test_api_file()
    test_api_tasks()
    test_api_save_dir()
    test_api_cookies()
    test_api_auto_open()
    test_api_shutdown()
    test_api_pause_resume_cancel()

    # 汇总
    print(f"\n{'=' * 50}")
    total = passed + failed
    skipped = sum(1 for t in [None] if False)  # 简化：跳过的不计入

    print(f"  总计: {total} 个测试")
    print(f"  {Colors.GREEN}通过: {passed}{Colors.END}")
    print(f"  {Colors.RED}失败: {failed}{Colors.END}")
    print(f"  跳过: 部分（需网络连接或会中断服务）")
    print(f"{'=' * 50}\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

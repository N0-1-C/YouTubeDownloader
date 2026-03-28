"""
浏览器 Cookies 自动读取模块
支持: Chrome, Edge, Brave (基于 Chromium 的浏览器)
加密方式: v10 (AES-128-CBC), v11 (AES-256-GCM), v20 (app-bound AES-256-GCM)
输出: Netscape cookies.txt 格式 (yt-dlp 兼容)
"""
import os
import sys
import json
import base64
import sqlite3
import shutil
import tempfile
import subprocess
import time
from datetime import datetime

# ============ 浏览器路径配置 ============
LOCAL_APP_DATA = os.environ.get('LOCALAPPDATA', '')
APP_DATA = os.environ.get('APPDATA', '')
PROGRAM_FILES = os.environ.get('ProgramFiles', '')
PROGRAM_FILES_X86 = os.environ.get('ProgramFiles(x86)', '')

BROWSERS = {
    'chrome': {
        'name': 'Google Chrome',
        'local_state': os.path.join(LOCAL_APP_DATA, 'Google', 'Chrome', 'User Data', 'Local State'),
        'cookies_pattern': os.path.join(LOCAL_APP_DATA, 'Google', 'Chrome', 'User Data', '*', 'Network', 'Cookies'),
        'user_data': os.path.join(LOCAL_APP_DATA, 'Google', 'Chrome', 'User Data'),
        'process': 'chrome.exe',
    },
    'edge': {
        'name': 'Microsoft Edge',
        'local_state': os.path.join(LOCAL_APP_DATA, 'Microsoft', 'Edge', 'User Data', 'Local State'),
        'cookies_pattern': os.path.join(LOCAL_APP_DATA, 'Microsoft', 'Edge', 'User Data', '*', 'Network', 'Cookies'),
        'user_data': os.path.join(LOCAL_APP_DATA, 'Microsoft', 'Edge', 'User Data'),
        'process': 'msedge.exe',
    },
    'brave': {
        'name': 'Brave',
        'local_state': os.path.join(LOCAL_APP_DATA, 'BraveSoftware', 'Brave-Browser', 'User Data', 'Local State'),
        'cookies_pattern': os.path.join(LOCAL_APP_DATA, 'BraveSoftware', 'Brave-Browser', 'User Data', '*', 'Network', 'Cookies'),
        'user_data': os.path.join(LOCAL_APP_DATA, 'BraveSoftware', 'Brave-Browser', 'User Data'),
        'process': 'brave.exe',
    },
}


# ============ DPAPI 解密 ============
def _dpapi_decrypt(encrypted, use_system=False):
    """Windows DPAPI 解密（使用 ctypes，不依赖 pywin32）"""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ('cbData', ctypes.wintypes.DWORD),
            ('pbData', ctypes.POINTER(ctypes.c_char)),
        ]

    p = ctypes.create_string_buffer(encrypted, len(encrypted))
    blob_in = DATA_BLOB(len(encrypted), p)
    blob_out = DATA_BLOB()

    flags = 0
    if use_system:
        # CRYPTPROTECT_SYSTEM = 0x00000004
        flags = 0x00000004

    if ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)
    ):
        result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return result
    return None


# ============ AES 解密 ============
def _aes_gcm_decrypt(key, nonce, ciphertext, tag):
    """AES-GCM 解密"""
    from Cryptodome.Cipher import AES
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def _aes_cbc_decrypt(key, iv, ciphertext):
    """AES-CBC 解密 (PKCS7 padding)"""
    from Cryptodome.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    decrypted = cipher.decrypt(ciphertext)
    # 去掉 PKCS7 padding
    pad_len = decrypted[-1]
    if 1 <= pad_len <= 16:
        decrypted = decrypted[:-pad_len]
    return decrypted


# ============ 密钥提取 ============
def _extract_master_key(local_state_path):
    """从 Local State 提取 DPAPI 加密的 master key"""
    if not os.path.exists(local_state_path):
        return None
    try:
        with open(local_state_path, 'r', encoding='utf-8') as f:
            local_state = json.load(f)
        enc_key_b64 = local_state.get('os_crypt', {}).get('encrypted_key', '')
        if not enc_key_b64:
            return None
        enc_key_raw = base64.b64decode(enc_key_b64)
        # 去掉 'DPAPI' 前缀（5 bytes）
        if enc_key_raw[:5] == b'DPAPI':
            enc_key_raw = enc_key_raw[5:]
        return _dpapi_decrypt(enc_key_raw)
    except Exception:
        return None


def _extract_app_bound_key(local_state_path):
    """提取 Chrome v20 app-bound 加密密钥
    流程: base64 decode -> 去掉 'APPB' 前缀 -> SYSTEM DPAPI -> 用户 DPAPI -> AES-GCM -> 密钥
    """
    if not os.path.exists(local_state_path):
        return None, "Local State 文件不存在"
    try:
        with open(local_state_path, 'r', encoding='utf-8') as f:
            local_state = json.load(f)

        app_bound_b64 = local_state.get('os_crypt', {}).get('app_bound_encrypted_key', '')
        if not app_bound_b64:
            return None, "未找到 app_bound_encrypted_key（浏览器可能未启用 app-bound 加密）"

        app_bound_raw = base64.b64decode(app_bound_b64)

        # 去掉 'APPB' 前缀
        prefix = app_bound_raw[:4]
        if prefix not in (b'APPB', b'DPAPI'):
            return None, f"未知的加密前缀: {prefix}"
        app_bound_raw = app_bound_raw[4:]

        # 第一步：SYSTEM DPAPI 解密（需要管理员权限）
        try:
            decrypted_system = _dpapi_decrypt(app_bound_raw, use_system=True)
            if not decrypted_system:
                return None, "SYSTEM DPAPI 解密失败（需要管理员权限）"
        except Exception as e:
            return None, f"SYSTEM DPAPI 解密失败: {e}"

        # 第二步：用户 DPAPI 解密
        try:
            decrypted_data = _dpapi_decrypt(decrypted_system)
            if not decrypted_data:
                return None, "用户 DPAPI 解密失败"
        except Exception as e:
            return None, f"用户 DPAPI 解密失败: {e}"

        # 第三步：从解密数据中提取 AES 密钥
        # 解密后的数据格式: [Chrome路径 + 0x01 + 12字节IV + 32字节密文 + 16字节TAG]
        # 使用硬编码在 elevation_service.exe 中的密钥进行 AES-GCM 解密
        # 注意: Chrome 133+ 使用不同的密钥
        CHROME_V20_KEY = bytes.fromhex(
            "B31C6E241AC846728DA9C1FAC4936651CFFB944D143AB816276BCC6DA0284787"
        )
        # Chrome 133+ 的备选密钥
        CHROME_V20_KEY_ALT = bytes.fromhex(
            "e98f37d7f4e1fa433d19304dc2258042090e2d1d7eea7670d41f738d08729660"
        )

        # 查找 0x01 标志位
        flag_pos = decrypted_data.find(b'\x01')
        if flag_pos == -1:
            return None, "未找到密钥数据标志位"

        iv = decrypted_data[flag_pos + 1 : flag_pos + 13]  # 12 bytes
        ciphertext = decrypted_data[flag_pos + 13 : flag_pos + 45]  # 32 bytes
        tag = decrypted_data[flag_pos + 45 : flag_pos + 61]  # 16 bytes

        # 尝试主密钥
        try:
            aes_key = _aes_gcm_decrypt(CHROME_V20_KEY, iv, ciphertext, tag)
            if aes_key:
                return aes_key, None
        except Exception:
            pass

        # 尝试备选密钥 (Chrome 133+)
        try:
            aes_key = _aes_gcm_decrypt(CHROME_V20_KEY_ALT, iv, ciphertext, tag)
            if aes_key:
                return aes_key, None
        except Exception:
            pass

        return None, "AES-GCM 密钥解密失败（Chrome 版本可能不兼容）"

    except Exception as e:
        return None, f"提取 app-bound 密钥时出错: {e}"


# ============ Cookie 解密 ============
def _decrypt_cookie_value(encrypted_value, master_key, app_bound_key):
    """解密单个 cookie 值，自动识别加密版本"""
    if not encrypted_value:
        return None

    # 未加密的 cookie
    if not encrypted_value[:3] in (b'v10', b'v11', b'v20'):
        try:
            return encrypted_value.decode('utf-8')
        except:
            return None

    try:
        version = encrypted_value[:3]

        if version == b'v10':
            # AES-128-CBC + PBKDF2
            if not master_key:
                return None
            from Cryptodome.Cipher import AES
            from Cryptodome.Protocol.KDF import PBKDF2
            import hashlib
            nonce = encrypted_value[3:15]  # 12 bytes (salt)
            ciphertext = encrypted_value[15:]
            key = PBKDF2(master_key, nonce, dkLen=16, count=1, hmac_hash_module=hashlib.sha1)
            decrypted = _aes_cbc_decrypt(key, b'\x00' * 16, ciphertext)
            return decrypted.decode('utf-8', errors='replace')

        elif version == b'v11':
            # AES-256-GCM (旧版 DPAPI master key)
            if not master_key:
                return None
            nonce = encrypted_value[3:15]  # 12 bytes
            ciphertext = encrypted_value[15:-16]
            tag = encrypted_value[-16:]  # 16 bytes
            decrypted = _aes_gcm_decrypt(master_key, nonce, ciphertext, tag)
            return decrypted.decode('utf-8', errors='replace')

        elif version == b'v20':
            # App-bound AES-256-GCM
            if not app_bound_key:
                return None
            nonce = encrypted_value[3:15]  # 12 bytes
            ciphertext = encrypted_value[15:-16]
            tag = encrypted_value[-16:]  # 16 bytes
            decrypted = _aes_gcm_decrypt(app_bound_key, nonce, ciphertext, tag)
            # v20 解密后前 32 字节是填充/校验数据
            return decrypted[32:].decode('utf-8', errors='replace')

    except Exception:
        return None

    return None


# ============ 浏览器进程检测 ============
def _is_browser_running(process_name):
    """检查浏览器进程是否在运行"""
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {process_name}', '/NH'],
            capture_output=True, text=True, timeout=5
        )
        return process_name.lower() in result.stdout.lower()
    except Exception:
        return False


def _close_browser(process_name):
    """关闭浏览器进程"""
    try:
        result = subprocess.run(
            ['taskkill', '/F', '/IM', process_name],
            capture_output=True, text=True, timeout=10
        )
        # 等待进程完全退出
        time.sleep(1)
        return not _is_browser_running(process_name)
    except Exception:
        return False


# ============ Cookies 数据库复制 ============
def _copy_cookies_db(db_path):
    """安全复制 cookies 数据库（处理文件锁定）"""
    tmp = os.path.join(tempfile.gettempdir(), '_yt_dl_cookies.db')
    if os.path.exists(tmp):
        try:
            os.unlink(tmp)
        except:
            pass
    # 尝试普通复制
    try:
        shutil.copy2(db_path, tmp)
        if os.path.getsize(tmp) > 0:
            return tmp, None
    except (PermissionError, OSError):
        pass
    # robocopy 兜底
    try:
        result = subprocess.run(
            ['robocopy', os.path.dirname(db_path), tempfile.gettempdir(),
             os.path.basename(db_path), '/R:1', '/W:1', '/NFL', '/NDL',
             '/NJH', '/NJS', '/NC', '/NS'],
            capture_output=True, text=True, timeout=10
        )
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            return tmp, None
    except:
        pass
    return None, "无法复制 cookies 数据库（浏览器可能正在运行，请先关闭浏览器）"


def _find_cookies_dbs(browser_key):
    """查找浏览器所有 Profile 的 cookies 数据库"""
    browser = BROWSERS[browser_key]
    user_data_dir = browser['user_data']

    # 直接检查 Default profile
    default_path = os.path.join(user_data_dir, 'Default', 'Network', 'Cookies')
    if os.path.exists(default_path):
        return [default_path]

    # 扫描所有 Profile 目录
    db_files = []
    if os.path.isdir(user_data_dir):
        for entry in os.listdir(user_data_dir):
            profile_dir = os.path.join(user_data_dir, entry)
            if not os.path.isdir(profile_dir):
                continue
            # 只检查有效的 Profile 目录
            if entry in ('Default', 'Guest Profile') or entry.startswith('Profile'):
                db = os.path.join(profile_dir, 'Network', 'Cookies')
                if os.path.exists(db):
                    db_files.append(db)

    return db_files if db_files else [default_path]


# ============ 主函数 ============
def _is_admin():
    """检查是否有管理员权限"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


def extract_cookies(browser_key='chrome', domain_filter=None, close_browser=False):
    """
    从浏览器提取 cookies 并生成 Netscape cookies.txt 格式

    Args:
        browser_key: 浏览器标识 ('chrome', 'edge', 'brave')
        domain_filter: 域名过滤（如 '.youtube.com'），None 表示提取全部
        close_browser: 是否自动关闭浏览器（如果正在运行）

    Returns:
        dict: {
            'success': bool,
            'cookies_txt': str,  # Netscape cookies.txt 内容
            'cookie_count': int,
            'browser': str,
            'message': str,
            'v20_supported': bool,
        }
    """
    if browser_key not in BROWSERS:
        return {'success': False, 'message': f'不支持的浏览器: {browser_key}'}

    browser = BROWSERS[browser_key]
    local_state_path = browser['local_state']
    process_name = browser['process']

    # 检查浏览器是否安装
    if not os.path.exists(local_state_path):
        return {'success': False, 'message': f'未检测到 {browser["name"]}，请确认已安装'}

    # 检查浏览器是否运行
    running = _is_browser_running(process_name)
    if running and close_browser:
        if not _close_browser(process_name):
            return {'success': False, 'message': f'无法关闭 {browser["name"]}，请手动关闭后重试'}
        # 等待文件锁释放
        time.sleep(2)
    elif running:
        return {
            'success': False,
            'message': f'{browser["name"]} 正在运行，无法读取 cookies。请先关闭浏览器后重试。',
            'need_close': True,
        }

    # 提取 master key (v10/v11)
    master_key = _extract_master_key(local_state_path)
    if not master_key:
        return {'success': False, 'message': '无法提取 master key（DPAPI 解密失败）'}

    # 提取 app-bound key (v20) — 可选，失败不影响 v10/v11
    app_bound_key, app_bound_error = _extract_app_bound_key(local_state_path)
    v20_available = app_bound_key is not None

    # 查找 cookies 数据库
    cookies_dbs = _find_cookies_dbs(browser_key)
    if not cookies_dbs or not os.path.exists(cookies_dbs[0]):
        return {'success': False, 'message': '未找到 cookies 数据库'}

    # 读取并解密 cookies
    all_cookies = []
    v10_count = 0
    v20_count = 0
    v20_fail_count = 0
    last_error = None

    for db_path in cookies_dbs:
        if not os.path.exists(db_path):
            continue

        tmp_db, copy_error = _copy_cookies_db(db_path)
        if not tmp_db:
            last_error = copy_error
            continue

        try:
            conn = sqlite3.connect(tmp_db)
            query = """
                SELECT host_key, path, is_secure, is_httponly,
                       name, encrypted_value, expires_utc, samesite
                FROM cookies
            """
            if domain_filter:
                query += f" WHERE host_key LIKE '%{domain_filter}%'"
            query += " ORDER BY host_key, path, name"

            cursor = conn.execute(query)
            for row in cursor.fetchall():
                host_key, path, is_secure, is_httponly, name, enc_value, expires_utc, samesite = row

                if not enc_value:
                    continue

                # 统计加密版本
                ver = enc_value[:3]
                if ver == b'v20':
                    v20_count += 1

                # 解密
                value = _decrypt_cookie_value(enc_value, master_key, app_bound_key)
                if value is None:
                    if ver == b'v20':
                        v20_fail_count += 1
                    continue

                if ver in (b'v10', b'v11') or (not ver in (b'v10', b'v11', b'v20')):
                    v10_count += 1

                # 转换过期时间: Chrome 用 WebKit epoch (1601-01-01), Netscape 用 Unix epoch (1970-01-01)
                # Chrome expires_utc 是 microseconds
                if expires_utc:
                    # 11644473600 = seconds between 1601-01-01 and 1970-01-01
                    unix_expiry = (expires_utc / 1000000) - 11644473600
                else:
                    unix_expiry = 0

                all_cookies.append({
                    'domain': host_key,
                    'path': path,
                    'secure': bool(is_secure),
                    'httpOnly': bool(is_httponly),
                    'name': name,
                    'value': value,
                    'expires': int(unix_expiry),
                })
            conn.close()
        except Exception as e:
            last_error = str(e)
        finally:
            try:
                os.unlink(tmp_db)
            except:
                pass

    if not all_cookies:
        error_msg = last_error or '未找到任何 cookies'
        if not v20_available and app_bound_error:
            error_msg += f'（v20 解密不可用: {app_bound_error}）'
        return {'success': False, 'message': error_msg}

    # 生成 Netscape cookies.txt 格式
    lines = [
        "# Netscape HTTP Cookie File",
        f"# Generated by YouTube Downloader at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Source: {browser['name']}",
        "# This file can be used with yt-dlp --cookies option",
        "#",
        "# Please do not edit this file manually.",
        "",
    ]

    for cookie in all_cookies:
        # Netscape 格式: domain\tflag\tpath\tsecure\texpires\tname\tvalue
        flag = 'TRUE' if cookie['domain'].startswith('.') else 'FALSE'
        secure = 'TRUE' if cookie['secure'] else 'FALSE'
        # 会话 cookie (expires=0) 设置一个较长的过期时间
        expires = str(cookie['expires']) if cookie['expires'] > 0 else str(int(time.time()) + 86400 * 365)
        lines.append(f"{cookie['domain']}\t{flag}\t{cookie['path']}\t{secure}\t{expires}\t{cookie['name']}\t{cookie['value']}")

    cookies_txt = '\n'.join(lines) + '\n'

    status_parts = []
    if v20_available:
        status_parts.append('v10/v11/v20 全部支持')
    else:
        status_parts.append('v10/v11 可用')
        if app_bound_error:
            status_parts.append(f'v20 不可用({app_bound_error})')

    return {
        'success': True,
        'cookies_txt': cookies_txt,
        'cookie_count': len(all_cookies),
        'browser': browser['name'],
        'message':         f"成功从 {browser['name']} 提取 {len(all_cookies)} 个 cookies（{', '.join(status_parts)}）",
        'v20_supported': v20_available,
    }


def get_available_browsers():
    """获取可用的浏览器列表"""
    available = []
    for key, info in BROWSERS.items():
        if os.path.exists(info['local_state']):
            running = _is_browser_running(info['process'])
            available.append({
                'key': key,
                'name': info['name'],
                'running': running,
                'process': info['process'],
            })
    return available


# ============ 测试 ============
if __name__ == '__main__':
    print("=== 测试浏览器 Cookies 读取 ===\n")

    # 检查可用浏览器
    browsers = get_available_browsers()
    print(f"可用浏览器: {json.dumps(browsers, ensure_ascii=False, indent=2)}")

    for b in browsers:
        print(f"\n{'='*60}")
        print(f"测试: {b['name']} (running={b['running']})")
        print(f"{'='*60}")

        if b['running']:
            print(f"[WARNING] {b['name']} is running, trying to close...")
            if not _close_browser(b['process']):
                print("  Failed to close, skipping")
                continue
            print("  Closed")

        result = extract_cookies(b['key'], domain_filter='youtube.com')
        print(f"结果: {result['success']}")
        print(f"消息: {result['message']}")
        if result['success']:
            print(f"Cookies 数量: {result['cookie_count']}")
            # 显示前几行
            lines = result['cookies_txt'].split('\n')
            for line in lines[:15]:
                print(f"  {line}")
            if len(lines) > 15:
                print(f"  ... (共 {len(lines)} 行)")
        else:
            # 诊断信息
            print(f"v20 supported: {result.get('v20_supported', 'N/A')}")
            print(f"Is admin: {_is_admin()}")

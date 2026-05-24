#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili Download V1.0.0
B站视频下载工具 - PySide6 GUI版本
"""

import sys
import os
import json
import time
import re
import hashlib
import random
import threading
import subprocess
import webbrowser
import io
import traceback
from datetime import datetime
from urllib.parse import urlencode, quote, urlparse, parse_qs

import requests

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget,
    QTableWidgetItem, QProgressBar, QDialog, QFileDialog,
    QHeaderView, QSplitter, QFrame, QMessageBox, QAbstractItemView,
    QSizePolicy, QComboBox, QGridLayout, QGroupBox, QTabWidget,
    QScrollArea, QSpinBox, QSpacerItem
)
from PySide6.QtCore import Qt, Signal, QThread, QSize, QObject, QTimer
from PySide6.QtGui import QPixmap, QImage, QColor, QFont, QIcon

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ============================================================
# 常量定义
# ============================================================

MixinArray = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

QUALITY_MAP = {
    126: "杜比视界",
    125: "HDR真彩",
    120: "4K超清",
    116: "1080P60",
    112: "1080P+",
    80: "1080P",
    74: "720P60",
    64: "720P",
    32: "480P",
    16: "360P"
}

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


# ============================================================
# 工具函数
# ============================================================

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def sanitize_filename(name):
    if not name:
        return name
    if os.name == 'nt':
        invalid_chars = '<>:"/\\|?*'
    else:
        invalid_chars = '/\0'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name.strip()


def get_download_dir():
    config = load_config()
    custom_dir = config.get("download_dir")
    if custom_dir:
        if os.path.isabs(custom_dir):
            resolved = custom_dir
        else:
            resolved = os.path.normpath(os.path.join(get_app_dir(), custom_dir))
        if os.path.exists(resolved):
            return resolved
        try:
            os.makedirs(resolved, exist_ok=True)
            return resolved
        except Exception:
            pass
    download_dir = os.path.join(get_app_dir(), 'downloads')
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    return download_dir


# ============================================================
# 配置管理
# ============================================================

CONFIG_FILE = os.path.join(get_app_dir(), "config.json")
COOKIE_FILE = os.path.join(get_app_dir(), "config", "cookies.config")
LOGIN_STATE_FILE = os.path.join(get_app_dir(), "config", "login_state.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "download_dir": "",
        "user_agent": DEFAULT_UA,
        "default_qn": 80,
        "user_info": None
    }


def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    except Exception:
        pass
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_cookies():
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cookies(cookie_data):
    try:
        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
    except Exception:
        pass
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookie_data, f, ensure_ascii=False, indent=2)


def save_login_state(login_data):
    """保存完整登录状态到JSON文件"""
    try:
        os.makedirs(os.path.dirname(LOGIN_STATE_FILE), exist_ok=True)
    except Exception:
        pass
    login_data["save_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOGIN_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(login_data, f, ensure_ascii=False, indent=2)


def load_login_state():
    """从JSON文件加载登录状态"""
    if os.path.exists(LOGIN_STATE_FILE):
        try:
            with open(LOGIN_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def clear_login_state():
    """清除登录状态文件"""
    if os.path.exists(LOGIN_STATE_FILE):
        try:
            os.remove(LOGIN_STATE_FILE)
        except Exception:
            pass
    if os.path.exists(COOKIE_FILE):
        try:
            os.remove(COOKIE_FILE)
        except Exception:
            pass


# ============================================================
# WBI签名
# ============================================================

class WBISigner:
    def __init__(self):
        self.img_key = ""
        self.sub_key = ""
        self.mixin_key = ""
        self.last_refresh = 0
        self.session = requests.Session()

    def get_mixin_key(self, raw_key):
        return "".join(raw_key[i] for i in MixinArray)[:32]

    def refresh_keys(self, cookies_str=""):
        try:
            headers = {
                "User-Agent": DEFAULT_UA,
                "Referer": "https://www.bilibili.com"
            }
            if cookies_str:
                headers["Cookie"] = cookies_str
            resp = self.session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=headers, timeout=10
            )
            data = resp.json()
            if data.get("code") == 0:
                wbi_img = data["data"]["wbi_img"]
                img_url = wbi_img.get("img_url", "")
                sub_url = wbi_img.get("sub_url", "")
                self.img_key = img_url.split("/")[-1].split(".")[0]
                self.sub_key = sub_url.split("/")[-1].split(".")[0]
                self.mixin_key = self.get_mixin_key(self.img_key + self.sub_key)
                self.last_refresh = time.time()
                return True
        except Exception:
            pass
        return False

    def sign(self, url, cookies_str=""):
        if not self.mixin_key or (time.time() - self.last_refresh > 600):
            self.refresh_keys(cookies_str)
        if not self.mixin_key:
            return url

        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params["wts"] = [str(int(time.time()))]

        encoded_params = []
        for k in sorted(params.keys()):
            for v in params[k]:
                encoded_k = quote(str(k), safe="")
                encoded_v = quote(str(v), safe="")
                encoded_params.append(f"{encoded_k}={encoded_v}")

        query_string = "&".join(encoded_params)
        md5_hash = hashlib.md5((query_string + self.mixin_key).encode()).hexdigest()

        separator = "&" if parsed.query else "?"
        return f"{url}{separator}w_rid={md5_hash}&wts={params['wts'][0]}"


# ============================================================
# 浏览器指纹生成
# ============================================================

def random_hex(length):
    return "".join(random.choice("0123456789abcdef") for _ in range(length))


def generate_fingerprint():
    fp = {}
    session = requests.Session()
    try:
        resp = session.get("https://www.bilibili.com/", headers={
            "User-Agent": DEFAULT_UA
        }, timeout=10)
        set_cookies = resp.headers.get("Set-Cookie", "")
        for part in set_cookies.split(","):
            part = part.strip()
            if "=" in part:
                kv = part.split(";")[0].strip()
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k == "buvid3":
                        fp["buvid3"] = v
                    elif k == "b_nut":
                        fp["b_nut"] = v
    except Exception:
        fp["buvid3"] = random_hex(32)
        fp["b_nut"] = str(int(time.time()))

    if "buvid3" not in fp:
        fp["buvid3"] = random_hex(32)
    if "b_nut" not in fp:
        fp["b_nut"] = str(int(time.time()))

    ts = int(time.time())
    fp["b_lsid"] = random_hex(8) + "_" + format(ts, 'x')

    fp["_uuid"] = (
        random_hex(8) + "-" + random_hex(4) + "-4" + random_hex(3) + "-"
        + format(random.randint(0, 15), 'x') + random_hex(3) + "-"
        + random_hex(12) + "infoc"
    )

    try:
        resp = session.get("https://api.bilibili.com/x/frontend/finger/spi", headers={
            "User-Agent": DEFAULT_UA,
            "Referer": "https://www.bilibili.com/"
        }, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            fp["buvid4"] = data["data"]["b_4"]
    except Exception:
        fp["buvid4"] = random_hex(32)

    if "buvid4" in fp:
        raw = fp["buvid4"] + str(ts) + str(random.random())
        fp["buvid_fp"] = hashlib.md5(raw.encode()).hexdigest()

    fp["browser_resolution"] = "1920x1080"
    fp["i-wanna-go-back"] = "-1"

    return fp


def fingerprint_to_cookie_str(fp):
    return "; ".join(f"{k}={v}" for k, v in fp.items())


# ============================================================
# Bilibili API 客户端
# ============================================================

class BilibiliClient:
    def __init__(self):
        self.session = requests.Session()
        self.wbi_signer = WBISigner()
        self.fingerprint = {}
        self.login_cookies = {}
        self.refresh_token = ""
        self.user_info = None
        self.config = load_config()
        self._initialized = False

    def init_async(self):
        """异步初始化，在后台线程中调用"""
        if self._initialized:
            return
        self._init_fingerprint()
        self._load_login_data()
        self._initialized = True

    def _init_fingerprint(self):
        self.fingerprint = generate_fingerprint()

    def _load_login_data(self):
        # 优先从新的登录状态文件加载
        login_state = load_login_state()
        if login_state:
            self.login_cookies = login_state.get("cookies", {})
            self.refresh_token = login_state.get("refresh_token", "")
            self.user_info = login_state.get("user_info")
            # 验证Cookie有效性
            self._validate_cookies()
        else:
            # 兼容旧格式
            cookie_data = load_cookies()
            if cookie_data:
                self.login_cookies = cookie_data.get("cookies", {})
                self.refresh_token = cookie_data.get("refresh_token", "")
                self.user_info = self.config.get("user_info")
                self._validate_cookies()

    def _validate_cookies(self):
        """验证已保存的Cookie是否仍然有效"""
        if not self.login_cookies:
            return
        try:
            headers = self._get_headers()
            resp = self.session.get(
                "https://api.bilibili.com/x/web-interface/nav?build=0&mobi_app=web",
                headers=headers, timeout=10
            )
            data = resp.json()
            if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                self.user_info = data["data"]
                self._save_login_data()
            else:
                self.login_cookies = {}
                self.refresh_token = ""
                self.user_info = None
                clear_login_state()
        except Exception:
            pass

    def _get_cookie_str(self):
        parts = []
        if self.fingerprint:
            parts.append(fingerprint_to_cookie_str(self.fingerprint))
        if self.login_cookies:
            parts.append("; ".join(f"{k}={v}" for k, v in self.login_cookies.items()))
        return "; ".join(parts)

    def _get_headers(self, referer="https://www.bilibili.com"):
        return {
            "User-Agent": self.config.get("user_agent", DEFAULT_UA),
            "Referer": referer,
            "Cookie": self._get_cookie_str()
        }

    def _save_login_data(self):
        # 保存到新的登录状态JSON文件
        save_login_state({
            "cookies": self.login_cookies,
            "refresh_token": self.refresh_token,
            "user_info": self.user_info
        })
        # 同时保存到config.json以兼容
        self.config["user_info"] = self.user_info
        save_config(self.config)

    # ---- QR Code Login ----

    def get_qrcode(self):
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-web"
        headers = {
            "User-Agent": self.config.get("user_agent", DEFAULT_UA),
            "Referer": "https://passport.bilibili.com"
        }
        resp = self.session.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["qrcode_key"], data["data"]["url"]
        return None, None

    def poll_qrcode(self, qrcode_key):
        url = f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?source=main-web&qrcode_key={qrcode_key}"
        headers = {
            "User-Agent": self.config.get("user_agent", DEFAULT_UA),
            "Referer": "https://passport.bilibili.com"
        }
        resp = self.session.get(url, headers=headers, timeout=10)
        data = resp.json()
        code = data.get("data", {}).get("code", -1)

        if code == 0:
            self.refresh_token = data.get("data", {}).get("refresh_token", "")
            set_cookie_header = resp.headers.get("Set-Cookie", "")
            for part in set_cookie_header.split(","):
                part = part.strip()
                if "=" in part:
                    kv = part.split(";")[0].strip()
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        self.login_cookies[k.strip()] = v.strip()
            self._get_user_info()
            self._save_login_data()
            return 0
        elif code == 86038:
            return 86038
        elif code == 86090:
            return 86090
        elif code == 86101:
            return 86101
        return -1

    def _get_user_info(self):
        try:
            headers = self._get_headers()
            resp = self.session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=headers, timeout=10
            )
            data = resp.json()
            if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                d = data["data"]
                self.user_info = {
                    "uname": d.get("uname", ""),
                    "face": d.get("face", ""),
                    "mid": d.get("wallet", {}).get("mid", d.get("mid", ""))
                }
        except Exception:
            pass

    # ---- Video Info ----

    def parse_bv(self, text):
        match = re.search(r'BV[a-zA-Z0-9]+', text)
        if match:
            return match.group(0)
        return None

    def get_video_pages(self, bvid):
        url = f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}&jsonp=jsonp"
        headers = self._get_headers()
        resp = self.session.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", [])
        return []

    def get_video_detail(self, bvid):
        base_url = (
            f"https://api.bilibili.com/x/web-interface/wbi/view/detail?"
            f"platform=web&page_no=1&p=1&need_operation_card=1"
            f"&web_rm_repeat=1&need_elec=1&bvid={bvid}"
        )
        signed_url = self.wbi_signer.sign(base_url, self._get_cookie_str())
        headers = self._get_headers()
        resp = self.session.get(signed_url, headers=headers, timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("View", {})
        return {}

    def get_play_url(self, bvid, cid, qn=80):
        base_url = (
            f"https://api.bilibili.com/x/player/wbi/playurl?"
            f"cid={cid}&bvid={bvid}&qn={qn}&type=&otype=json"
            f"&fnver=0&fnval=4048&fourk=1&gaia_source=&from_client=BROWSER"
            f"&is_main_page=true&need_fragment=false&isGaiaAvoided=false"
            f"&client_attr=0&session=&voice_balance=1&web_location=1315873"
        )
        signed_url = self.wbi_signer.sign(base_url, self._get_cookie_str())
        headers = self._get_headers(referer=f"https://www.bilibili.com/video/{bvid}")
        try:
            resp = self.session.get(signed_url, headers=headers, timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {})
        except Exception:
            pass
        return {}

    def get_bangumi_play_url(self, aid, cid, qn=80):
        url = (
            f"https://api.bilibili.com/pgc/player/web/playurl?"
            f"fnver=0&fourk=1&otype=json&avid={aid}&cid={cid}&qn={qn}&fnval=4048"
        )
        headers = self._get_headers()
        resp = self.session.get(url, headers=headers, timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
        return {}

    def select_video_stream(self, dash_data, target_qn=80):
        videos = dash_data.get("video", [])
        if not videos:
            return None

        codec_priority = {"avc": 0, "hev": 1, "av01": 2, "av1": 2}
        qn_videos = [v for v in videos if v.get("id") == target_qn]
        if not qn_videos:
            available_qns = sorted(set(v.get("id") for v in videos), reverse=True)
            for qn in available_qns:
                if qn <= target_qn:
                    qn_videos = [v for v in videos if v.get("id") == qn]
                    break
            if not qn_videos:
                qn_videos = [videos[0]]

        qn_videos.sort(key=lambda v: codec_priority.get(v.get("codecid", ""), 9))
        return qn_videos[0]

    def select_audio_stream(self, dash_data):
        audios = dash_data.get("audio", [])
        if not audios:
            return None
        audios.sort(key=lambda a: a.get("bandwidth", 0), reverse=True)
        return audios[0]

    def get_available_qualities(self, bvid, cid):
        """获取视频可用的清晰度列表"""
        play_data = self.get_play_url(bvid, cid, qn=120)
        if not play_data:
            return []
        accept_quality = play_data.get("accept_quality", [])
        accept_description = play_data.get("accept_description", [])
        result = []
        for i, qn in enumerate(accept_quality):
            desc = accept_description[i] if i < len(accept_description) else QUALITY_MAP.get(qn, str(qn))
            result.append({"qn": qn, "description": desc})
        return result

    def download_file(self, url, filepath, headers, progress_callback=None, cancel_flag=None):
        resp = self.session.get(url, headers=headers, stream=True, timeout=120)
        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        start_time = time.time()
        last_update = 0

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if cancel_flag and cancel_flag.is_set():
                    return False
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    current_time = time.time()
                    if total_size > 0 and (current_time - last_update > 0.2 or downloaded >= total_size):
                        last_update = current_time
                        percent = min((downloaded / total_size) * 100, 100)
                        elapsed = current_time - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        if progress_callback:
                            progress_callback(percent, downloaded, total_size, speed)
        return True

    def merge_video_audio(self, video_path, audio_path, output_path):
        try:
            cmd = [
                "ffmpeg", "-i", video_path, "-i", audio_path,
                "-c", "copy", "-y", output_path
            ]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            result = subprocess.run(
                cmd, startupinfo=startupinfo,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120
            )
            return result.returncode == 0
        except Exception:
            return False


# ============================================================
# Worker Signals
# ============================================================

class WorkerSignals:
    def __init__(self):
        self.log_signal = None
        self.progress_signal = None
        self.status_signal = None
        self.finished_signal = None
        self.info_signal = None
        self.qr_signal = None
        self.login_signal = None


# ============================================================
# Query Worker
# ============================================================

class QueryWorker(QThread):
    log_signal = Signal(str, str)
    info_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, client, bv_input):
        super().__init__()
        self.client = client
        self.bv_input = bv_input

    def run(self):
        try:
            bvid = self.client.parse_bv(self.bv_input)
            if not bvid:
                self.error_signal.emit("无法解析BV号，请检查输入")
                return

            self.log_signal.emit(f"正在查询视频信息: {bvid}", "INFO")

            pages = self.client.get_video_pages(bvid)
            if not pages:
                self.error_signal.emit("无法获取视频分P列表")
                return

            detail = self.client.get_video_detail(bvid)
            if not detail:
                self.error_signal.emit("无法获取视频详情")
                return

            owner = detail.get("owner", {})
            info = {
                "bvid": bvid,
                "aid": detail.get("aid", ""),
                "title": detail.get("title", ""),
                "cover": detail.get("pic", ""),
                "up_name": owner.get("name", ""),
                "desc": detail.get("desc", ""),
                "pages": pages,
                "page_count": detail.get("videos", len(pages)),
                "is_bangumi": detail.get("rights", {}).get("is_cooperation", 0) == 1
            }

            self.log_signal.emit(f"查询成功: {info['title']}", "INFO")
            self.info_signal.emit(info)

        except Exception as e:
            self.error_signal.emit(f"查询失败: {str(e)}")


class QuickAddWorker(QThread):
    """快速添加下载任务工作线程"""
    log_signal = Signal(str, str)
    tasks_signal = Signal(list)

    def __init__(self, client, text, default_qn):
        super().__init__()
        self.client = client
        self.text = text
        self.default_qn = default_qn

    def run(self):
        try:
            bv = self.client.parse_bv(self.text)
            if not bv:
                self.log_signal.emit("无法解析BV号", "ERROR")
                return

            self.log_signal.emit(f"正在获取视频信息: {bv}", "INFO")

            pages = self.client.get_video_pages(bv)
            detail = self.client.get_video_detail(bv)
            if not pages or not detail:
                self.log_signal.emit("获取视频信息失败", "ERROR")
                return

            title = detail.get("title", "未知标题")
            up_name = detail.get("owner", {}).get("name", "未知UP主")

            tasks = []
            for i, page in enumerate(pages):
                cid = page.get("cid")
                part_title = page.get("part", title) or title
                tasks.append({
                    "bvid": bv,
                    "cid": cid,
                    "title": part_title,
                    "up_name": up_name,
                    "qn": self.default_qn,
                    "page_index": i
                })

            self.tasks_signal.emit(tasks)
            self.log_signal.emit(f"已添加 {len(tasks)} 个下载任务", "INFO")
        except Exception as e:
            self.log_signal.emit(f"解析失败: {e}", "ERROR")


# ============================================================
# Download Task Item Widget
# ============================================================

class DownloadTaskItem(QFrame):
    """单个下载任务项UI组件"""
    remove_requested = Signal(object)
    pause_requested = Signal(object)

    def __init__(self, task_id, title, up_name, qn, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.title = title
        self.up_name = up_name
        self.qn = qn
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            DownloadTaskItem {
                background-color: #fafafa;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                margin: 2px;
            }
        """)
        self.setFixedHeight(70)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        
        # 左侧信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        # 标题（截断显示）
        display_title = self.title[:35] + "..." if len(self.title) > 35 else self.title
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
        
        # UP主和画质
        self.info_label = QLabel(f"UP主: {self.up_name} | {QUALITY_MAP.get(self.qn, str(self.qn))}")
        self.info_label.setStyleSheet("font-size: 11px; color: #666;")
        
        # 状态
        self.status_label = QLabel("等待中...")
        self.status_label.setStyleSheet("font-size: 11px; color: #888;")
        
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.info_label)
        info_layout.addWidget(self.status_label)
        
        # 中间进度条
        progress_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        
        self.speed_label = QLabel("0 KB/s")
        self.speed_label.setStyleSheet("font-size: 10px; color: #888;")
        self.speed_label.setAlignment(Qt.AlignCenter)
        
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.speed_label)
        
        # 右侧按钮
        btn_layout = QVBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedSize(60, 28)
        self.btn_cancel.clicked.connect(lambda: self.remove_requested.emit(self))
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel, 0, Qt.AlignCenter)
        btn_layout.addStretch()
        
        layout.addLayout(info_layout, 3)
        layout.addLayout(progress_layout, 2)
        layout.addLayout(btn_layout, 0)

    def update_progress(self, percent, downloaded, total, speed):
        self.progress_bar.setValue(int(percent))
        if speed > 0:
            if speed > 1024 * 1024:
                speed_text = f"{speed / 1024 / 1024:.1f} MB/s"
            elif speed > 1024:
                speed_text = f"{speed / 1024:.1f} KB/s"
            else:
                speed_text = f"{speed:.0f} B/s"
            self.speed_label.setText(speed_text)
        if total > 0:
            downloaded_mb = downloaded / 1024 / 1024
            total_mb = total / 1024 / 1024
            self.status_label.setText(f"下载中... {downloaded_mb:.1f}/{total_mb:.1f} MB")

    def set_status(self, status):
        self.status_label.setText(status)
        if "完成" in status:
            self.progress_bar.setValue(100)
            self.btn_cancel.setText("关闭")
        elif "失败" in status or "取消" in status:
            self.btn_cancel.setText("关闭")

    def set_downloading(self):
        self.status_label.setText("下载中...")


# ============================================================
# Download Queue Manager
# ============================================================

class DownloadQueueManager(QObject):
    """下载队列管理器"""
    task_added = Signal(dict)
    task_started = Signal(str)
    task_finished = Signal(str, bool, str)
    task_progress = Signal(str, float, float, float, float)
    task_status = Signal(str, str)
    all_finished = Signal()

    def __init__(self, client, max_concurrent=1):
        super().__init__()
        self.client = client
        self.max_concurrent = max_concurrent
        self.queue = []
        self.active_tasks = {}
        self.task_workers = {}
        self._lock = threading.Lock()
        self._task_counter = 0

    def set_max_concurrent(self, count):
        self.max_concurrent = min(count, 3)
        self._try_start_next()

    def add_task(self, bvid, cid, title, up_name, qn, page_index=0):
        with self._lock:
            self._task_counter += 1
            task_id = f"task_{self._task_counter}"
            task = {
                "id": task_id,
                "bvid": bvid,
                "cid": cid,
                "title": title,
                "up_name": up_name,
                "qn": qn,
                "page_index": page_index
            }
            self.queue.append(task)
        
        self.task_added.emit(task)
        self._try_start_next()
        return task_id

    def _try_start_next(self):
        task = None
        with self._lock:
            if len(self.active_tasks) >= self.max_concurrent:
                return
            if not self.queue:
                if not self.active_tasks:
                    self.all_finished.emit()
                return
            
            task = self.queue.pop(0)
            self.active_tasks[task["id"]] = task
        
        if task:
            task_id = task["id"]
            worker = DownloadWorker(
                self.client, task["bvid"], task["cid"],
                task["title"], task["qn"], task["page_index"]
            )
            worker.log_signal.connect(lambda msg, lv: None)
            worker.progress_signal.connect(
                lambda p, d, t, s, tid=task_id: self.task_progress.emit(tid, p, d, t, s)
            )
            worker.status_signal.connect(
                lambda s, tid=task_id: self.task_status.emit(tid, s)
            )
            worker.finished_signal.connect(
                lambda success, msg, tid=task_id: self._on_task_finished(tid, success, msg)
            )
            
            self.task_workers[task_id] = worker
            self.task_started.emit(task_id)
            worker.start()

    def _on_task_finished(self, task_id, success, msg):
        with self._lock:
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
            if task_id in self.task_workers:
                del self.task_workers[task_id]
        
        self.task_finished.emit(task_id, success, msg)
        self._try_start_next()

    def cancel_task(self, task_id):
        if task_id in self.task_workers:
            self.task_workers[task_id].cancel()

    def get_queue_count(self):
        return len(self.queue)

    def get_active_count(self):
        return len(self.active_tasks)


# ============================================================
# Download Worker
# ============================================================

class DownloadWorker(QThread):
    log_signal = Signal(str, str)
    progress_signal = Signal(float, float, float, float)
    status_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, client, bvid, cid, title, qn, page_index=0):
        super().__init__()
        self.client = client
        self.bvid = bvid
        self.cid = cid
        self.title = title
        self.qn = qn
        self.page_index = page_index
        self.cancel_flag = threading.Event()

    def run(self):
        try:
            self.status_signal.emit("正在获取下载链接...")
            self.log_signal.emit(f"正在获取播放链接: BV={self.bvid}, CID={self.cid}, QN={self.qn}", "INFO")

            play_data = self.client.get_play_url(self.bvid, self.cid, self.qn)
            if not play_data:
                self.finished_signal.emit(False, "获取播放链接失败")
                return

            dash = play_data.get("dash", {})
            if not dash:
                self.finished_signal.emit(False, "未获取到DASH数据，可能需要登录")
                return

            video_stream = self.client.select_video_stream(dash, self.qn)
            audio_stream = self.client.select_audio_stream(dash)

            if not video_stream:
                self.finished_signal.emit(False, "未找到合适的视频流")
                return

            video_url = video_stream.get("baseUrl") or video_stream.get("base_url", "")
            audio_url = ""
            if audio_stream:
                audio_url = audio_stream.get("baseUrl") or audio_stream.get("base_url", "")

            if not video_url:
                self.finished_signal.emit(False, "视频流URL为空")
                return

            download_dir = get_download_dir()
            safe_title = sanitize_filename(self.title)
            if self.page_index > 0:
                base_name = f"{safe_title}_P{self.page_index + 1}"
            else:
                base_name = safe_title

            video_temp = os.path.join(download_dir, f"{base_name}_video.m4s")
            audio_temp = os.path.join(download_dir, f"{base_name}_audio.m4s")
            output_file = os.path.join(download_dir, f"{base_name}.mp4")

            dl_headers = self.client._get_headers(referer=f"https://www.bilibili.com/video/{self.bvid}")
            dl_headers["Range"] = "bytes=0-"

            self.status_signal.emit("正在下载视频流...")
            self.log_signal.emit(f"视频流: QN={video_stream.get('id')}, Codec={video_stream.get('codecid')}", "INFO")

            def video_progress(percent, downloaded, total, speed):
                half_percent = percent / 2
                self.progress_signal.emit(half_percent, downloaded, total, speed)

            ok = self.client.download_file(video_url, video_temp, dl_headers, video_progress, self.cancel_flag)
            if not ok:
                self._cleanup(video_temp, audio_temp)
                self.finished_signal.emit(False, "视频流下载已取消或失败")
                return

            if audio_url:
                self.status_signal.emit("正在下载音频流...")
                self.log_signal.emit("正在下载音频流...", "INFO")

                def audio_progress(percent, downloaded, total, speed):
                    half_percent = 50 + percent / 2
                    self.progress_signal.emit(half_percent, downloaded, total, speed)

                ok = self.client.download_file(audio_url, audio_temp, dl_headers, audio_progress, self.cancel_flag)
                if not ok:
                    self._cleanup(video_temp, audio_temp)
                    self.finished_signal.emit(False, "音频流下载已取消或失败")
                    return

                self.status_signal.emit("正在合并音视频...")
                self.log_signal.emit("正在使用ffmpeg合并音视频...", "INFO")

                merge_ok = self.client.merge_video_audio(video_temp, audio_temp, output_file)
                self._cleanup(video_temp, audio_temp)

                if not merge_ok:
                    self.finished_signal.emit(False, "ffmpeg合并失败，请确保已安装ffmpeg")
                    return
            else:
                import shutil
                shutil.move(video_temp, output_file)
                self._cleanup(audio_temp)

            file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
            self.progress_signal.emit(100, 1, 1, 0)
            self.status_signal.emit("下载完成!")
            self.log_signal.emit(f"下载完成: {output_file} ({file_size / 1024 / 1024:.2f}MB)", "INFO")
            self.finished_signal.emit(True, output_file)

        except Exception as e:
            self.log_signal.emit(f"下载异常: {traceback.format_exc()}", "ERROR")
            self.finished_signal.emit(False, str(e))

    def _cleanup(self, *files):
        for f in files:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def cancel(self):
        self.cancel_flag.set()


# ============================================================
# Login Worker
# ============================================================

class LoginWorker(QThread):
    log_signal = Signal(str, str)
    qr_signal = Signal(bytes)
    login_signal = Signal(bool, str)

    def __init__(self, client):
        super().__init__()
        self.client = client
        self._stop = False

    def run(self):
        try:
            self.log_signal.emit("正在获取登录二维码...", "INFO")
            qrcode_key, qrcode_url = self.client.get_qrcode()

            if not qrcode_key or not qrcode_url:
                self.login_signal.emit(False, "获取二维码失败")
                return

            if HAS_QRCODE:
                qr = qrcode.QRCode(box_size=6, border=2)
                qr.add_data(qrcode_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                qr_bytes = buf.getvalue()
                self.qr_signal.emit(qr_bytes)
            else:
                self.log_signal.emit("qrcode库未安装，请手动打开链接扫码", "WARNING")
                self.log_signal.emit(f"扫码链接: {qrcode_url}", "INFO")

            self.log_signal.emit("请使用B站手机客户端扫描二维码", "INFO")

            while not self._stop:
                time.sleep(2)
                code = self.client.poll_qrcode(qrcode_key)

                if code == 0:
                    uname = self.client.user_info.get("uname", "未知") if self.client.user_info else "未知"
                    self.log_signal.emit(f"登录成功! 用户: {uname}", "INFO")
                    self.login_signal.emit(True, uname)
                    return
                elif code == 86038:
                    self.log_signal.emit("二维码已过期，请重新获取", "WARNING")
                    self.login_signal.emit(False, "二维码已过期")
                    return
                elif code == 86090:
                    self.log_signal.emit("已扫码，请在手机上确认登录", "INFO")
                elif code == 86101:
                    pass
                else:
                    self.log_signal.emit(f"未知状态码: {code}", "WARNING")

            self.login_signal.emit(False, "已取消")

        except Exception as e:
            self.log_signal.emit(f"登录异常: {str(e)}", "ERROR")
            self.login_signal.emit(False, str(e))

    def stop(self):
        self._stop = True


# ============================================================
# Cover Image Loader
# ============================================================

class CoverLoader(QThread):
    loaded = Signal(bytes)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            headers = {
                "User-Agent": DEFAULT_UA,
                "Referer": "https://www.bilibili.com"
            }
            resp = requests.get(self.url, headers=headers, timeout=15)
            if resp.status_code == 200:
                self.loaded.emit(resp.content)
        except Exception:
            pass


# ============================================================
# Main Window
# ============================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client = BilibiliClient()
        self.current_video_info = None
        self.query_worker = None
        self.cover_loader = None
        self._ffmpeg_available = False
        self.task_items = {}

        self.setWindowTitle("Bilibili Download V1.0.0")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 800)
        self._center_window()

        self._check_ffmpeg()
        self._setup_ui()
        self._init_download_manager()
        
        # 异步初始化客户端
        self._init_client_async()

    def _init_client_async(self):
        """在后台线程中初始化客户端"""
        self._init_thread = threading.Thread(target=self.client.init_async, daemon=True)
        self._init_thread.start()
        # 使用定时器检查初始化完成
        self._init_timer = QTimer()
        self._init_timer.timeout.connect(self._check_init_complete)
        self._init_timer.start(100)

    def _check_init_complete(self):
        """检查初始化是否完成"""
        if self.client._initialized:
            self._init_timer.stop()
            self._update_login_status()
            if not self._ffmpeg_available:
                self.log("未检测到ffmpeg，下载后将无法合并音视频文件！请安装ffmpeg并添加到PATH", "WARNING")

    def _center_window(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def _check_ffmpeg(self):
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            result = subprocess.run(
                ["ffmpeg", "-version"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                startupinfo=startupinfo, timeout=5
            )
            self._ffmpeg_available = result.returncode == 0
        except Exception:
            self._ffmpeg_available = False

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        # ---- Top Toolbar ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_settings = QPushButton("设置")
        btn_settings.setFixedSize(80, 32)
        btn_settings.clicked.connect(self._open_settings)

        btn_about = QPushButton("关于")
        btn_about.setFixedSize(80, 32)
        btn_about.clicked.connect(self._open_about)

        toolbar.addWidget(btn_settings)
        toolbar.addWidget(btn_about)
        toolbar.addStretch()

        main_layout.addLayout(toolbar)

        # ---- Tab Widget ----
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #ddd; border-radius: 4px; }
            QTabBar::tab { padding: 8px 20px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: #3b82f6; color: white; }
            QTabBar::tab:!selected { background-color: #f0f0f0; }
        """)
        
        # 查询页面
        self.query_page = self._create_query_page()
        self.tab_widget.addTab(self.query_page, "视频查询")
        
        # 下载页面
        self.download_page = self._create_download_page()
        self.tab_widget.addTab(self.download_page, "下载任务")
        
        main_layout.addWidget(self.tab_widget, 1)

    def _create_query_page(self):
        """创建视频查询页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("视频链接/BV号:"))
        self.input_field = QLineEdit()
        self.input_field.setFixedWidth(280)
        self.input_field.setPlaceholderText("输入BV号或视频链接")
        self.input_field.returnPressed.connect(self._on_query)
        btn_search = QPushButton("查询")
        btn_search.setFixedSize(70, 32)
        btn_search.clicked.connect(self._on_query)
        btn_download = QPushButton("添加到下载")
        btn_download.setFixedSize(100, 32)
        btn_download.clicked.connect(self._add_to_download)
        search_layout.addWidget(self.input_field)
        search_layout.addWidget(btn_search)
        search_layout.addWidget(btn_download)
        search_layout.addStretch()
        layout.addLayout(search_layout)

        # 内容区域
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：视频信息
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)

        detail_frame = QFrame()
        detail_frame.setStyleSheet("QFrame { border: 1px solid #ddd; border-radius: 4px; padding: 5px; }")
        detail_layout = QHBoxLayout(detail_frame)

        self.cover_label = QLabel("封面")
        self.cover_label.setFixedSize(160, 100)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("QLabel { background-color: #f0f0f0; border-radius: 4px; }")

        info_layout = QVBoxLayout()
        self.title_label = QLabel("标题: -")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.up_label = QLabel("UP主: -")
        self.desc_label = QLabel("简介: -")
        self.desc_label.setWordWrap(True)
        self.page_count_label = QLabel("分P数: -")
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.up_label)
        info_layout.addWidget(self.desc_label)
        info_layout.addWidget(self.page_count_label)
        info_layout.addStretch()

        detail_layout.addWidget(self.cover_label)
        detail_layout.addLayout(info_layout, 1)
        left_layout.addWidget(detail_frame, 2)

        self.page_table = QTableWidget()
        self.page_table.setColumnCount(4)
        self.page_table.setHorizontalHeaderLabels(["序号", "标题", "时长", "CID"])
        self.page_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.page_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.page_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.page_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.page_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.page_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.page_table.setAlternatingRowColors(True)
        left_layout.addWidget(self.page_table, 3)

        # 右侧：日志
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 0, 0, 0)
        log_label = QLabel("日志")
        log_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        right_layout.addWidget(log_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumWidth(260)
        self.log_text.setMaximumWidth(320)
        right_layout.addWidget(self.log_text)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        layout.addWidget(splitter, 1)
        return page

    def _create_download_page(self):
        """创建下载任务页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 顶部输入栏
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("视频链接/BV号:"))
        self.dl_input_field = QLineEdit()
        self.dl_input_field.setPlaceholderText("输入BV号或视频链接，按回车添加下载任务")
        self.dl_input_field.returnPressed.connect(self._quick_add_download)
        btn_add = QPushButton("添加下载")
        btn_add.setFixedSize(90, 32)
        btn_add.clicked.connect(self._quick_add_download)
        input_layout.addWidget(self.dl_input_field, 1)
        input_layout.addWidget(btn_add)
        layout.addLayout(input_layout)

        # 状态栏
        self.dl_status_label = QLabel("等待中: 0 | 下载中: 0")
        self.dl_status_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.dl_status_label)

        # 任务列表区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #ddd; border-radius: 4px; }")
        
        self.task_list_widget = QWidget()
        self.task_list_layout = QVBoxLayout(self.task_list_widget)
        self.task_list_layout.setContentsMargins(5, 5, 5, 5)
        self.task_list_layout.setSpacing(5)
        self.task_list_layout.addStretch()
        
        scroll.setWidget(self.task_list_widget)
        layout.addWidget(scroll, 1)

        return page

    def _init_download_manager(self):
        """初始化下载队列管理器"""
        max_concurrent = self.client.config.get("max_concurrent", 1)
        self.download_manager = DownloadQueueManager(self.client, max_concurrent)
        self.download_manager.task_added.connect(self._on_task_added)
        self.download_manager.task_started.connect(self._on_task_started)
        self.download_manager.task_finished.connect(self._on_task_finished)
        self.download_manager.task_progress.connect(self._on_task_progress)
        self.download_manager.task_status.connect(self._on_task_status)
        self.download_manager.all_finished.connect(self._on_all_finished)

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "INFO": "#42A5F5",
            "WARNING": "#FFB74D",
            "ERROR": "#EF5350"
        }
        color = color_map.get(level, "#42A5F5")
        header_color = {"INFO": "#0D47A1", "WARNING": "#E65100", "ERROR": "#B71C1C"}.get(level, "#0D47A1")
        self.log_text.append(
            f'<span style="color:{header_color}">[{timestamp}] [{level}]</span> '
            f'<span style="color:{color}">{message}</span>'
        )
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    # ---- Query ----

    def _on_query(self):
        text = self.input_field.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入视频链接或BV号")
            return

        self.log(f"开始查询: {text}", "INFO")
        self.query_worker = QueryWorker(self.client, text)
        self.query_worker.log_signal.connect(self.log)
        self.query_worker.info_signal.connect(self._on_query_result)
        self.query_worker.error_signal.connect(self._on_query_error)
        self.query_worker.start()

    def _on_query_result(self, info):
        self.current_video_info = info
        self.title_label.setText(f"标题: {info['title']}")
        self.up_label.setText(f"UP主: {info['up_name']}")
        self.desc_label.setText(f"简介: {info['desc'][:100]}{'...' if len(info['desc']) > 100 else ''}")
        self.page_count_label.setText(f"分P数: {info['page_count']}")

        if info.get("cover"):
            self.cover_loader = CoverLoader(info["cover"])
            self.cover_loader.loaded.connect(self._on_cover_loaded)
            self.cover_loader.start()

        self.page_table.setRowCount(len(info["pages"]))
        for i, page in enumerate(info["pages"]):
            self.page_table.setItem(i, 0, QTableWidgetItem(str(page.get("page", i + 1))))
            self.page_table.setItem(i, 1, QTableWidgetItem(page.get("part", "")))
            duration = page.get("duration", 0)
            mins, secs = divmod(duration, 60)
            self.page_table.setItem(i, 2, QTableWidgetItem(f"{mins}:{secs:02d}"))
            self.page_table.setItem(i, 3, QTableWidgetItem(str(page.get("cid", ""))))

    def _on_query_error(self, msg):
        self.log(msg, "ERROR")
        QMessageBox.warning(self, "查询失败", msg)

    def _on_cover_loaded(self, data):
        img = QImage()
        img.loadFromData(data)
        if not img.isNull():
            pixmap = QPixmap.fromImage(img).scaled(
                160, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.cover_label.setPixmap(pixmap)

    # ---- Download ----

    def _add_to_download(self):
        """从查询页面添加下载任务"""
        if not self.current_video_info:
            QMessageBox.warning(self, "提示", "请先查询视频信息")
            return

        if not self._ffmpeg_available:
            reply = QMessageBox.question(
                self, "警告", "未检测到ffmpeg，合并将失败。是否继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        info = self.current_video_info
        row = self.page_table.currentRow()
        if row < 0 and len(info["pages"]) > 0:
            row = 0

        if row < 0 or row >= len(info["pages"]):
            QMessageBox.warning(self, "提示", "请选择要下载的分P")
            return

        page = info["pages"][row]
        cid = page.get("cid")
        title = page.get("part", info["title"]) or info["title"]

        self._add_download_task(info["bvid"], cid, title, info["up_name"], row)

    def _quick_add_download(self):
        """快速添加下载任务（下载页面输入框）"""
        text = self.dl_input_field.text().strip()
        if not text:
            return

        if not self._ffmpeg_available:
            QMessageBox.warning(self, "警告", "未检测到ffmpeg，无法下载")
            return

        self.dl_input_field.clear()
        qn = self.client.config.get("default_qn", 80)
        self.quick_add_worker = QuickAddWorker(self.client, text, qn)
        self.quick_add_worker.log_signal.connect(self.log)
        self.quick_add_worker.tasks_signal.connect(self._on_quick_add_tasks)
        self.quick_add_worker.start()

    def _on_quick_add_tasks(self, tasks):
        """快速添加任务结果"""
        for task in tasks:
            self.download_manager.add_task(
                task["bvid"], task["cid"], task["title"],
                task["up_name"], task["qn"], task["page_index"]
            )
        self._update_dl_status()

    def _add_download_task(self, bvid, cid, title, up_name, page_index):
        """添加下载任务到队列"""
        qn = self.client.config.get("default_qn", 80)
        task_id = self.download_manager.add_task(bvid, cid, title, up_name, qn, page_index)
        self.log(f"已添加任务: {title[:30]}...", "INFO")
        self._update_dl_status()

    def _on_task_added(self, task):
        """任务添加到队列"""
        task_id = task["id"]
        item = DownloadTaskItem(task_id, task["title"], task["up_name"], task["qn"])
        item.remove_requested.connect(self._on_task_remove)
        self.task_items[task_id] = item
        self.task_list_layout.insertWidget(self.task_list_layout.count() - 1, item)
        self._update_dl_status()

    def _on_task_started(self, task_id):
        """任务开始下载"""
        if task_id in self.task_items:
            self.task_items[task_id].set_downloading()
        self._update_dl_status()

    def _on_task_progress(self, task_id, percent, downloaded, total, speed):
        """任务进度更新"""
        if task_id in self.task_items:
            self.task_items[task_id].update_progress(percent, downloaded, total, speed)

    def _on_task_status(self, task_id, status):
        """任务状态更新"""
        if task_id in self.task_items:
            self.task_items[task_id].set_status(status)

    def _on_task_finished(self, task_id, success, msg):
        """任务完成"""
        if task_id in self.task_items:
            if success:
                self.task_items[task_id].set_status("下载完成!")
            else:
                self.task_items[task_id].set_status(f"失败: {msg}")
        self._update_dl_status()

    def _on_task_remove(self, item):
        """移除任务"""
        task_id = item.task_id
        self.download_manager.cancel_task(task_id)
        if task_id in self.task_items:
            self.task_list_layout.removeWidget(self.task_items[task_id])
            self.task_items[task_id].deleteLater()
            del self.task_items[task_id]
        self._update_dl_status()

    def _on_all_finished(self):
        """所有任务完成"""
        self._update_dl_status()
        self.log("所有下载任务已完成", "INFO")

    def _update_dl_status(self):
        """更新下载状态显示"""
        waiting = self.download_manager.get_queue_count()
        active = self.download_manager.get_active_count()
        self.dl_status_label.setText(f"等待中: {waiting} | 下载中: {active}")

    # ---- Settings ----

    def _open_settings(self):
        dlg = SettingsDialog(self, self.client)
        dlg.login_status_changed.connect(self._update_login_status)
        dlg.config_changed.connect(self._on_config_changed)
        dlg.exec()

    def _on_config_changed(self):
        """配置变更"""
        max_concurrent = self.client.config.get("max_concurrent", 1)
        self.download_manager.set_max_concurrent(max_concurrent)

    def _update_login_status(self):
        if self.client.user_info:
            uname = self.client.user_info.get("uname", "")
            self.log(f"当前登录用户: {uname}", "INFO")
        else:
            self.log("未登录", "WARNING")

    # ---- About ----

    def _open_about(self):
        dlg = AboutDialog(self)
        dlg.exec()


# ============================================================
# Settings Dialog
# ============================================================

class SettingsDialog(QDialog):
    login_status_changed = Signal()
    config_changed = Signal()

    def __init__(self, parent, client):
        super().__init__(parent)
        self.client = client
        self.login_worker = None
        self.setWindowTitle("设置")
        self.setFixedSize(600, 750)
        self.setModal(True)
        self._center_on_parent(parent)
        self._setup_ui()

    def _center_on_parent(self, parent):
        if parent:
            px = parent.x() + (parent.width() - self.width()) // 2
            py = parent.y() + (parent.height() - self.height()) // 2
            self.move(px, py)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Download dir
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("下载目录:"))
        self.dir_input = QLineEdit()
        self.dir_input.setText(get_download_dir())
        dir_layout.addWidget(self.dir_input, 1)
        btn_browse = QPushButton("浏览...")
        btn_browse.setFixedWidth(70)
        btn_browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(btn_browse)
        layout.addLayout(dir_layout)

        # Quality
        qn_layout = QHBoxLayout()
        qn_layout.addWidget(QLabel("默认画质:"))
        self.qn_combo = QComboBox()
        for qn_val, qn_name in sorted(QUALITY_MAP.items(), reverse=True):
            self.qn_combo.addItem(qn_name, qn_val)
        current_qn = self.client.config.get("default_qn", 80)
        for i in range(self.qn_combo.count()):
            if self.qn_combo.itemData(i) == current_qn:
                self.qn_combo.setCurrentIndex(i)
                break
        qn_layout.addWidget(self.qn_combo, 1)
        layout.addLayout(qn_layout)

        # Max concurrent downloads
        concurrent_layout = QHBoxLayout()
        concurrent_layout.addWidget(QLabel("同时下载数:"))
        self.concurrent_combo = QComboBox()
        self.concurrent_combo.addItem("1 个", 1)
        self.concurrent_combo.addItem("2 个", 2)
        self.concurrent_combo.addItem("3 个", 3)
        current_max = self.client.config.get("max_concurrent", 1)
        for i in range(self.concurrent_combo.count()):
            if self.concurrent_combo.itemData(i) == current_max:
                self.concurrent_combo.setCurrentIndex(i)
                break
        concurrent_layout.addWidget(self.concurrent_combo, 1)
        layout.addLayout(concurrent_layout)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color: #cccccc;")
        layout.addWidget(sep1)

        # Login section
        login_label = QLabel("B站登录")
        login_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(login_label)

        btn_login = QPushButton("登录B站")
        btn_login.setFixedWidth(120)
        btn_login.clicked.connect(self._on_login)
        layout.addWidget(btn_login)

        self.qr_label = QLabel("二维码将显示在此处")
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet("QLabel { background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; }")
        layout.addWidget(self.qr_label, 0, Qt.AlignCenter)

        self.login_status_label = QLabel()
        self._update_login_label()
        layout.addWidget(self.login_status_label)

        self.login_log = QTextEdit()
        self.login_log.setReadOnly(True)
        self.login_log.setMaximumHeight(120)
        layout.addWidget(self.login_log)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #cccccc;")
        layout.addWidget(sep2)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.setFixedWidth(80)
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择下载目录")
        if d:
            self.dir_input.setText(d)

    def _update_login_label(self):
        if self.client.user_info:
            uname = self.client.user_info.get("uname", "未知")
            mid = self.client.user_info.get("mid", "")
            self.login_status_label.setText(f"已登录: {uname} (UID: {mid})")
            self.login_status_label.setStyleSheet("color: green;")
        else:
            self.login_status_label.setText("未登录")
            self.login_status_label.setStyleSheet("color: gray;")

    def _on_login(self):
        if not HAS_QRCODE:
            self._append_login_log("qrcode库未安装，请安装: pip install qrcode[pil]", "ERROR")
            return

        self.qr_label.setText("正在获取二维码...")
        self.login_worker = LoginWorker(self.client)
        self.login_worker.log_signal.connect(self._append_login_log)
        self.login_worker.qr_signal.connect(self._show_qr)
        self.login_worker.login_signal.connect(self._on_login_result)
        self.login_worker.start()

    def _append_login_log(self, msg, level="INFO"):
        color_map = {"INFO": "#42A5F5", "WARNING": "#FFB74D", "ERROR": "#EF5350"}
        color = color_map.get(level, "#42A5F5")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.login_log.append(
            f'<span style="color:gray">[{timestamp}]</span> '
            f'<span style="color:{color}">{msg}</span>'
        )

    def _show_qr(self, data):
        img = QImage()
        img.loadFromData(data)
        if not img.isNull():
            pixmap = QPixmap.fromImage(img).scaled(
                200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.qr_label.setPixmap(pixmap)
        else:
            self.qr_label.setText("二维码加载失败")

    def _on_login_result(self, success, msg):
        if success:
            self._append_login_log(f"登录成功: {msg}", "INFO")
        else:
            self._append_login_log(f"登录失败: {msg}", "ERROR")
        self._update_login_label()
        self.login_status_changed.emit()

    def _save(self):
        self.client.config["download_dir"] = self.dir_input.text().strip()
        self.client.config["default_qn"] = self.qn_combo.currentData()
        self.client.config["max_concurrent"] = self.concurrent_combo.currentData()
        save_config(self.client.config)

        download_dir = self.dir_input.text().strip()
        if download_dir and not os.path.exists(download_dir):
            try:
                os.makedirs(download_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "提示", f"无法创建目录: {e}")
                return

        self.config_changed.emit()
        self.accept()


# ============================================================
# Quality Select Dialog
# ============================================================

class QualitySelectDialog(QDialog):
    """清晰度选择对话框"""

    def __init__(self, parent, qualities, default_qn=80):
        super().__init__(parent)
        self.setWindowTitle("选择清晰度")
        self.setFixedSize(400, 300)
        self.setModal(True)
        self.selected_qn = None
        self._qualities = qualities
        self._default_qn = default_qn
        self._setup_ui()
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        if parent:
            px = parent.x() + (parent.width() - self.width()) // 2
            py = parent.y() + (parent.height() - self.height()) // 2
            self.move(px, py)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        label = QLabel("请选择下载清晰度:")
        label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(label)

        self.quality_table = QTableWidget()
        self.quality_table.setColumnCount(2)
        self.quality_table.setHorizontalHeaderLabels(["清晰度", "QN值"])
        self.quality_table.horizontalHeader().setStretchLastSection(True)
        self.quality_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.quality_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.quality_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.quality_table.setRowCount(len(self._qualities))

        default_row = 0
        for i, q in enumerate(self._qualities):
            qn = q["qn"]
            desc = q["description"]
            self.quality_table.setItem(i, 0, QTableWidgetItem(desc))
            self.quality_table.setItem(i, 1, QTableWidgetItem(str(qn)))
            if qn == self._default_qn:
                default_row = i

        self.quality_table.selectRow(default_row)
        self.quality_table.doubleClicked.connect(self.accept)
        layout.addWidget(self.quality_table)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_ok.setFixedWidth(80)
        btn_ok.clicked.connect(self._on_accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _on_accept(self):
        row = self.quality_table.currentRow()
        if row >= 0 and row < len(self._qualities):
            self.selected_qn = self._qualities[row]["qn"]
        self.accept()

    @staticmethod
    def select_quality(parent, qualities, default_qn=80):
        """弹出清晰度选择对话框，返回选中的qn值，取消返回None"""
        dlg = QualitySelectDialog(parent, qualities, default_qn)
        if dlg.exec() == QDialog.Accepted:
            return dlg.selected_qn
        return None


# ============================================================
# Download Dialog
# ============================================================

class DownloadDialog(QDialog):
    def __init__(self, parent, title, qn):
        super().__init__(parent)
        self.setWindowTitle(f"下载: {title}")
        self.setFixedSize(550, 300)
        self.setModal(True)
        self._cancel_callback = None
        self._qn = qn
        self._center_on_parent(parent)
        self._setup_ui(title)

    def _center_on_parent(self, parent):
        if parent:
            px = parent.x() + (parent.width() - self.width()) // 2
            py = parent.y() + (parent.height() - self.height()) // 2
            self.move(px, py)

    def _setup_ui(self, title):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        name_label = QLabel(f"视频: {title}")
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(name_label)

        qn_name = QUALITY_MAP.get(self._qn, str(self._qn))
        self.status_label = QLabel(f"画质: {qn_name} - 正在获取下载链接...")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.percent_label = QLabel("0%")
        self.percent_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.percent_label)

        self.speed_label = QLabel("")
        self.speed_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.speed_label)

        btn_layout = QHBoxLayout()
        btn_folder = QPushButton("打开下载文件夹")
        btn_folder.setFixedWidth(130)
        btn_folder.clicked.connect(self._open_folder)
        self.btn_cancel = QPushButton("取消下载")
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_folder)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def set_cancel_callback(self, callback):
        self._cancel_callback = callback

    def update_progress(self, percent, downloaded, total, speed):
        self.progress_bar.setValue(int(percent))
        self.percent_label.setText(f"{percent:.1f}%")
        if total > 0:
            self.speed_label.setText(
                f"已下载: {downloaded / 1024 / 1024:.1f}MB / {total / 1024 / 1024:.1f}MB  "
                f"速度: {speed / 1024:.0f}KB/s"
            )

    def update_status(self, text):
        self.status_label.setText(text)

    def append_log(self, msg, level="INFO"):
        pass

    def on_finished(self, success, msg):
        if success:
            self.status_label.setText("下载完成!")
            self.progress_bar.setValue(100)
            self.percent_label.setText("100%")
            self.btn_cancel.setText("关闭")
        else:
            self.status_label.setText(f"下载失败: {msg}")
            self.btn_cancel.setText("关闭")

    def _on_cancel(self):
        if self.btn_cancel.text() == "关闭":
            self.accept()
            return
        if self._cancel_callback:
            self._cancel_callback()
        self.btn_cancel.setText("关闭")

    def _open_folder(self):
        webbrowser.open(get_download_dir())


# ============================================================
# About Dialog
# ============================================================

class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setFixedSize(500, 450)
        self.setModal(True)
        self._center_on_parent(parent)
        self._setup_ui()

    def _center_on_parent(self, parent):
        if parent:
            px = parent.x() + (parent.width() - self.width()) // 2
            py = parent.y() + (parent.height() - self.height()) // 2
            self.move(px, py)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Bilibili Download V1.0.0")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(15)

        desc = QTextEdit()
        desc.setReadOnly(True)
        desc.setHtml(
            "<p>B站视频下载工具，支持DASH格式视频下载。</p>"
            "<p><b>功能特点:</b></p>"
            "<ul>"
            "<li>支持BV号/视频链接解析</li>"
            "<li>支持多分P视频选择下载</li>"
            "<li>支持多种画质选择</li>"
            "<li>支持二维码扫码登录</li>"
            "<li>DASH格式音视频分离下载+ffmpeg合并</li>"
            "<li>WBI签名验证</li>"
            "</ul>"
            "<p><b>依赖:</b></p>"
            "<ul>"
            "<li>PySide6 - GUI框架</li>"
            "<li>requests - HTTP请求</li>"
            "<li>qrcode + Pillow - 二维码生成</li>"
            "<li>ffmpeg - 音视频合并</li>"
            "</ul>"
            "<p>本软件仅供学习交流使用，请勿用于商业用途。</p>"
        )
        layout.addWidget(desc)

        layout.addSpacing(10)

        btn_close = QPushButton("关闭")
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignCenter)


# ============================================================
# Entry Point
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Global stylesheet
    app.setStyleSheet("""
        QMainWindow {
            background-color: #ffffff;
            color: #000000;
        }
        QWidget {
            background-color: #ffffff;
            color: #000000;
        }
        QPushButton {
            background-color: #3b82f6;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 5px 15px;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #2563eb;
        }
        QPushButton:pressed {
            background-color: #1d4ed8;
        }
        QLineEdit {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #d1d5db;
            border-radius: 4px;
            padding: 5px 8px;
            font-size: 13px;
        }
        QLineEdit:focus {
            border-color: #3b82f6;
        }
        QTableWidget {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            gridline-color: #f3f4f6;
            font-size: 13px;
        }
        QTableWidget::item {
            background-color: #ffffff;
            color: #000000;
        }
        QTableWidget::item:selected {
            background-color: #dbeafe;
            color: #1e40af;
        }
        QHeaderView::section {
            background-color: #f9fafb;
            color: #000000;
            border: none;
            border-bottom: 2px solid #e5e7eb;
            padding: 6px;
            font-weight: bold;
            font-size: 13px;
        }
        QTextEdit {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            font-size: 12px;
            font-family: Consolas, monospace;
        }
        QProgressBar {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            text-align: center;
            height: 20px;
        }
        QProgressBar::chunk {
            background-color: #3b82f6;
            border-radius: 3px;
        }
        QComboBox {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #d1d5db;
            border-radius: 4px;
            padding: 5px 8px;
            font-size: 13px;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #000000;
            selection-background-color: #dbeafe;
            selection-color: #1e40af;
        }
        QDialog {
            background-color: #ffffff;
            color: #000000;
        }
        QLabel {
            color: #000000;
            font-size: 13px;
        }
        QSplitter::handle {
            background-color: #e5e7eb;
        }
        QScrollBar:vertical {
            background-color: #f5f5f5;
            width: 10px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical {
            background-color: #c1c1c1;
            border-radius: 5px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #a8a8a8;
        }
        QScrollBar:horizontal {
            background-color: #f5f5f5;
            height: 10px;
            border-radius: 5px;
        }
        QScrollBar::handle:horizontal {
            background-color: #c1c1c1;
            border-radius: 5px;
            min-width: 20px;
        }
        QScrollBar::handle:horizontal:hover {
            background-color: #a8a8a8;
        }
        QGroupBox {
            color: #000000;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            color: #000000;
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

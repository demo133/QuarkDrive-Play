# -*- coding: utf-8 -*-
"""
QuarkPlay - 夸克网盘(OpenList) x PotPlayer 边下边播 图形客户端
- 扫描网盘视频 / 双击即播 / 常驻监听新视频自动播放
- 一键启停 OpenList 服务（无需命令行）
- 配置与数据保存在 %APPDATA%\\QuarkPlay\\
仅用 Python 标准库（tkinter + urllib），PyInstaller 打包成免安装 exe。
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import ctypes
from ctypes import wintypes
import urllib.parse
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "QuarkPlay"
APP_VER = "1.0.0"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SEEN_FILE = os.path.join(CONFIG_DIR, "seen.json")
PLAYLIST_FILE = os.path.join(CONFIG_DIR, "new-videos.m3u")
SERVICE_LOG = os.path.join(CONFIG_DIR, "service.log")
PROGRESS_FILE = os.path.join(CONFIG_DIR, "progress.json")

VIDEO_EXT = (".mp4", ".mkv", ".ts", ".m2ts", ".avi", ".mov",
             ".wmv", ".flv", ".webm", ".m4v", ".rmvb")
CREATE_NO_WINDOW = 0x08000000

DEFAULTS = {
    "openlist_url": "http://127.0.0.1:5244",
    "openlist_user": "admin",
    "openlist_pass": "",
    "openlist_exe": "C:\\openlist\\openlist.exe",
    "potplayer_exe": "C:\\Program Files\\PotPlayer\\PotPlayerMini64.exe",
    "mount_path": "/quark",
    "scan_dirs": ["/quark"],
    "poll_seconds": 60,
    "max_depth": 4,
    "autoplay": True,
    "resume_playback": True,
}


def resource_path(name):
    """PyInstaller onefile 解包目录 or 脚本目录"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def load_cfg():
    if not os.path.isdir(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULTS.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    save_cfg(DEFAULTS)
    return dict(DEFAULTS)


def save_cfg(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0


def short_time(s):
    if not s:
        return ""
    return s.replace("T", " ")[:19]


def fmt_pos(sec):
    sec = max(0, int(sec))
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def load_progress():
    """读取播放进度库 {视频路径: {pos, updated}}；损坏/不存在返回空。"""
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_progress(d):
    """原子写入进度库，失败静默（不影响播放）。"""
    try:
        tmp = PROGRESS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, PROGRESS_FILE)
    except Exception:
        pass


# ---- PotPlayer 进程活动探测（用于区分"播放中 / 暂停 / 已关闭"） ----
_TH32CS_SNAPPROCESS = 0x2


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _potplayer_cpu_seconds(exe_names):
    """返回所有匹配进程的累计 CPU 时间(秒)之和；进程不存在返回 None。"""
    k32 = ctypes.windll.kernel32
    try:
        snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    except Exception:
        return None
    pids = []
    try:
        e = _PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() in exe_names:
                pids.append(e.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    if not pids:
        return None
    total = 0.0
    for pid in pids:
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            ct, et, kt, ut = (wintypes.FILETIME() for _ in range(4))
            if k32.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                   ctypes.byref(kt), ctypes.byref(ut)):
                for ft in (kt, ut):
                    total += (((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7)
        finally:
            k32.CloseHandle(h)
    return total


class OpenListClient:
    """OpenList(Alist) API 封装，仅标准库"""

    def __init__(self, cfg):
        self.cfg = cfg

    def _post(self, path, body, token=None, timeout=20):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = token
        url = self.cfg["openlist_url"].rstrip("/") + path
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def ping(self):
        url = self.cfg["openlist_url"].rstrip("/") + "/ping"
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200

    def login(self):
        r = self._post("/api/auth/login", {
            "username": self.cfg["openlist_user"],
            "password": self.cfg["openlist_pass"]})
        if r.get("code") != 200:
            raise RuntimeError("登录失败: %s" % r.get("message"))
        return r["data"]["token"]

    def list_dir(self, token, path, refresh=False):
        r = self._post("/api/fs/list",
                       {"path": path, "page": 1, "per_page": 0,
                        "refresh": refresh}, token)
        if r.get("code") != 200:
            raise RuntimeError(r.get("message") or "list failed")
        return r["data"]["content"] or []

    def walk(self, token, path, depth, out, log):
        if depth > int(self.cfg["max_depth"]):
            return
        try:
            items = self.list_dir(token, path, False)
        except Exception:
            try:
                items = self.list_dir(token, path, True)
            except Exception as e:
                log("跳过目录 %s : %s" % (path, e))
                return
        for it in items:
            child = path.rstrip("/") + "/" + it["name"]
            if it.get("is_dir"):
                self.walk(token, child, depth + 1, out, log)
            else:
                ext = os.path.splitext(it["name"])[1].lower()
                if ext in VIDEO_EXT:
                    out.append({
                        "path": child,
                        "name": it["name"],
                        "size": int(it.get("size") or 0),
                        "mtime": it.get("modified") or "",
                        "sign": it.get("sign") or "",
                    })

    def play_url(self, item):
        # /d/ 直链必须带完整路径（含挂载路径），否则 401
        p = item["path"]
        if not p.startswith("/"):
            p = "/" + p
        enc = "/".join(urllib.parse.quote(seg) for seg in p.split("/"))
        url = self.cfg["openlist_url"].rstrip("/") + "/d" + enc
        if item.get("sign"):
            url += "?sign=" + urllib.parse.quote(item["sign"])
        return url


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_cfg()
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.items = []
        self.svc_proc = None
        self.svc_log_fh = None
        self.watch_stop = threading.Event()
        self.watch_thread = None
        self.scanning = False
        self.progress = load_progress()
        self._sess = None                 # 当前播放会话（结构见 play_item/_progress_loop）
        self._resume_flash_id = None      # 状态栏提示恢复定时器
        self._progress_stop = threading.Event()
        threading.Thread(target=self._progress_loop, daemon=True).start()

        root.title("%s v%s - 夸克网盘边下边播" % (APP_NAME, APP_VER))
        root.geometry("880x620")
        root.minsize(760, 520)
        try:
            root.iconbitmap(resource_path("icon.ico"))
        except Exception:
            pass

        self._build_ui()
        self._load_settings()
        self.root.after(80, self._drain)
        self._kick_ping()
        self.root.after(500, self._auto_start_service)

    # ---------------- UI ----------------
    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- Tab 1: 视频库 ----
        tab1 = ttk.Frame(nb)
        nb.add(tab1, text=" 视频库 ")

        bar = ttk.Frame(tab1)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        self.btn_scan = ttk.Button(bar, text="▶ 立即扫描", command=self.start_scan)
        self.btn_scan.pack(side="left")
        self.var_watch = tk.BooleanVar(value=False)
        self.chk_watch = ttk.Checkbutton(
            bar, text="自动监听新视频并播放", variable=self.var_watch,
            command=self.toggle_watch)
        self.chk_watch.pack(side="left", padx=12)
        self.var_autoplay = tk.BooleanVar(value=bool(self.cfg.get("autoplay", True)))
        ttk.Checkbutton(bar, text="发现新视频自动播放",
                        variable=self.var_autoplay).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=12, pady=2)
        self.lbl_svc = ttk.Label(bar, text="● 服务状态检测中…")
        self.lbl_svc.pack(side="left")
        self.btn_svc = ttk.Button(bar, text="启动 OpenList", command=self.svc_toggle)
        self.btn_svc.pack(side="left", padx=8)
        self.svc_running = None

        frame = ttk.Frame(tab1)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("name", "size", "mtime", "prog")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings")
        for cid, txt, w, anchor in (
                ("name", "文件名", 300, "w"),
                ("size", "大小", 90, "e"),
                ("mtime", "修改时间", 150, "center"),
                ("prog", "上次看到", 110, "center")):
            self.tree.heading(cid, text=txt)
            self.tree.column(cid, width=w, anchor=anchor)
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.on_play)
        self.tree.bind("<Button-3>", self.on_tree_menu)

        # 右键菜单：续播 / 从头播放 / 清除进度
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="▶ 播放（自动续播）", command=lambda: self._menu_action("play"))
        self.menu.add_command(label="⏮ 从头播放", command=lambda: self._menu_action("restart"))
        self.menu.add_separator()
        self.menu.add_command(label="✕ 清除本片进度记录", command=lambda: self._menu_action("clear"))

        self.lbl_stat = ttk.Label(tab1, text="共 0 个视频 · 双击任意一行即可调用 PotPlayer 播放")
        self.lbl_stat.pack(fill="x", padx=10, pady=(0, 6))

        # ---- Tab 2: 设置 ----
        tab2 = ttk.Frame(nb)
        nb.add(tab2, text=" 设置 ")
        self.entries = {}
        rows = [
            ("OpenList 地址", "openlist_url", 40),
            ("账号", "openlist_user", 20),
            ("密码", "openlist_pass", 20),
            ("OpenList 程序路径 (openlist.exe)", "openlist_exe", 52),
            ("PotPlayer 程序路径", "potplayer_exe", 52),
            ("挂载路径", "mount_path", 14),
            ("扫描目录 (逗号分隔)", "scan_dirs", 40),
            ("监听轮询间隔 (秒)", "poll_seconds", 8),
            ("目录递归深度", "max_depth", 6),
        ]
        for i, (label, key, w) in enumerate(rows):
            ttk.Label(tab2, text=label).grid(
                row=i, column=0, sticky="e", padx=(14, 6), pady=5)
            e = ttk.Entry(tab2, width=w)
            if key == "openlist_pass":
                e.configure(show="*")
            e.grid(row=i, column=1, sticky="w", pady=5)
            self.entries[key] = e
            if key == "openlist_exe":
                ttk.Button(tab2, text="浏览…", width=6,
                           command=lambda k=key: self._browse(k, False)
                           ).grid(row=i, column=2, padx=6)
            if key == "potplayer_exe":
                ttk.Button(tab2, text="浏览…", width=6,
                           command=lambda k=key: self._browse(k, True)
                           ).grid(row=i, column=2, padx=6)
        self.chk_auto_cfg = tk.BooleanVar(value=bool(self.cfg.get("autoplay", True)))
        ttk.Checkbutton(tab2, text="发现新视频时自动播放",
                        variable=self.chk_auto_cfg).grid(
            row=len(rows), column=1, sticky="w", pady=8)
        self.chk_resume_cfg = tk.BooleanVar(value=bool(self.cfg.get("resume_playback", True)))
        ttk.Checkbutton(tab2, text="记住播放进度（打开同一视频自动续播）",
                        variable=self.chk_resume_cfg).grid(
            row=len(rows) + 1, column=1, sticky="w", pady=2)
        ttk.Button(tab2, text="保存设置", command=self.save_settings).grid(
            row=len(rows) + 2, column=1, sticky="w", pady=6)
        ttk.Label(tab2, text="配置与数据目录: " + CONFIG_DIR, foreground="#666").grid(
            row=len(rows) + 3, column=0, columnspan=3, sticky="w", padx=14, pady=10)

        # ---- Tab 3: 日志 ----
        tab3 = ttk.Frame(nb)
        nb.add(tab3, text=" 日志 ")
        self.txt = tk.Text(tab3, wrap="none", state="disabled",
                           font=("Consolas", 9))
        vs3 = ttk.Scrollbar(tab3, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=vs3.set)
        self.txt.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        vs3.pack(side="right", fill="y", pady=8)

    def _browse(self, key, exe_filter):
        p = filedialog.askopenfilename(
            filetypes=[("程序", "*.exe") if exe_filter else ("全部", "*.*")])
        if p:
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, p)

    def _load_settings(self):
        for k, e in self.entries.items():
            v = self.cfg.get(k, "")
            if k == "scan_dirs":
                v = ", ".join(v if isinstance(v, list) else [v])
            e.delete(0, "end")
            e.insert(0, str(v))
        self.chk_auto_cfg.set(bool(self.cfg.get("autoplay", True)))
        self.chk_resume_cfg.set(bool(self.cfg.get("resume_playback", True)))
        self.log("欢迎使用 %s v%s" % (APP_NAME, APP_VER))
        self.log("配置目录: " + CONFIG_DIR)
        self.log("提示：先点「启动 OpenList」(或确认服务已运行)，再点「立即扫描」。")

    # ---------------- 工具 ----------------
    def log(self, msg):
        self.q.put(("log", "[%s] %s" % (time.strftime("%H:%M:%S"), msg)))

    def get_cfg_from_ui(self):
        cfg = dict(self.cfg)
        for k, e in self.entries.items():
            v = e.get().strip()
            if k == "scan_dirs":
                v = [x.strip() for x in v.split(",") if x.strip()]
            elif k in ("poll_seconds", "max_depth"):
                try:
                    v = max(1, int(v))
                except ValueError:
                    v = int(DEFAULTS[k])
            cfg[k] = v
        cfg["autoplay"] = bool(self.chk_auto_cfg.get())
        cfg["resume_playback"] = bool(self.chk_resume_cfg.get())
        return cfg

    def save_settings(self):
        self.cfg = self.get_cfg_from_ui()
        try:
            save_cfg(self.cfg)
            self.log("设置已保存到 " + CONFIG_FILE)
        except Exception as e:
            self.log("设置保存失败: %s" % e)
            messagebox.showerror(APP_NAME, "设置保存失败：\n%s" % e)
            return
        if self.var_watch.get():
            self.log("提示：监听间隔已更新，关闭再打开「自动监听」后生效。")

    # ---------------- 扫描 ----------------
    def start_scan(self):
        if self.scanning:
            return
        self.cfg = self.get_cfg_from_ui()
        self.scanning = True
        self.btn_scan.state(["disabled"])
        self.log("开始扫描 %s …" % (", ".join(self.cfg["scan_dirs"]) or "(未配置)"))
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            cli = OpenListClient(self.cfg)
            token = cli.login()
            items = []
            for d in self.cfg["scan_dirs"]:
                if d:
                    cli.walk(token, d, 0, items, self.log)
        except Exception as e:
            self.log("扫描失败: %s" % e)
            self.q.put(("scan_done", None))
            return
        new_items, first_run = self._diff_seen(items)
        self.q.put(("videos", items))
        self.q.put(("new", new_items if not first_run else []))
        self.q.put(("scan_done", len(items)))

    def _diff_seen(self, items):
        """new = seen 里没有 或 mtime 变化。首次运行只建基线不自动播放。"""
        first_run = not os.path.exists(SEEN_FILE)
        with self.lock:
            try:
                seen = json.load(open(SEEN_FILE, encoding="utf-8"))
            except Exception:
                seen = {}
                first_run = True
            new_items = [it for it in items if seen.get(it["path"]) != it["mtime"]]
            for it in items:
                seen[it["path"]] = it["mtime"]
            with open(SEEN_FILE, "w", encoding="utf-8") as f:
                json.dump(seen, f, ensure_ascii=False)
        return new_items, first_run

    def _write_playlist(self, new_items):
        try:
            lines = ["#EXTM3U"]
            for it in new_items:
                lines.append("#EXTINF:-1," + it["name"])
                lines.append(OpenListClient(self.cfg).play_url(it))
            with open(PLAYLIST_FILE, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines))
        except Exception as e:
            self.log("播放列表写入失败: %s" % e)

    # ---------------- 监听 ----------------
    def toggle_watch(self):
        if self.var_watch.get():
            self.cfg = self.get_cfg_from_ui()
            self.watch_stop.clear()
            self.watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
            self.watch_thread.start()
            self.log("自动监听已开启，每 %s 秒扫描一次。" % self.cfg["poll_seconds"])
        else:
            self.watch_stop.set()
            self.log("自动监听已关闭。")

    def _watch_loop(self):
        while not self.watch_stop.is_set():
            if not self.scanning:
                self.q.put(("scan_request", None))
            self.watch_stop.wait(int(self.cfg["poll_seconds"]))

    # ---------------- 播放 ----------------
    def on_play(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.items[int(sel[0])]
        self.play_item(item)

    def on_tree_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    # ---------------- 播放进度记忆 ----------------
    # PotPlayer 是独立进程，拿不到真实进度条位置，因此按"确认在播的时长"推算：
    #   - 用进程 CPU 时间增量区分 播放中 / 暂停（暂停不计入）
    #   - 用进程存在性检测播放器关闭（关闭立即冻结，不再累计）
    #   - 拖动会造成固定偏差，继续观看不会放大；右键「从头播放」可重置
    def _potplayer_names(self):
        try:
            return {os.path.basename(self.cfg.get("potplayer_exe", "")).lower()}
        except Exception:
            return {"potplayermini64.exe"}

    def _write_progress(self, s):
        pos = s["start"] + s["elapsed"]
        self.progress[s["path"]] = {"pos": round(pos, 1), "updated": time.time()}
        save_progress(self.progress)

    def _freeze_session(self):
        """切换视频/退出时冻结当前会话：只累计已确认在播的时间。"""
        s = self._sess
        if not s:
            return
        try:
            cpu = _potplayer_cpu_seconds(self._potplayer_names())
            now = time.time()
            if cpu is not None and s.get("cpu_prev") is not None:
                d_cpu = max(0.0, cpu - s["cpu_prev"])
                d_wall = max(0.0, now - s["wall_prev"])
                if d_wall > 0 and d_cpu / d_wall >= 0.01:
                    s["elapsed"] += d_wall
            self._write_progress(s)
        except Exception:
            pass
        self._sess = None

    def _progress_loop(self):
        """每 10 秒核对 PotPlayer 状态并更新进度。"""
        while not self._progress_stop.wait(10):
            try:
                s = self._sess
                if not s or not self.cfg.get("resume_playback", True):
                    continue
                cpu = _potplayer_cpu_seconds(self._potplayer_names())
                now = time.time()
                if cpu is None:
                    # 播放器已关闭：冻结在最后确认的位置
                    self._write_progress(s)
                    self.log("播放器已关闭，进度已保存。")
                    self._sess = None
                    continue
                if s.get("cpu_prev") is None:
                    s["cpu_prev"], s["wall_prev"] = cpu, now
                    continue
                d_cpu = max(0.0, cpu - s["cpu_prev"])
                d_wall = max(0.0, now - s["wall_prev"])
                ratio = (d_cpu / d_wall) if d_wall > 0 else 1.0
                if ratio >= 0.01:
                    s["elapsed"] += d_wall          # 确认在播
                    s["low"] = 0
                else:
                    # 单次低 CPU 可能是缓冲，连续两个周期低 CPU 才判暂停
                    s["low"] = s.get("low", 0) + 1
                    if s["low"] < 2:
                        s["elapsed"] += d_wall
                s["cpu_prev"], s["wall_prev"] = cpu, now
                self._write_progress(s)
            except Exception:
                pass

    def _menu_action(self, action):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.items[int(sel[0])]
        if action == "play":
            self.play_item(item)
        elif action == "restart":
            self.progress.pop(item["path"], None)
            save_progress(self.progress)
            self._refresh_row_progress(item["path"])
            self.log("已清除进度，从头播放: %s" % item["name"])
            self.play_item(item, force_restart=True)
        elif action == "clear":
            self.progress.pop(item["path"], None)
            save_progress(self.progress)
            self._refresh_row_progress(item["path"])
            self.log("已清除进度记录: %s" % item["name"])

    def _refresh_row_progress(self, path):
        for i, it in enumerate(self.items):
            if it["path"] == path:
                rec = self.progress.get(path) or {}
                pos = float(rec.get("pos") or 0)
                val = fmt_pos(pos) if pos >= 5 else ""
                try:
                    self.tree.set(str(i), "prog", val)
                except Exception:
                    pass
                break

    def play_item(self, item, force_restart=False):
        exe = self.cfg.get("potplayer_exe", "")
        if not os.path.exists(exe):
            self.log("找不到 PotPlayer: %s ，请到「设置」修改路径。" % exe)
            messagebox.showwarning(APP_NAME, "找不到 PotPlayer：\n%s\n请到「设置」修改路径。" % exe)
            return
        url = OpenListClient(self.cfg).play_url(item)
        key = item["path"]
        resume_on = bool(self.cfg.get("resume_playback", True))
        pos = 0.0
        if force_restart:
            self.progress.pop(key, None)
            save_progress(self.progress)
            self._refresh_row_progress(key)
        elif resume_on:
            try:
                pos = float((self.progress.get(key) or {}).get("pos") or 0)
            except Exception:
                pos = 0.0
        if pos < 5:            # 无记录/几乎没看/手动重头 → 从头
            pos = 0.0
        args = [exe]
        if pos > 0:
            args.append("/seek=" + fmt_pos(pos))
        args.append(url)
        try:
            subprocess.Popen(args, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.log("播放失败: %s" % e)
            return
        # 新会话开始，冻结上一会话
        self._freeze_session()
        self._sess = {"path": key, "start": pos, "elapsed": 0.0,
                      "cpu_prev": None, "wall_prev": time.time()}
        if pos > 0:
            self.log("▶ 已恢复到上次播放位置 %s : %s" % (fmt_pos(pos), item["name"]))
            self.q.put(("resume", {"pos": pos, "name": item["name"]}))
        else:
            self.log("已调用 PotPlayer 播放: %s" % item["name"])
            self._refresh_row_progress(key)

    # ---------------- OpenList 服务 ----------------
    def svc_toggle(self):
        if self.svc_proc and self.svc_proc.poll() is None:
            self.svc_stop()
        else:
            self.svc_start()

    def svc_start(self):
        exe = self.cfg.get("openlist_exe", "")
        if not os.path.exists(exe):
            messagebox.showwarning(APP_NAME, "找不到 openlist.exe：\n%s\n请到「设置」修改路径。" % exe)
            return
        if self.svc_proc and self.svc_proc.poll() is None:
            self.log("OpenList 已在运行。")
            return
        self.btn_svc.state(["disabled"])
        self.log("正在启动 OpenList …")
        threading.Thread(target=self._svc_start_worker, daemon=True).start()

    def _svc_start_worker(self):
        ok = self._launch_and_wait(OpenListClient(self.cfg), wait_seconds=12)
        ts = time.strftime("%H:%M:%S")
        if ok:
            self.q.put(("log", "[%s] OpenList 启动成功。日志: %s" % (ts, SERVICE_LOG)))
        else:
            self.q.put(("log", "[%s] OpenList 启动失败或超时，请查看 %s" % (ts, SERVICE_LOG)))
        self.q.put(("svc_done", None))

    def _launch_and_wait(self, cli, wait_seconds=12):
        """启动 OpenList 进程并轮询 /ping 等待就绪，返回是否就绪。"""
        try:
            if self.svc_proc and self.svc_proc.poll() is None:
                self.svc_proc.terminate()
                try:
                    self.svc_proc.wait(timeout=5)
                except Exception:
                    self.svc_proc.kill()
                time.sleep(1)
            self.svc_log_fh = open(SERVICE_LOG, "ab")
            exe = self.cfg.get("openlist_exe", "")
            self.svc_proc = subprocess.Popen(
                [exe, "server"], cwd=os.path.dirname(exe) or ".",
                stdout=self.svc_log_fh, stderr=self.svc_log_fh,
                creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.q.put(("log", "[%s] 启动 OpenList 出错: %s" % (time.strftime("%H:%M:%S"), e)))
            return False
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                if cli.ping():
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    # ---------------- 打开软件时自动启动 OpenList ----------------
    def _auto_start_service(self):
        """软件打开后自动拉起 OpenList；已在运行则跳过，失败自动重试。"""
        if self.svc_proc and self.svc_proc.poll() is None:
            return
        exe = self.cfg.get("openlist_exe", "")
        if not exe or not os.path.exists(exe):
            self.log("未找到 openlist.exe，跳过自动启动（请在「设置」填写路径后手动启动）。")
            return
        threading.Thread(target=self._auto_start_worker, daemon=True).start()

    def _auto_start_worker(self):
        cli = OpenListClient(self.cfg)
        try:
            if cli.ping():
                self.log("检测到 OpenList 已在运行，无需自动启动。")
                return
        except Exception:
            pass
        for attempt in (1, 2, 3):
            self.log("OpenList 未运行，自动启动中…（第 %d/3 次）" % attempt)
            if self._launch_and_wait(cli, wait_seconds=12):
                self.log("OpenList 自动启动成功。")
                return
            if attempt < 3:
                time.sleep(3)
        self.q.put(("svc_fail", None))
        self.log("OpenList 自动启动失败（已重试 3 次）。可查看 %s 排查原因，"
                 "或在「视频库」页点「启动 OpenList」手动重试。" % SERVICE_LOG)

    def svc_stop(self):
        if self.svc_proc and self.svc_proc.poll() is None:
            self.svc_proc.terminate()
            try:
                self.svc_proc.wait(timeout=5)
            except Exception:
                self.svc_proc.kill()
            self.log("OpenList 已停止。")
        else:
            self.log("OpenList 不是由本程序启动的，请在对应窗口停止。")

    def _kick_ping(self):
        threading.Thread(target=self._ping_worker, daemon=True).start()

    def _ping_worker(self):
        while True:
            ok = False
            try:
                ok = OpenListClient(self.cfg).ping()
            except Exception:
                ok = False
            self.q.put(("svc", ok))
            time.sleep(5)

    # ---------------- 队列 → UI ----------------
    def _drain(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.txt.configure(state="normal")
                    self.txt.insert("end", data + "\n")
                    if int(self.txt.index("end-1c").split(".")[0]) > 800:
                        self.txt.delete("1.0", "200.0")
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
                elif kind == "videos":
                    self._fill_tree(data)
                elif kind == "new":
                    if data:
                        self._write_playlist(data)
                        self.log("发现 %d 个新视频，播放列表已更新。" % len(data))
                        if self.var_watch.get() and self.var_autoplay.get():
                            self.log("自动播放最新: " + data[0]["name"])
                            self.play_item(data[0])
                elif kind == "scan_done":
                    self.scanning = False
                    self.btn_scan.state(["!disabled"])
                    if data is not None:
                        self.lbl_stat.configure(
                            text="共 %d 个视频 · 双击任意一行即可调用 PotPlayer 播放" % data)
                elif kind == "resume":
                    msg = "▶ 已恢复到上次播放位置 %s · %s" % (fmt_pos(data["pos"]), data["name"])
                    if self._resume_flash_id:
                        try:
                            self.root.after_cancel(self._resume_flash_id)
                        except Exception:
                            pass
                    self.lbl_stat.configure(text=msg, foreground="#f26614")
                    self._resume_flash_id = self.root.after(
                        8000, lambda: self.lbl_stat.configure(
                            text="共 %d 个视频 · 双击任意一行即可调用 PotPlayer 播放" % len(self.items),
                            foreground="#000000"))
                elif kind == "scan_request":
                    self.start_scan()
                elif kind == "svc_done":
                    self.btn_svc.state(["!disabled"])
                elif kind == "svc_fail":
                    self.btn_svc.state(["!disabled"])
                    self.lbl_svc.configure(text="● OpenList 启动失败", foreground="#c0564a")
                elif kind == "svc":
                    if data != self.svc_running or True:
                        self.svc_running = data
                        if data:
                            self.lbl_svc.configure(text="● OpenList 运行中", foreground="#1a7f37")
                            self.btn_svc.configure(text="停止 OpenList")
                        else:
                            self.lbl_svc.configure(text="● OpenList 未运行", foreground="#999")
                            self.btn_svc.configure(text="启动 OpenList")
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _fill_tree(self, items):
        self.items = sorted(items, key=lambda x: x["mtime"], reverse=True)
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            rec = self.progress.get(it["path"]) or {}
            try:
                pos = float(rec.get("pos") or 0)
            except Exception:
                pos = 0.0
            prog = fmt_pos(pos) if pos >= 5 else ""
            self.tree.insert("", "end", iid=str(i), values=(
                it["name"], human_size(it["size"]),
                short_time(it["mtime"]), prog))

    def on_close(self):
        self.watch_stop.set()
        self._progress_stop.set()
        self._freeze_session()   # 保存播放进度
        if self.svc_proc and self.svc_proc.poll() is None:
            ans = messagebox.askyesnocancel(
                APP_NAME,
                "OpenList 正在由本程序启动运行。\n\n"
                "「是」— 退出并停止 OpenList\n"
                "「否」— 退出但保持 OpenList 运行（PotPlayer 可继续播放）\n"
                "「取消」— 返回程序")
            if ans is None:
                return
            if ans:
                self.svc_stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()

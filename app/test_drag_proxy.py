# -*- coding: utf-8 -*-
"""拖动进度条识别（本地字节级代理）mock 测试。不依赖 PotPlayer / OpenList。"""
import json
import os
import sys
import time
import threading
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as appmod

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + ("  " + detail if detail else ""))


# ---------- Part 1: _RangeProxy 转发 + offset 上报 ----------
DATA = bytes(range(256)) * 4096          # 1 MB 假视频
UP_offsets = []

class Up(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        rng = self.headers.get("Range")
        start, end = 0, len(DATA) - 1
        status = 200
        if rng:
            m = __import__("re").match(r"bytes=(\d+)-(\d*)", rng.strip())
            start = int(m.group(1))
            if m.group(2):
                end = int(m.group(2))
            status = 206
        UP_offsets.append(start)
        body = DATA[start:end + 1]
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        if rng:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, len(DATA)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)

up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
threading.Thread(target=up.serve_forever, daemon=True).start()
up_url = "http://127.0.0.1:%d/file.mp4" % up.server_address[1]

got = []
pr = appmod._RangeProxy(lambda t, o, s: got.append((t, o, s)))
pr.start()
pr.streams["tok1"] = {"url": up_url, "size": len(DATA), "refresh": lambda: up_url}

print("[Part1] _RangeProxy 转发")
r = urllib.request.urlopen("http://127.0.0.1:%d/p/tok1" % pr.port, timeout=10)
full = r.read(); r.close()
check("全量请求返回 200+完整内容", r.status == 200 and len(full) == len(DATA) and full[:16] == DATA[:16])
check("全量请求 offset=0 上报", got and got[-1] == ("tok1", 0, len(DATA)))

req = urllib.request.Request("http://127.0.0.1:%d/p/tok1" % pr.port,
                             headers={"Range": "bytes=524288-"})
r = urllib.request.urlopen(req, timeout=10)
part = r.read(); r.close()
check("Range 请求返回 206+正确切片",
      r.status == 206 and part == DATA[524288:])
check("Range 请求 offset=524288 上报", got[-1] == ("tok1", 524288, len(DATA)))

# ---------- Part 2: _on_range 拖动识别逻辑（stub App） ----------
print("[Part2] 拖动识别逻辑")
A = appmod.App.__new__(appmod.App)
A.cfg = {"resume_playback": True, "potplayer_exe": "PotPlayerMini64.exe"}
A.lock = threading.Lock()
A.q = __import__("queue").Queue()
A.progress = {}
logs = []
A.log = lambda m: logs.append(m)
appmod.save_progress = lambda d: None          # 不写真实文件
appmod._potplayer_cpu_seconds = lambda names: 0.0

SIZE = 2 * 1024 * 1024 * 1024                  # 2GB
BR = 300000.0                                  # 300KB/s

def new_sess(t0=None, start=0.0, br=BR):
    A._sess = {"path": "/quark/v.mp4", "start": start, "elapsed": 0.0,
               "cpu_prev": None, "wall_prev": time.time(), "ratios": [],
               "token": "T", "name": "v.mp4", "size": SIZE,
               "byte": None, "seg_byte0": None, "seg_sec0": start,
               "bitrate": br, "t0": t0 if t0 is not None else time.time()}
    return A._sess

def rng(off, size=SIZE):
    A._on_range("T", off, size)

# 场景1：从零开播（过宽限期后），顺序小块前进 → 不误判拖动
s = new_sess(t0=time.time() - 30)
rng(0); rng(1048576); rng(2097152)
check("场景1 从头顺序播放不误判", s["start"] == 0.0 and s["seg_byte0"] == 0, "start=%s" % s["start"])

# 场景2：续播 /seek=T，前 10 秒内 0 → seek 落点 只锚定不拖动
s = new_sess(start=1800.0)
rng(0); rng(int(1800 * BR)); rng(int(1800 * BR) + 1048576)
check("场景2 seek 落点只锚定", s["start"] == 1800.0 and s["elapsed"] == 0.0
      and s["seg_byte0"] == int(1800 * BR) + 1048576, "seg_byte0=%s" % s["seg_byte0"])

# 场景3：宽限期后拖动 → 位置 = seg_sec0 + (offset-b0)/bitrate
s = new_sess(t0=time.time() - 30, start=1800.0)
anchor = int(1800 * BR)
rng(anchor); s["elapsed"] = 25.0; s["byte"] = anchor + int(25 * BR)
drag_to = int(3600 * BR)                       # 拖到约 1 小时处
rng(drag_to)
expect = 1800.0 + (drag_to - anchor) / BR
check("场景3 拖动位置按码率换算", abs(s["start"] - expect) < 1.0,
      "got=%.1f expect=%.1f" % (s["start"], expect))
check("场景3 拖动后锚点/时长复位", s["elapsed"] == 0.0 and s["seg_byte0"] == drag_to
      and abs(s["seg_sec0"] - expect) < 1.0)
check("场景3 记录已写入 progress 库", abs(A.progress["/quark/v.mp4"]["pos"] - expect) < 1.0)
check("场景3 拖动事件入队", A.q.qsize() >= 1 and A.q.get_nowait()[0] == "seeked")

# 场景4：mkv 片尾索引读取（宽限期后大跳到 >98%）不误判拖动
s = new_sess(t0=time.time() - 30)
rng(0); rng(1048576)
tail = int(SIZE * 0.995)
rng(tail)
check("场景4 片尾索引读取被忽略", s["start"] == 0.0 and s["seg_byte0"] == 0,
      "seg_byte0=%s" % s["seg_byte0"])

# 场景5：顺序播到 97% 以后 → 看完清零（4MB 一小块顺序前进）
s = new_sess(t0=time.time() - 30)
rng(0); s["elapsed"] = 90.0
o = 4 * 1024 * 1024
while o <= int(SIZE * 0.975):
    rng(o)
    o += 4 * 1024 * 1024
check("场景5 顺序播完记录清零", s["start"] == 0.0 and s["elapsed"] == 0.0)
check("场景5 看完日志", any("播完" in m for m in logs))

# 场景6：token 不匹配（旧会话）忽略
s = new_sess()
A._sess = s
A._on_range("OTHER", 123456789, SIZE)
check("场景6 token 不匹配忽略", s["byte"] is None)

# 场景7：无码率记录时用 观测字节/时长 现场换算
s = new_sess(t0=time.time() - 30, br=0.0)      # 首次播放无历史码率
rng(0); s["elapsed"] = 30.0; s["byte"] = int(30 * 250000)
rng(int(30 * 250000) + 1048576)                # 顺序前进(1MB<2MB阈值)，锚点不变
seq_byte = int(30 * 250000) + 1048576
inst = seq_byte / 30.0                         # 现场码率 = 已播字节/确认时长
drag2 = 100 * 1024 * 1024                      # 拖到 100MB 处（跳变 > 阈值）
rng(drag2)
check("场景7 现场码率换算拖动位置", abs(s["start"] - drag2 / inst) < 2.0,
      "got=%.1f expect=%.1f" % (s["start"], drag2 / inst))

# 场景8：_write_progress 携带码率
s["bitrate"] = 123456.0
appmod.save_progress = lambda d: json.dumps(d)
A._write_progress(s)
check("场景8 进度记录含码率字段", A.progress["/quark/v.mp4"].get("bitrate") == 123456.0)

up.shutdown()
print("\n%d PASS / %d FAIL" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)

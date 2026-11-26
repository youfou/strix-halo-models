#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strix Halo 395 (128GB) 模型批量下载脚本 —— 在 macOS 或 Ubuntu 上运行，
下载 16 个 llama.cpp 模型 + Halogen 的 Qwen 3.8 Flash Next（.hgn）到模型盘，给 395 跑 llama.cpp 与 Halogen 用。

特性：
  * 多线程下载：aria2c，默认每文件 16 连接 / 16 分段
  * 断点续传：aria2c 控制文件（块级）+ 已完成文件按大小跳过；
    Ctrl+C 随时停，重新运行自动继续
  * 无限重试：aria2c 每次最多 5 次，脚本层面无限重试，自动换镜像
  * 超时规则：有速度时不设超时；持续 0 速 180 秒则终止本次尝试并重试
  * 镜像优先：ModelScope（国内官方/镜像）> hf-mirror > huggingface.co，
    每次尝试前实测挑通的；全程走国内镜像可省代理流量
  * 进度显示：每 5 秒刷新当前模型、速度、本模型进度、总体进度和剩余时间；
    进度和速度取自 aria2 RPC 的真实已下载字节，不用文件体积——多分段
    是乱序写盘，文件体积是写到的最大偏移，会虚高（最后一段一开始写，
    体积就接近满格）
  * 日志：控制台 + 日志文件双份，aria2c 的详细日志单独存一份

用法（macOS）：
  python3 download-models.py --dest /Volumes/llms/models
  python3 download-models.py --dest /Volumes/llms/models --dry-run
  python3 download-models.py --dest /Volumes/llms/models --only qwen3-8b
  python3 download-models.py --dest /Volumes/llms/models --connections 8
用法（Ubuntu，把 --dest 换成挂载点，例如 /mnt/llms/models）：
  python3 download-models.py --dest /mnt/llms/models

依赖：aria2c（macOS：brew install aria2；Ubuntu：sudo apt install aria2）、
  Python 3（macOS 自带，Ubuntu 预装）。
环境变量（可选）：HF_TOKEN —— 仅在个别仓库要求授权时才需要，
  本清单里的仓库目前全部公开，正常不需要。

注意：脚本按 manifest.json（同目录）下载，清单在 2026-11-26 核实：
  43 个文件，共 905.16 GB。（2026-11-27 删 MiniMax M2.5 与 Qwen2.5-Coder-32B，腾 163.94GB；同日加 Halogen 的 Qwen 3.8 Flash Next，10 个文件、120.30GB：主模型 v2.hgn 66.69GB + n-gram 表 51.20GB + draft head 1.49GB + vision 0.90GB + tokenizer/ 6 个小文件。注意：下载脚本把文件扁平化存到 <dest>/<slug>/<basename>，tokenizer/ 下的 6 个文件会落在模型目录根部，部署 Halogen 前需手动把它们移进 tokenizer/ 子目录，见 README。）
"""

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

STALL_SECONDS = 180      # 持续 0 速超过这么久，终止本次尝试并重试
POLL_SECONDS = 5         # 进度刷新间隔（秒）
ARIA_TRIES = 5           # aria2c 单次调用内的重试次数
ARIA_RETRY_WAIT = 10     # aria2c 两次重试之间的等待（秒）
RETRY_WAIT = 10          # 脚本层面两次尝试之间的等待（秒）
MIRROR_RETRY_WAIT = 60   # 所有镜像都不可用时的等待（秒）

LOG_FP = None
STATUS_ACTIVE = False
STOP_REQUESTED = False
CHILD_PROC = None


# ---------------------------------------------------------------- 日志
def log(msg):
    """写一行带时间戳的日志：控制台 + 日志文件。"""
    global STATUS_ACTIVE
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    if STATUS_ACTIVE:
        sys.stdout.write("\n")
        STATUS_ACTIVE = False
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    if LOG_FP is not None:
        LOG_FP.write(line + "\n")
        LOG_FP.flush()


def fmt_gb(nbytes):
    """按大小自动选单位：B / KB / MB / GB。"""
    if nbytes >= 1e9:
        return "%.1fGB" % (nbytes / 1e9)
    if nbytes >= 1e6:
        return "%.1fMB" % (nbytes / 1e6)
    if nbytes >= 1e3:
        return "%.0fKB" % (nbytes / 1e3)
    return "%dB" % nbytes


def fmt_speed(bps):
    if bps >= 1e6:
        return "%.1f MB/s" % (bps / 1e6)
    if bps >= 1e3:
        return "%.0f KB/s" % (bps / 1e3)
    return "%.0f B/s" % bps


def fmt_eta(seconds):
    if seconds is None or seconds < 0:
        return "--"
    seconds = int(seconds)
    h, m = seconds // 3600, (seconds % 3600) // 60
    if h > 0:
        return "%dh%02dm" % (h, m)
    if m > 0:
        return "%dm" % m
    return "%ds" % seconds


def interruptible_sleep(seconds):
    """可被 Ctrl+C 打断的 sleep。"""
    end = time.time() + seconds
    while time.time() < end:
        if STOP_REQUESTED:
            return
        time.sleep(min(1.0, end - time.time()))


# ---------------------------------------------------------------- 信号
def _on_signal(signum, frame):
    global STOP_REQUESTED, CHILD_PROC
    STOP_REQUESTED = True
    if CHILD_PROC is not None and CHILD_PROC.poll() is None:
        try:
            CHILD_PROC.terminate()
        except Exception:
            pass


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


# ---------------------------------------------------------------- 镜像
def build_urls(repo, path):
    """按优先顺序返回候选 URL 列表：(source, url)。"""
    q = urllib.parse.quote(path, safe="/")
    return [
        ("modelscope", "https://modelscope.cn/models/%s/resolve/master/%s" % (repo, q)),
        ("hf-mirror", "https://hf-mirror.com/%s/resolve/main/%s" % (repo, q)),
        ("huggingface", "https://huggingface.co/%s/resolve/main/%s" % (repo, q)),
    ]


def probe(url, token=None):
    """1KB Range 探测：返回 True 表示该 URL 现在能断点续传下载。"""
    headers = {"User-Agent": "model-downloader/1.0", "Range": "bytes=0-1023"}
    if token and ("huggingface.co" in url or "hf-mirror.com" in url):
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
            return r.status in (200, 206)
    except Exception:
        return False


def pick_url(model, fname, token):
    """按 manifest 的实测标记排序候选，逐个探测，返回 (source, url)。"""
    cands = build_urls(model["repo"], fname["path"])
    # 明确标为 False 的镜像跳过；标记缺失时照常尝试（老 manifest 也能跑）
    order = []
    if fname.get("modelscope_ok") is not False:
        order.append(cands[0])
    if fname.get("hfmirror_ok") is not False:
        order.append(cands[1])
    order.append(cands[2])
    seen = set()
    for source, url in order:
        if url in seen:
            continue
        seen.add(url)
        if probe(url, token):
            return source, url
    return None, None


# ---------------------------------------------------------------- 进度
class Tracker:
    """从磁盘实际大小统计总体进度，并算滚动速度 / ETA。"""

    def __init__(self, models, dest):
        self.models = models
        self.dest = dest
        self.total = sum(m["size"] for m in models)
        self.samples = deque(maxlen=13)  # 约 60 秒窗口（每 5 秒一个样本）
        self.started = time.time()
        self.current = None  # (slug, basename, 真实已下载字节)，当前在下文件
        # 以启动时已下载的字节数为基线，避免把断点续传前已有的部分
        # 算成“本轮刚下载的”，否则刚启动时速度会被虚报几百 MB/s
        self.samples.append((self.started, self.downloaded()))

    def downloaded(self):
        return sum(self._file_done(m, f)
                   for m in self.models for f in m["files"])

    def _file_done(self, model, f):
        """单个文件真实已下载字节。当前在下载的文件以 aria2 RPC 的
        completedLength 为准（set_current 写入），其余用文件体积。
        不用文件体积量当前文件，是因为多分段乱序写盘：文件体积是写到
        的最大偏移，最后一段一开始写体积就接近满格，会虚高几十倍。"""
        base = os.path.basename(f["path"])
        if (self.current is not None
                and self.current[0] == model["slug"]
                and self.current[1] == base):
            return min(self.current[2], f["size"])
        p = os.path.join(self.dest, model["slug"], base)
        try:
            return min(os.path.getsize(p), f["size"])
        except OSError:
            return 0

    def set_current(self, slug, basename, done_bytes):
        """记录当前在下载文件的真实已下载字节（aria2 RPC 的值）。"""
        self.current = (slug, basename, max(0, done_bytes))

    def clear_current(self):
        self.current = None

    def model_done(self, model):
        """本模型真实已下载字节（当前文件用 RPC 值，其余用文件体积）。"""
        return sum(self._file_done(model, f) for f in model["files"])

    def sample(self):
        now = time.time()
        self.samples.append((now, self.downloaded()))
        return self.downloaded()

    def speed(self):
        # 只用窗口内的增量算速度；样本不足时返回 0，不用“总量/总时间”
        # 估算（那会把断点续传前已有的字节也算进去）
        if len(self.samples) >= 2:
            (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
            if t1 > t0:
                return max(0.0, (b1 - b0) / (t1 - t0))
        return 0.0

    def eta(self):
        s = self.speed()
        if s <= 0:
            return None
        return (self.total - self.downloaded()) / s


def pick_rpc_port():
    """挑一个本机空闲端口给 aria2 RPC 用（每次调用换一个，避免复用冲突）。"""
    for _ in range(20):
        port = secrets.randbelow(30000) + 20000  # 20000–49999
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            continue
    return 6800


def rpc_status(port, secret):
    """问 aria2 RPC 要当前下载的真实进度。
    返回 (completedLength, downloadSpeed)，单位字节；问不到返回 (None, None)。
    completedLength 是真正写盘的字节数，不受多分段乱序写盘影响；
    文件体积（st_size）是写到的最大偏移，会虚高。"""
    body = json.dumps({
        "jsonrpc": "2.0", "id": "dl",
        "method": "aria2.tellActive",
        "params": ["token:%s" % secret],
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/jsonrpc" % port, data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None, None
    try:
        item = data["result"][0]
        return int(item["completedLength"]), int(item["downloadSpeed"])
    except Exception:
        return None, None


def rpc_shutdown(port, secret):
    """让开着 RPC 的 aria2 干净退出。aria2 开 RPC 后下完不会自己退出，
    会一直等着当服务器，不调 shutdown 的话脚本会一直等它。"""
    body = json.dumps({
        "jsonrpc": "2.0", "id": "sd",
        "method": "aria2.shutdown",
        "params": ["token:%s" % secret],
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/jsonrpc" % port, data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 单文件下载
def file_state(path, expected):
    """返回文件当前状态。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "missing"
    if size == expected:
        # 体积满格还不能算完成：多分段乱序写盘时，最后一段一写体积就
        # 接近满格，但中间可能全是空洞；只有 aria2 控制文件也被删掉
        # （aria2 只在真正下完并校验通过后才删）才算完成，否则按断点续传。
        if os.path.exists(path + ".aria2"):
            return "partial"
        return "done"
    if size > expected:
        return "oversize"
    ctl = path + ".aria2"
    if os.path.exists(ctl):
        return "partial"
    return "partial-noctl"


def run_aria2c(url, source, dest_dir, fname, sha256, token, log_dir,
               connections, tracker, model, model_index, model_count):
    """跑一次 aria2c 下载一个文件，带进度显示和 180 秒零速保护。
    返回 (ok, reason)。"""
    global CHILD_PROC, STATUS_ACTIVE
    basename = os.path.basename(fname["path"])
    target = os.path.join(dest_dir, basename)
    aria_log = os.path.join(
        log_dir, "aria2-%s-%s.log" % (
            model["slug"],
            time.strftime("%H%M%S")))
    cmd = [
        "aria2c",
        "--continue=true",
        "--allow-overwrite=true",
        "--file-allocation=none",
        "-x", str(connections), "-s", str(connections), "-k", "1M",
        "--max-tries=%d" % ARIA_TRIES,
        "--retry-wait=%d" % ARIA_RETRY_WAIT,
        "--timeout=%d" % STALL_SECONDS,
        "--connect-timeout=30",
        "--dir=%s" % dest_dir,
        "--out=%s" % basename,
        "--log=%s" % aria_log,
        "--log-level=info",
        "--console-log-level=warn",
        "--summary-interval=0",
    ]
    # 开本地 RPC 问真实进度：completedLength 是真正写盘的字节数，
    # 文件体积（st_size）会因多分段乱序写盘虚高，不能用来量进度和速度。
    # 每次调用换一个随机端口和密钥，避免复用冲突；只监听本机。
    rpc_port = pick_rpc_port()
    rpc_secret = secrets.token_hex(16)
    cmd += [
        "--enable-rpc=true",
        "--rpc-listen-port=%d" % rpc_port,
        "--rpc-secret=%s" % rpc_secret,
        "--rpc-listen-all=false",
    ]
    if sha256:
        cmd.append("--checksum=sha-256=" + sha256)
    if token and ("huggingface.co" in url or "hf-mirror.com" in url):
        cmd.append("--header=Authorization: Bearer " + token)
    cmd.append(url)

    log("开始下载 [%s] %s (%s)，来源 %s，并发 %d" % (
        model["name"], basename, fmt_gb(fname["size"]), source, connections))
    try:
        CHILD_PROC = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return False, "无法启动 aria2c: %s" % e
    proc = CHILD_PROC
    start = time.time()
    last_change = start
    last_done = 0
    verify_logged = False  # 文件到 100% 后只打一次“正在校验”提示
    polls = 0
    rpc_miss = 0
    rpc_warned = False
    try:
        while True:
            if STOP_REQUESTED:
                # 等 aria2c 保存断点状态后再退出，避免控制文件写一半
                try:
                    proc.wait(timeout=15)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                if STATUS_ACTIVE:
                    sys.stdout.write("\n")
                    STATUS_ACTIVE = False
                return False, "用户中断"
            rc = proc.poll()
            rpc_done, _rpc_speed = rpc_status(rpc_port, rpc_secret)
            try:
                cur_file = os.path.getsize(target)
            except OSError:
                cur_file = 0
            now = time.time()
            if rpc_done is not None:
                # 0 速判断只用 RPC 的真实进度：文件体积会因多分段乱序写盘
                # 虚高，一旦用它抬高过 last_done，RPC 的真实值就再也超不过
                # 它，会误判 0 速（实测：下到 2.8GB、15MB/s 仍被判 stall）。
                cur_done = min(rpc_done, fname["size"])
                rpc_miss = 0
                if cur_done > last_done:
                    last_change = now
                    last_done = cur_done
            else:
                # RPC 问不到时退回文件体积显示，但不拿它判 0 速；
                # 真卡死时由 aria2 自身的 --timeout=180 兜底重试。
                cur_done = cur_file
                rpc_miss += 1
                if (rpc_miss >= 3 and not rpc_warned
                        and cur_file < fname["size"]):
                    rpc_warned = True
                    log("aria2 RPC 问不到进度，退回文件体积估算"
                        "（速度和进度可能虚高，仅本次尝试）")
            tracker.set_current(model["slug"], basename, cur_done)
            done = tracker.sample()
            speed = tracker.speed()
            eta = tracker.eta()
            mdone = tracker.model_done(model)
            f_pct = (100.0 * cur_done / fname["size"]) if fname["size"] else 0.0
            m_pct = (100.0 * mdone / model["size"]) if model["size"] else 0.0
            t_pct = 100.0 * done / tracker.total if tracker.total else 0.0
            status = ("[%s] %s (%d/%d) | %s %s/%s %.0f%% | %s | 本模型 %.0f%% "
                      "| 总体 %.1f%% (%s/%s) | 剩余 %s" % (
                          time.strftime("%H:%M:%S"), model["name"],
                          model_index, model_count, basename,
                          fmt_gb(cur_done), fmt_gb(fname["size"]), f_pct,
                          fmt_speed(speed), m_pct, t_pct,
                          fmt_gb(done), fmt_gb(tracker.total), fmt_eta(eta)))
            sys.stdout.write("\r" + status + " " * 8)
            sys.stdout.flush()
            STATUS_ACTIVE = True
            polls += 1
            if polls % 6 == 0 and LOG_FP is not None:
                LOG_FP.write("%s %s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), status))
                LOG_FP.flush()
            if (cur_done >= fname["size"]
                    and not os.path.exists(target + ".aria2")):
                # 下完了且校验通过（aria2 只在校验通过后才删控制文件），
                # 但开 RPC 后 aria2 不会自动退出，用 RPC 让它干净退出，
                # 否则脚本会一直等到 180 秒 0 速保护才误判为卡死。
                rpc_shutdown(rpc_port, rpc_secret)
                try:
                    proc.wait(timeout=15)
                except Exception:
                    try:
                        proc.terminate()
                        proc.wait(timeout=10)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                if STATUS_ACTIVE:
                    sys.stdout.write("\n")
                    STATUS_ACTIVE = False
                return True, "ok"
            if rc is not None:
                if STATUS_ACTIVE:
                    sys.stdout.write("\n")
                    STATUS_ACTIVE = False
                if rc == 0:
                    return True, "ok"
                return False, "aria2c 退出码 %d（详见 %s）" % (rc, aria_log)
            if (now - last_change > STALL_SECONDS and now - start > 10
                    and rpc_done is not None
                    and cur_done < fname["size"]):
                # 只有本次问到了 RPC、且文件还没下满时才判 0 速。
                # 文件已到 100% 时 0 速是正常的（aria2 在做 sha256 校验），
                # 不能按 180 秒判 stall；校验阶段不设超时，只等它完成。
                log("持续 %d 秒 0 速，终止本次尝试并重试（文件已下载部分保留）"
                    % STALL_SECONDS)
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                if STATUS_ACTIVE:
                    sys.stdout.write("\n")
                    STATUS_ACTIVE = False
                return False, "stall-180s"
            if cur_done >= fname["size"] and not verify_logged:
                # 到 100% 后 aria2 做 sha256 校验（读盘+算 hash），这段时间
                # 下载速度是 0，属于正常收尾。校验阶段不设超时：校验是本地
                # 确定性操作（读完即完），超时重试只会让它从头再算一遍，
                # 没有任何用处；校验失败时 aria2 自己会以非 0 退出码退出，
                # 由上面的 rc 检查处理。只等它完成即可。
                verify_logged = True
                log("文件已 100%%，正在做 sha256 校验（读盘+算 hash），"
                    "速度显示为 0 是正常的，耐心等它完成")
            if cur_done < fname["size"]:
                verify_logged = False
            time.sleep(POLL_SECONDS)
    finally:
        tracker.clear_current()


def download_file(model, fname, dest, log_dir, connections, token,
                  tracker, model_index, model_count):
    """下载一个文件：跳过已完成的，无限重试直到完成或用户中断。"""
    dest_dir = os.path.join(dest, model["slug"])
    os.makedirs(dest_dir, exist_ok=True)
    basename = os.path.basename(fname["path"])
    target = os.path.join(dest_dir, basename)
    attempt = 0
    while not STOP_REQUESTED:
        attempt += 1
        state = file_state(target, fname["size"])
        if state == "done":
            log("已完成，跳过 [%s] %s (%s)" % (
                model["name"], basename, fmt_gb(fname["size"])))
            return True
        if state == "oversize":
            log("文件比预期大，删除重下 [%s] %s" % (model["name"], basename))
            os.remove(target)
        elif state == "partial-noctl":
            log("发现无断点信息的残缺文件，删除重下 [%s] %s" % (
                model["name"], basename))
            os.remove(target)
        elif state == "partial":
            log("断点续传 [%s] %s" % (model["name"], basename))
        source, url = pick_url(model, fname, token)
        if url is None:
            log("[%s] %s：三个镜像暂时都不可达，%d 秒后重试（第 %d 次）"
                % (model["name"], basename, MIRROR_RETRY_WAIT, attempt))
            interruptible_sleep(MIRROR_RETRY_WAIT)
            continue
        ok, reason = run_aria2c(
            url, source, dest_dir, fname, fname.get("sha256"), token,
            log_dir, connections, tracker, model, model_index, model_count)
        if STOP_REQUESTED:
            return False
        if ok:
            if file_state(target, fname["size"]) == "done":
                log("完成 [%s] %s (%s)，sha256 已校验" % (
                    model["name"], basename, fmt_gb(fname["size"])))
                return True
            log("[%s] %s：aria2c 返回成功但大小不符，重试" % (
                model["name"], basename))
        else:
            log("[%s] %s：第 %d 次尝试失败（%s），%d 秒后重试" % (
                model["name"], basename, attempt, reason, RETRY_WAIT))
        interruptible_sleep(RETRY_WAIT)
    return False


# ---------------------------------------------------------------- 主流程
def write_readme(dest, models, total_files, total_size):
    lines = [
        "# Strix Halo 395 模型库",
        "",
        "下载时间：%s；共 %d 个模型、%d 个文件、%s。" % (
            time.strftime("%Y-%m-%d %H:%M"),
            len(models), total_files,
            fmt_gb(total_size)),
        "在 Ubuntu 上把本盘挂载后直接用，无需后处理。",
        "",
        "## 用 llama.cpp 运行（示例）",
        "",
        "```bash",
        "llama-server --model /path/to/models/qwen3-coder-30b/Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf \\",
        "  --host 0.0.0.0 --port 8080 -c 131072",
        "```",
        "",
        "多分片模型（如 Qwen3-Coder-Next）只需指第一个分片，llama.cpp 会自动找齐其余分片。",
        "带 mmproj 的视觉模型（Qwen3-VL-32B、Gemma-3-27B-it、Inkling-2-Mini）加 `--mmproj` 指向同目录的 mmproj 文件。",
        "",
        "## 模型清单",
        "",
        "| 模型 | 目录 | 文件 | 大小 |",
        "|---|---|---|---|",
    ]
    for model in models:
        files = ", ".join(os.path.basename(f["path"])
                          for f in model["files"])
        lines.append("| %s | %s/ | %s | %s |" % (
            model["name"], model["slug"], files, fmt_gb(model["size"])))
    with open(os.path.join(dest, "README.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    global LOG_FP
    ap = argparse.ArgumentParser(description="Strix Halo 395 模型批量下载")
    ap.add_argument("--dest", required=True,
                    help="模型存放目录（macOS 如 /Volumes/llms/models，"
                    "Ubuntu 如 /mnt/llms/models）")
    ap.add_argument("--manifest", default=None,
                    help="manifest.json 路径（默认：脚本同目录）")
    ap.add_argument("--connections", type=int, default=16,
                    help="每文件并发连接数（默认 16）")
    ap.add_argument("--only", default=None,
                    help="只下载某一个模型（用 slug，如 qwen3-8b）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出下载计划，不下载")
    args = ap.parse_args()

    if shutil.which("aria2c") is None:
        if sys.platform == "darwin":
            print("没找到 aria2c，请先安装：brew install aria2")
        else:
            print("没找到 aria2c，请先安装：sudo apt install aria2")
        return 1
    script_dir = os.path.dirname(os.path.abspath(__file__))
    manifest_path = args.manifest or os.path.join(script_dir, "manifest.json")
    try:
        with open(manifest_path) as fh:
            manifest = json.load(fh)
    except OSError:
        print("找不到 manifest.json：%s" % manifest_path)
        return 1
    token = os.environ.get("HF_TOKEN") or None

    models = manifest["models"]
    if args.only:
        models = [m for m in models if m["slug"] == args.only]
        if not models:
            print("manifest 里没有 slug 为 %s 的模型" % args.only)
            return 1
    total_size = sum(m["size"] for m in models)
    total_files = sum(len(m["files"]) for m in models)

    if args.dry_run:
        print("下载计划：%d 个模型、%d 个文件、%s" % (
            len(models), total_files, fmt_gb(total_size)))
        for m in models:
            ms = "ModelScope" if any(
                f.get("modelscope_ok") for f in m["files"]) else "-"
            print("  %-22s %2d 文件 %8s  国内镜像：%s" % (
                m["slug"], len(m["files"]), fmt_gb(m["size"]), ms))
        return 0

    os.makedirs(args.dest, exist_ok=True)
    log_dir = os.path.join(args.dest, ".logs")
    os.makedirs(log_dir, exist_ok=True)
    LOG_FP = open(os.path.join(
        log_dir, "download-%s.log" % time.strftime("%Y%m%d-%H%M%S")),
        "a", buffering=1)
    log("开始下载：%d 个模型、%d 个文件、共 %s" % (
        len(models), total_files, fmt_gb(total_size)))
    log("目标目录：%s；每文件并发连接：%d" % (args.dest, args.connections))
    if token:
        log("已设置 HF_TOKEN（仅用于个别要求授权的仓库）")
    usage = shutil.disk_usage(args.dest)
    log("目标盘剩余空间：%s" % fmt_gb(usage.free))
    tracker = Tracker(models, args.dest)
    already = tracker.downloaded()
    if total_size - already > usage.free:
        log("空间不足：还需下载 %s，但目标盘只剩 %s" % (
            fmt_gb(total_size - already), fmt_gb(usage.free)))
        return 1
    log("已下载 %s，剩余待下载 %s" % (
        fmt_gb(already), fmt_gb(total_size - already)))

    t0 = time.time()
    ok_all = True
    for idx, model in enumerate(models, 1):
        if STOP_REQUESTED:
            break
        log("模型 %d/%d：%s（%d 个文件，%s）" % (
            idx, len(models), model["name"], len(model["files"]),
            fmt_gb(model["size"])))
        for fname in model["files"]:
            if STOP_REQUESTED:
                break
            if not download_file(model, fname, args.dest, log_dir,
                                 args.connections, token, tracker,
                                 idx, len(models)):
                ok_all = False
                break
        if not ok_all:
            break
    elapsed = time.time() - t0
    done = tracker.downloaded()
    if STOP_REQUESTED:
        log("已停止（Ctrl+C）。已下载 %s / %s，重新运行本脚本自动继续。"
            % (fmt_gb(done), fmt_gb(total_size)))
        return 130
    if ok_all:
        avg = done / elapsed if elapsed > 1 else 0
        log("全部完成：%d 个文件、%s，用时 %s，平均速度 %s" % (
            total_files, fmt_gb(done), fmt_eta(elapsed),
            fmt_speed(avg) if avg > 0 else "--"))
        write_readme(args.dest, models, total_files, total_size)
        log("已在目标目录生成 README.md（模型清单与 llama-server 用法）")
        return 0
    log("未完成：已下载 %s / %s，重新运行本脚本继续。" % (
        fmt_gb(done), fmt_gb(total_size)))
    return 1


if __name__ == "__main__":
    sys.exit(main())

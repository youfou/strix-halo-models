#!/bin/bash
# 通过 RunWisp 启动 / 停止 / 查看模型下载任务（macOS / Ubuntu 通用）
#
# 用法（在 download-models.py、manifest.json、runwisp.toml 所在目录）：
#   ./start-download.sh          启动下载（daemon 未运行会自动拉起；
#                                只触发任务就返回，不占命令行，下载在
#                                daemon 手下后台跑；看实时输出用 logs）
#   ./start-download.sh stop     停止下载（等同于按 Ctrl+C，断点已保存）
#   ./start-download.sh status   看 daemon 与任务状态
#   ./start-download.sh logs     看本次运行的实时输出
#   ./start-download.sh restart  重启 daemon（改了监听地址/端口后用，
#                                reload 改不了这两个），下载从断点续传
#
# 目标盘就是 runwisp.toml 里 run 命令的 --dest（macOS 默认 /Volumes/llms/models，
# Ubuntu 默认 /mnt/llms/models），换盘直接改那一行；不想改文件时也可以启动前加
# DOWNLOAD_DEST 临时覆盖：
#   DOWNLOAD_DEST=/mnt/llms/models ./start-download.sh
# 监控在 Web UI 看：本机 http://127.0.0.1:9477，局域网另一台设备用
# http://<这台机器的局域网 IP>:9477（端口可用 RUNWISP_PORT 改，
# 监听地址可用 RUNWISP_HOST 改，默认 0.0.0.0 即全部网卡）。
# 注意：0.0.0.0 会把 Web UI 暴露给整个局域网，务必先设一个固定密码再重启
# daemon：RUNWISP_PASSWORD=你的密码 ./start-download.sh（否则每次启动都
# 随机生成一个新密码）；想上 HTTPS 可在 runwisp.toml 的 [daemon] 里加
# tls = "auto"（自签证书，浏览器会报证书警告，点继续即可）。
# 下载脚本自己的详细日志在目标盘的 .logs/ 目录里。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/runwisp.toml"
# RunWisp 自己的数据（数据库、日志、控制 socket）放内置盘，不放模型盘：
# exFAT 不支持 Unix socket，daemon 会在 .runwisp/runwisp.sock 上 bind 失败。
# 下载本身仍走 runwisp.toml 里 --dest 指的模型盘，不受影响。
DATA="${RUNWISP_DATA:-$HOME/.runwisp}"
TASK="download-models"
PORT="${RUNWISP_PORT:-9477}"
# daemon 的 HTTP 监听地址：默认 0.0.0.0（全部网卡，局域网另一台设备也能
# 打开 Web UI）。只想本机访问时改回 127.0.0.1：
#   RUNWISP_HOST=127.0.0.1 ./start-download.sh
# 注意：监听地址是 daemon 启动时的 flag，runwisp reload 改不了，改了它
# 要用 ./start-download.sh restart 重启 daemon 才生效。
HOST="${RUNWISP_HOST:-0.0.0.0}"

die() { echo "错误：$*" >&2; exit 1; }
info() { echo "$*"; }

daemon_running() {
    runwisp status -c "$CONFIG" --data "$DATA" >/dev/null 2>&1
}

# 任务是否正在跑（看 status --json 里 lastRun 的状态）。
# 查不到或出错时返回非 0（按“没在跑”处理，直接触发即可）。
# 注意：runwisp start 对已在跑的任务不是 no-op——默认 on_overlap=queue
# 会把这次触发排进队列，等当前这次跑完再启动；本配置已设 on_overlap=skip，
# 重复触发会被丢弃而不是排队，这里先拦住是给一句明确提示。
task_running() {
    runwisp status --json -c "$CONFIG" --data "$DATA" 2>/dev/null | python3 -c "
import json, sys
task = sys.argv[1]
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for t in d.get('tasks', []):
    if t.get('name') == task:
        lr = t.get('lastRun') or {}
        sys.exit(0 if lr.get('status') == 'running' else 1)
sys.exit(1)
" "$TASK"
}

# 本机局域网 IP（打 Web UI 地址用）；拿不到时返回空，只显示 127.0.0.1。
lan_ip() {
    if [ "$(uname)" = "Darwin" ]; then
        ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null
    else
        hostname -I 2>/dev/null | awk '{print $1}'
    fi
}

# 打印 Web UI 地址：本机 + 局域网（监听 0.0.0.0 时另一台设备用后者）。
web_ui_info() {
    info "Web UI（本机）：http://127.0.0.1:${PORT:-9477}"
    local lip
    lip="$(lan_ip)"
    if [ -n "$lip" ] && [ "$HOST" = "0.0.0.0" ]; then
        info "Web UI（局域网）：http://$lip:${PORT:-9477}"
    fi
}

# ---- 前置检查 ----
if [ "$(uname)" = "Darwin" ]; then
    [ -x "$(command -v runwisp)" ] \
        || die "找不到 runwisp，先装：brew install runwisp/tap/runwisp"
    [ -x "$(command -v aria2c)" ] \
        || die "找不到 aria2c，先装：brew install aria2"
else
    [ -x "$(command -v runwisp)" ] || die "找不到 runwisp，先装：从 https://github.com/runwisp/runwisp/releases 下 runwisp-linux-x64.tar.gz，解压后把 runwisp 放进 PATH（如 /usr/local/bin，见 README 的 Ubuntu 章节）"
    [ -x "$(command -v aria2c)" ] \
        || die "找不到 aria2c，先装：sudo apt install aria2"
fi
[ -x "$(command -v python3)" ] || die "找不到 python3"
[ -f "$SCRIPT_DIR/download-models.py" ] || die "找不到 $SCRIPT_DIR/download-models.py"
[ -f "$SCRIPT_DIR/manifest.json" ] || die "找不到 $SCRIPT_DIR/manifest.json"
[ -f "$CONFIG" ] || die "找不到 $CONFIG"

# ---- 目标目录：默认读配置，DOWNLOAD_DEST 可覆盖 ----
DEST="$(sed -n 's/^run = ".*--dest \([^ "]*\).*/\1/p' "$CONFIG" | head -1)"
[ -n "$DEST" ] || die "runwisp.toml 的 run 命令里没找到 --dest"
if [ -n "${DOWNLOAD_DEST:-}" ]; then
    DEST="$DOWNLOAD_DEST"
    esc_dest="$(printf '%s' "$DEST" | sed 's/[&|]/\\&/g')"
    sed "/^run = /s|--dest [^\" ]*|--dest $esc_dest|" "$CONFIG" > "$CONFIG.tmp" \
        && mv "$CONFIG.tmp" "$CONFIG"
fi
# 模型盘必须已挂载：没挂载时 download-models.py 会把目录建在内置盘上，
# 948GB 写进去就满了，所以这里先拦住。挂载点取目标路径的前两级
# （如 /Volumes/llms）。
DEST_VOL="$(printf '%s' "$DEST" | cut -d/ -f1-3)"
if [ "$(uname)" = "Darwin" ]; then
    mount | grep -q " on $DEST_VOL (" || die "外接盘 $DEST_VOL 未挂载，先插盘再跑"
else
    mount | grep -q " on $DEST_VOL type " || die "目标盘 $DEST_VOL 未挂载：先按 README 的 Ubuntu 章节把盘挂载到 $DEST_VOL（或把 runwisp.toml 里 run 命令的 --dest 改成实际挂载点）再跑"
fi

# ---- 把配置里的 working_dir 指到本脚本所在目录 ----
# 这样四个文件放哪都能跑，不用手工改 runwisp.toml。
esc_dir="$(printf '%s' "$SCRIPT_DIR" | sed 's/[&|]/\\&/g')"
if grep -q '^working_dir' "$CONFIG"; then
    sed "s|^working_dir = .*|working_dir = \"$esc_dir\"|" "$CONFIG" > "$CONFIG.tmp" \
        && mv "$CONFIG.tmp" "$CONFIG"
else
    sed "/^\[tasks.$TASK\]/a\\
working_dir = \"$esc_dir\"" "$CONFIG" > "$CONFIG.tmp" \
        && mv "$CONFIG.tmp" "$CONFIG"
fi

# ---- 校验配置 ----
# RunWisp 1.9.1 要求配置文件不能被组/其他人写（否则 daemon 拒绝启动）；
# 上面 sed 重写会按当前 umask 建文件，显式改成 0644 才稳妥。
# 同理，配置文件所在的目录也不能组写（RunWisp 会沿路径逐级检查）。
chmod 0755 "$SCRIPT_DIR"
chmod 0644 "$CONFIG"
runwisp validate -c "$CONFIG" --data "$DATA" >/dev/null 2>&1 \
    || die "runwisp.toml 校验失败，执行 runwisp validate -c $CONFIG --data $DATA 看详情"

ACTION="${1:-start}"
case "$ACTION" in
start)
    if ! daemon_running; then
        info "RunWisp daemon 未运行，正在拉起（监听 ${HOST:-0.0.0.0}:${PORT:-9477}）……"
        nohup runwisp daemon -c "$CONFIG" --data "$DATA" \
            --host "${HOST:-0.0.0.0}" --port "${PORT:-9477}" \
            > "$SCRIPT_DIR/.runwisp-daemon.log" 2>&1 &
        ok=0
        for ((i = 0; i < 30; i++)); do
            if daemon_running; then ok=1; break; fi
            sleep 1
        done
        [ "$ok" = 1 ] || {
            echo "daemon 30 秒内没起来，看日志：" >&2
            tail -20 "$SCRIPT_DIR/.runwisp-daemon.log" >&2
            echo "如果提示端口被占，说明已有别的 RunWisp daemon 在跑，" >&2
            echo "换个端口再试：RUNWISP_PORT=9478 ./start-download.sh" >&2
            exit 1
        }
        info "daemon 已启动。"
    fi
    runwisp reload -c "$CONFIG" --data "$DATA" \
        || die "配置重载失败"
    if task_running; then
        info "任务 $TASK 已在运行中，不用重复启动。"
        web_ui_info
        info "看实时日志：./start-download.sh logs"
        exit 0
    fi
    # 用 runwisp start 触发（只发一个“开始”信号就返回，命令行立即释放，
    # 下载在 daemon 手下后台跑）；想看实时输出用 ./start-download.sh logs
    # 或 Web UI。旧版这里用 runwisp run，会一直跟到任务结束才返回，
    # 24 小时下载会把命令行占住（要 Ctrl+C 才能断开）。
    runwisp start "$TASK" -c "$CONFIG" --data "$DATA" \
        || die "触发任务失败"
    info "下载任务已启动（后台运行，命令行已释放）。"
    web_ui_info
    info "看实时日志：./start-download.sh logs"
    info "脚本自己的日志：$DEST/.logs/"
    info "停止：./start-download.sh stop"
    ;;
stop)
    daemon_running || die "daemon 未运行，没有正在跑的任务"
    runwisp stop "$TASK" -c "$CONFIG" --data "$DATA" \
        || die "停止失败（任务可能已经不在运行）"
    info "已发停止信号（SIGINT），脚本正在保存断点后退出。"
    info "下次执行 ./start-download.sh 会从断点续传。"
    ;;
status)
    daemon_running || die "daemon 未运行"
    runwisp status -c "$CONFIG" --data "$DATA"
    web_ui_info
    ;;
restart)
    # 重启 daemon 以应用新的监听地址 / 端口（--host、--port 是启动时 flag，
    # runwisp reload 改不了）。先停任务（SIGINT，保存断点），再停 daemon，
    # 最后重新拉起并续传。下载本身从断点继续，不重下。
    if daemon_running; then
        info "正在停止任务 $TASK（保存断点）……"
        runwisp stop "$TASK" -c "$CONFIG" --data "$DATA" >/dev/null 2>&1 || true
        info "正在停止 daemon……"
        runwisp stop -c "$CONFIG" --data "$DATA" >/dev/null 2>&1 || true
        for ((i = 0; i < 40; i++)); do
            daemon_running || break
            sleep 1
        done
        daemon_running && die "daemon 40 秒内没停下，先手工处理再跑"
        info "daemon 已停。"
    fi
    # 复用 start 的流程：拉起 daemon（带新的 --host）并触发任务续传。
    exec "$0" start
    ;;
logs)
    daemon_running || die "daemon 未运行"
    runwisp logs -f "$TASK" -c "$CONFIG" --data "$DATA"
    ;;
*)
    die "用法：$0 [start|stop|status|logs|restart]"
    ;;
esac

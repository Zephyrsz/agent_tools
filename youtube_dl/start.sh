#!/usr/bin/env bash
# TubeSafe 本地服务管理，兼容 macOS 自带 Bash 和 Linux Bash。
set -euo pipefail
umask 077

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/tubesafe.pid"
LOG_FILE="$ROOT_DIR/logs/tubesafe.log"
PYTHON="$ROOT_DIR/.venv/bin/python"
URL="http://127.0.0.1"

usage() {
    echo "用法: $0 {start|stop|restart|status}"
    echo "可选: PORT=8765 $0 start（默认端口 8765，仅监听本机）"
}

fail() { echo "错误: $*" >&2; exit 1; }

case "${1:-}" in
    start|stop|restart|status) ACTION="$1" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
[[ $# -eq 1 ]] || { usage >&2; exit 2; }

mkdir -p "$RUN_DIR"
# 防止并发 start/restart 创建多个实例；异常断电留下的锁需手动清理。
LOCK_DIR="$RUN_DIR/control.lock"
mkdir "$LOCK_DIR" 2>/dev/null || fail "另一个管理操作正在执行；若确认没有操作运行，请删除 $LOCK_DIR 后重试。"
trap 'rmdir "$LOCK_DIR"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

valid_port() {
    [[ "$1" =~ ^[1-9][0-9]{0,4}$ ]] && (( $1 <= 65535 ))
}

load_state() {
    [[ -f "$PID_FILE" ]] || return 1
    {
        read -r PID
        read -r SAVED_PORT
        IFS= read -r STARTED_AT
    } < "$PID_FILE" || return 1
    [[ "$PID" =~ ^[0-9]+$ && ${#PID} -le 10 ]] && (( PID > 1 )) || return 1
    valid_port "$SAVED_PORT" && [[ -n "$STARTED_AT" ]]
}

is_running() {
    local command started state
    kill -0 "$PID" 2>/dev/null || return 1
    state="$(ps -p "$PID" -o stat= 2>/dev/null)" || return 1
    [[ "$state" != *Z* ]] || return 1
    command="$(ps -ww -p "$PID" -o command= 2>/dev/null)" || return 1
    started="$(LC_ALL=C ps -p "$PID" -o lstart= 2>/dev/null)" || return 1
    # 同时匹配启动命令和启动时间，避免陈旧 PID 指向其他进程。
    [[ "$command" == "$PYTHON -m app.cli --port $SAVED_PORT" && "$started" == "$STARTED_AT" ]]
}

stop_service() {
    if ! load_state || ! is_running; then
        rm -f "$PID_FILE"
        echo "TubeSafe 未运行（已清理失效的进程记录）。"
        return
    fi
    echo "正在停止 TubeSafe (PID $PID)..."
    kill -TERM "$PID" 2>/dev/null || true
    for ((i=0; i<30; i++)); do
        if ! is_running; then
            rm -f "$PID_FILE"
            echo "TubeSafe 已停止。"
            return
        fi
        sleep 1
    done
    fail "服务在 30 秒内未退出，已保留进程记录；请检查 $LOG_FILE 后重试。"
}

start_service() {
    if load_state && is_running; then
        echo "TubeSafe 已运行 (PID $PID): $URL:$SAVED_PORT"
        return
    fi
    rm -f "$PID_FILE"
    local port="${PORT:-8765}"
    valid_port "$port" || fail "PORT 必须是 1–65535 之间的整数。"
    command -v uv >/dev/null 2>&1 || fail "未找到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/"
    cd "$ROOT_DIR"
    echo "正在检查并同步 Python 依赖..."
    UV_PROJECT_ENVIRONMENT="$ROOT_DIR/.venv" uv sync --frozen --inexact
    export PATH="$ROOT_DIR/.venv/bin:$PATH"
    for dependency in aria2c ffmpeg node; do
        if ! command -v "$dependency" >/dev/null 2>&1; then
            echo "提示: 未找到 $dependency，服务仍可启动，但下载功能可能不可用。" >&2
        fi
    done
    "$PYTHON" - "$port" <<'PY'
import socket
import sys

try:
    with socket.socket() as sock:
        # 与 Uvicorn 一致，允许重启后复用处于 TIME_WAIT 的地址。
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError as exc:
    sys.exit(f"无法使用端口 {sys.argv[1]}: {exc}；请释放端口或设置 PORT。")
PY
    mkdir -p "$(dirname "$LOG_FILE")"
    printf '\n--- TubeSafe 启动 %s ---\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
    # 直接启动虚拟环境 Python，记录服务本身的 PID，不记录 uv 包装进程。
    nohup "$PYTHON" -m app.cli --port "$port" >> "$LOG_FILE" 2>&1 < /dev/null &
    PID=$!
    SAVED_PORT="$port"
    STARTED_AT="$(LC_ALL=C ps -p "$PID" -o lstart=)"
    printf '%s\n%s\n%s\n' "$PID" "$SAVED_PORT" "$STARTED_AT" > "$PID_FILE"
    for ((i=0; i<30; i++)); do
        # 给 nohup 一次完成 exec 的机会，再校验服务身份。
        sleep 1
        if ! is_running; then
            rm -f "$PID_FILE"
            tail -n 20 "$LOG_FILE" >&2
            fail "TubeSafe 启动失败，详情见 $LOG_FILE"
        fi
        if "$PYTHON" - "$URL:$port/api/health" <<'PY'
import json
import sys
import urllib.request

try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(sys.argv[1], timeout=0.5) as response:
        data = json.load(response)
    # ok 表示外部下载工具是否齐全；HTTP 正常响应即表示服务已就绪。
    sys.exit(0 if data.get("profile") == "conservative" else 1)
except Exception:
    sys.exit(1)
PY
        then
            if is_running; then
                echo "TubeSafe 已启动 (PID $PID): $URL:$port"
                echo "日志: $LOG_FILE"
                return
            fi
        fi
    done
    echo "服务就绪检查超时，正在清理本次启动的进程..." >&2
    stop_service
    fail "TubeSafe 未能就绪，详情见 $LOG_FILE"
}

case "$ACTION" in
    start) start_service ;;
    stop) stop_service ;;
    restart) stop_service; start_service ;;
    status)
        if load_state && is_running; then
            echo "TubeSafe 正在运行 (PID $PID): $URL:$SAVED_PORT"
        else
            echo "TubeSafe 未运行。"
            exit 1
        fi
        ;;
esac

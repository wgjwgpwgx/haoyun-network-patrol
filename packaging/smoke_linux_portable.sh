#!/usr/bin/env bash
# 信创 Linux 绿色包冒烟:在"同代 glibc 的干净容器"里实跑解压后的程序。
#
# 用法: packaging/smoke_linux_portable.sh <xxx-linux-<arch>.tar.gz>
# 不依赖构建环境、不依赖 curl(用 bash 的 /dev/tcp 发原始 HTTP 请求)。
# 覆盖:--help 可启动 / 无图形库时自动转 Web 模式 / --web 拉起服务并响应 /
#       登录默认开启 / 非 Windows 启动时提示密码明文落库。
set -euo pipefail

PKG="${1:?用法: smoke_linux_portable.sh <tar.gz>}"
PORT="${PATROL_PORT:-8765}"
WORK="$(mktemp -d)"
tar xzf "$PKG" -C "$WORK"
cd "$WORK/haoyun-patrol"

listening() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }

wait_http() {  # $1: 日志文件
  for _ in $(seq 1 60); do
    listening && return 0
    sleep 1
  done
  echo "服务未在 60 秒内监听 $PORT 端口,日志如下:"; cat "$1"; return 1
}

status_line() {  # $1: 请求路径 → 输出 HTTP 状态行
  exec 3<>"/dev/tcp/127.0.0.1/$PORT"
  printf 'GET %s HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n' "$1" >&3
  head -n1 <&3
  exec 3>&- 3<&-
}

expect_status() {  # $1: 路径 $2: 期望状态码
  local line
  line="$(status_line "$1")"
  case "$line" in
    *" $2 "*) echo "  GET $1 -> $2";;
    *) echo "  GET $1 期望 $2,实际: $line"; return 1;;
  esac
}

stop_app() {  # $1: 主进程 PID。onefile 有父子两个进程,并确认端口确实释放
  kill "$1" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$1" 2>/dev/null || break; sleep 0.5; done
  kill -9 "$1" 2>/dev/null || true
  for _ in $(seq 1 20); do listening || return 0; sleep 0.5; done
  echo "停止后端口 $PORT 仍未释放"; return 1
}

echo "[1/5] --help(引导器与 Python 运行时可启动)"
./patrol-assistant --help >/dev/null

echo "[2/5] 无参数启动:没有图形库时应自动转 Web 模式并提示密码明文落库"
export PATROL_NO_BROWSER=1 PATROL_PORT="$PORT"
./patrol-assistant >"$WORK/noarg.log" 2>&1 &
PID=$!
wait_http "$WORK/noarg.log"
grep -q "自动切换 Web 模式" "$WORK/noarg.log" \
  || { echo "未见'自动切换 Web 模式'提示:"; cat "$WORK/noarg.log"; exit 1; }
grep -q "明文" "$WORK/noarg.log" \
  || { echo "未见'密码明文落库'提示:"; cat "$WORK/noarg.log"; exit 1; }
stop_app "$PID"

echo "[3/5] --web 启动并响应请求"
./patrol-assistant --web >"$WORK/web.log" 2>&1 &
PID=$!
wait_http "$WORK/web.log"
expect_status "/ui" 303
expect_status "/ui/login" 200

echo "[4/5] 登录默认开启:未登录访问接口被拒"
expect_status "/devices" 401

echo "[5/5] 退出"
stop_app "$PID"
echo "LINUX_PORTABLE_SMOKE_OK ($PKG)"

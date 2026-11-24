"""模拟设备服务器(P1 演示件⑤):本地 Telnet 模拟真机

流程仿真(真实代码路径,非 mock):
  netmiko(telnet 通道) → 登录提示 → 命令 → 回显(来自知识库/内置种子)

用途:无真机演示、培训、自测 Telnet 通道与解析链。
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Callable

logger = logging.getLogger(__name__)

_PROMPT = "SimCore"   # 提示符主体;实际提示符为 SimCore>(用户模式)/ SimCore#(特权模式)


class SimDeviceServer:
    """极简 Telnet 行服务器:登录两步 + 命令回显循环。"""

    def __init__(self, port: int = 0, responses: dict[str, str] | None = None,
                 prompt: str = _PROMPT) -> None:
        self.responses = responses or {}
        self.prompt = prompt
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", port))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        self._running = False
        self._thread: threading.Thread | None = None

    # ── 生命周期 ─────────────────────────────────────────────

    def start(self) -> int:
        """后台启动,返回端口。"""
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        logger.info("模拟设备已启动: 127.0.0.1:%d (telnet)", self.port)
        return self.port

    def stop(self) -> None:
        self._running = False
        try:
            self._srv.close()
        except OSError:
            pass

    def _serve(self) -> None:
        while self._running:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    # ── 单连接处理 ───────────────────────────────────────────

    def _send(self, conn, text: str) -> None:
        conn.sendall((text + "\r\n").encode("utf-8", errors="replace"))

    @staticmethod
    def _reader(conn):
        """返回"按行读取"函数:CRLF 视为一个行结束符,空行返回 "",对端关闭返回 None。

        客户端(netmiko)的行结束符并不统一——用户名后发 CRLF、密码后只发 CR、
        探测提示符时发一个空行,所以必须逐字节按状态切行,不能按固定分隔符读。
        """
        last_was_cr = False  # 上个字节是 CR:紧随的 LF 属于同一个行结束符

        def readline() -> str | None:
            nonlocal last_was_cr
            buf = b""
            while True:
                ch = conn.recv(1)
                if not ch:
                    return None
                if last_was_cr and ch == b"\n":
                    last_was_cr = False
                    continue
                last_was_cr = ch == b"\r"
                if ch in (b"\r", b"\n"):
                    return buf.decode("utf-8", errors="replace").strip()
                buf += ch

        return readline

    def _handle(self, conn) -> None:
        try:
            readline = self._reader(conn)

            # 登录仿真:Username: → Password: → 提示符
            self._send(conn, "Warning: Simulated device (patrol simulator)")
            self._send(conn, "Username: ")
            readline()                  # 用户名(任意)
            self._send(conn, "Password: ")
            readline()                  # 密码(任意)

            # 命令循环。行为按真机习惯,否则 netmiko 登录后无法定位提示符:
            #   提示符独占一行 / 键入的命令原样回显 / 空行(只按回车)也重新给出提示符
            privileged = False
            while True:
                suffix = "#" if privileged else ">"
                conn.sendall(("\r\n" + self.prompt + suffix).encode())
                line = readline()
                if line is None:
                    return              # 对端关闭
                low = line.lower().strip()
                if line and low in ("quit", "exit", "logout"):
                    self._send(conn, "Bye")
                    return
                if not line:
                    continue             # 空行:循环开头已重新给出提示符
                self._send(conn, line)   # 回显命令:netmiko 以此划分命令与输出
                if low == "enable" and not privileged:
                    # 类 IOS 设备的提权:enable → Password: → 提示符变为 #
                    self._send(conn, "Password: ")
                    readline()           # enable 密码(任意)
                    privileged = True
                    continue
                output = self._match(low)
                if output:
                    self._send(conn, output)
        except (OSError, ConnectionResetError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _match(self, low_cmd: str) -> str:
        """命令匹配:精确 → 前缀忽略多余空白;未命中返回空。"""
        squashed = " ".join(low_cmd.split())
        if squashed in self.responses:
            return self.responses[squashed]
        for cmd, text in self.responses.items():
            if squashed.startswith(" ".join(cmd.lower().split())):
                return text
        return ""


# ── 响应表构造 ──────────────────────────────────────────────


def responses_from_seed(vendor: str) -> dict[str, str]:
    from patrol.knowledge_seed import SEED_DEVICES
    for dev in SEED_DEVICES:
        if dev["vendor"] == vendor:
            return dict(dev["responses"])
    return {}


def responses_from_knowledge(customer: str, device: str) -> dict[str, str]:
    from patrol import knowledge as _kb
    """从知识库最新快照构造命令→回显映射(旧资料一键变模拟设备)。"""
    snaps = _kb.list_snapshots(customer, device)
    if not snaps:
        return {}
    rec = _kb.load_snapshot(customer, device, snaps[0]["file"]) or {}
    return {it["command"]: it["raw_output"]
            for it in rec.get("items", []) if it.get("command")}

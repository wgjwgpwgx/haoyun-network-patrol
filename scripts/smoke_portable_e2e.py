"""成品包全链路冒烟:内置模拟设备 → 命令行巡检 + 网页端巡检 → 核对报告与任务状态。

与源码测试互补,只回答一个问题:解压后的程序能不能真用。页面模板、报告模板、
Word 模板有没有进包,按厂商名动态加载的设备驱动类有没有进包,只有成品跑一遍才知道。

用法(项目根目录):
    python scripts/smoke_portable_e2e.py                    # dist 下刚构建的包
    python scripts/smoke_portable_e2e.py <包目录 | .zip | .tar.gz>
    python scripts/smoke_portable_e2e.py <Linux 包 .tar.gz> --image rockylinux:8

    --image:把程序放进"同代 glibc 的干净容器"里跑(仅 Linux 宿主机,需要 docker);
    模拟设备起在宿主机回环地址,容器以 --network host 连回来。

包会先复制到临时目录再跑,原目录不产生任何数据与报告;
全程只用回环地址上的模拟设备,不接触任何真实设备。只用标准库。
"""
from __future__ import annotations

import argparse
import http.cookiejar
import itertools
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # 内置模拟设备只用标准库,无需安装依赖
from patrol.simulator_core import SimDeviceServer, responses_from_seed  # noqa: E402

WIN_DIR, WIN_EXE = "昊云网络巡检助手", "启动巡检助手.exe"
LINUX_EXE = "patrol-assistant"
# 运行期数据与登录凭据不随包分发;从包目录取副本时同样不带
_NOT_SHIPPED = ("data", "output", "config/auth.yaml", "config/smtp.yaml")
SEEDS = [("huawei", "huawei", "vrp_switch"),
         ("h3c", "h3c", "s7506e"),
         ("zte", "zte", "zxr10_switch")]

_passed = _failed = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global _passed, _failed
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f"  ← {detail}" if detail and not ok else ""))
    if ok:
        _passed += 1
    else:
        _failed += 1


def tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.splitlines()[-lines:])


def fetch(package: Path, work: Path) -> Path:
    """把成品包取到全新目录(目录→复制,压缩包→解压),返回其中的程序目录。"""
    if package.is_dir():
        copy = work / package.name
        shutil.copytree(package, copy)
        for rel in _NOT_SHIPPED:
            target = copy / rel
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
    elif package.suffix == ".zip":
        with zipfile.ZipFile(package) as zf:
            zf.extractall(work)
    else:
        with tarfile.open(package) as tf:
            tf.extractall(work, filter="data")
    found = [d for d in work.rglob("*") if (d / WIN_EXE).exists() or (d / LINUX_EXE).exists()]
    if len(found) != 1:
        sys.exit(f"在 {package} 中没有找到唯一的程序目录(找到 {len(found)} 个)")
    return found[0]


class Runner:
    """在本机或干净容器里启动成品程序。"""

    def __init__(self, app_dir: Path, image: str | None) -> None:
        self.app_dir, self.image = app_dir, image
        self.exe = WIN_EXE if sys.platform == "win32" else LINUX_EXE
        self.container: str | None = None  # 仅容器模式使用
        self._seq = itertools.count()

    def command(self, *args: str, env: dict | None = None) -> list[str]:
        """成品程序的完整命令行。"""
        if not self.image:
            return [str(self.app_dir / self.exe), *args]
        # 每个进程一个容器名:--rm 的清理是异步的,沿用旧名字会报"名字已被占用"
        self.container = f"patrol-smoke-{os.getpid()}-{next(self._seq)}"
        cmd = ["docker", "run", "--rm", "--network", "host", "--name", self.container,
               "--user", f"{os.getuid()}:{os.getgid()}"]
        for key, value in {**(env or {}), "HOME": "/tmp"}.items():  # 以普通用户身份运行时 /root 不可写
            cmd += ["-e", f"{key}={value}"]
        cmd += ["-v", f"{self.app_dir.parent}:/work", "-w", f"/work/{self.app_dir.name}",
                self.image, f"./{self.exe}", *args]
        return cmd

    def _popen(self, argv: list[str], **kwargs) -> subprocess.Popen:
        proc = subprocess.Popen(argv, cwd=self.app_dir, **kwargs)
        proc.container = self.container  # type: ignore[attr-defined]
        return proc

    def run(self, *args: str, timeout: int = 300) -> tuple[int, str]:
        """跑到结束,返回 (退出码, 输出);超时则终止并返回退出码 -1。"""
        proc = self._popen(self.command(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            out, _ = proc.communicate(timeout=timeout)
            return proc.returncode, out.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            self.stop(proc)
            return -1, f"超过 {timeout} 秒未结束,已终止"

    def spawn(self, *args: str, env: dict | None = None, log: BinaryIO) -> subprocess.Popen:
        """后台启动(不传 args 即不带参数启动),输出写入 log。"""
        return self._popen(self.command(*args, env=env), env={**os.environ, **(env or {})},
                           stdout=log, stderr=subprocess.STDOUT,
                           start_new_session=sys.platform != "win32")

    def stop(self, proc: subprocess.Popen) -> None:
        """onefile 有父子两个进程:Windows 按进程树结束,Linux 按进程组结束。"""
        if self.image:
            subprocess.run(["docker", "stop", "-t", "5", proc.container],  # type: ignore[attr-defined]
                           capture_output=True, timeout=120)
        elif sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=120)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # 让 3xx 以异常形式返回给调用方,由调用方判定状态码


class Client:
    """带登录状态的极简 HTTP 客户端:request() 返回 (状态码, 正文)。"""

    def __init__(self, base: str) -> None:
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())

    def request(self, method: str, path: str, data=None) -> tuple[int, str]:
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method)
        try:
            with self.opener.open(req, timeout=15) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def get(self, path: str) -> tuple[int, str]:
        return self.request("GET", path)

    def post(self, path: str, data: dict) -> tuple[int, str]:
        return self.request("POST", path, data)

    def wait_ready(self, path: str, seconds: int) -> bool:
        for _ in range(seconds):
            try:
                if self.get(path)[0] == 200:
                    return True
            except OSError:  # 服务尚未起来时连接被拒绝,继续等
                pass
            time.sleep(1)
        return False

    def wait_task(self, seconds: int) -> str:
        """轮询任务页,返回首个任务的状态:completed / partial / failed / 其他。"""
        for _ in range(seconds):
            table = re.search(r"<table.*?</table>", self.get("/ui/tasks")[1], re.S)
            table = table.group(0) if table else ""
            if table and "bg-primary" not in table:  # 不再有"运行中"徽标
                if 'bg-success">完成' in table:
                    return "completed"
                return "partial" if "台异常" in table else "failed"
            time.sleep(1)
        return "timeout"


def reports(app_dir: Path) -> list[Path]:
    return sorted((app_dir / "output").glob("patrol_*.json"))


def report_problem(path: Path) -> str:
    """报告合格返回空串;否则返回原因(设备数不对 / 有采集错误 / 没有任何判定)。"""
    devices = json.loads(path.read_text(encoding="utf-8"))["devices"]
    problems = [f"{d['name']}:{d['error'] or '没有任何已判定的检查项'}" for d in devices
                if d["error"] or d["pass_count"] + d["fail_count"] == 0]
    if len(devices) != len(SEEDS):
        problems.insert(0, f"报告里只有 {len(devices)} 台设备")
    return ";".join(problems)


def cli_patrol(runner: Runner) -> None:
    print("\n== 命令行:巡检 3 台模拟设备 ==")
    started = time.time()
    code, out = runner.run("run")
    check(code == 2, "退出码 = 2(巡检成功且有异常项)", f"退出码 = {code}\n{tail(out)}")
    produced = reports(runner.app_dir)
    if not produced:
        check(False, "生成报告文件", tail(out))
        return
    problem = report_problem(produced[-1])
    check(not problem, "报告含 3 台设备,全部采集成功且有判定", problem or tail(out))
    check(produced[-1].with_suffix(".html").exists(), "生成 HTML 报告(用到报告模板)")
    # Word 报告另有命名规则:副本是全新的,只要出现了就是本次产出
    check(any((runner.app_dir / "output").glob("*.docx")), "生成 Word 报告(用到 docx 模板)")
    print(f"       用时 {time.time() - started:.0f}s,报告 {produced[-1].name}")


def _web_env(port: int) -> dict[str, str]:
    return {"PATROL_PORT": str(port), "PATROL_NO_BROWSER": "1"}


def auto_web(runner: Runner, work: Path) -> None:
    """不带参数启动:没有图形界面时应转 Web 模式,而不是崩掉。"""
    print("\n== 不带参数启动:自动转 Web 模式 ==")
    port, log_path = free_port(), work / "auto-web.log"
    with open(log_path, "wb") as log:
        proc = runner.spawn(env=_web_env(port), log=log)
        try:
            if Client(f"http://127.0.0.1:{port}").wait_ready("/ui/login", 90):
                check(True, "自动转 Web 模式,登录页可访问")
            else:
                log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
                check(False, "自动转 Web 模式,登录页可访问", log_tail)
        finally:
            runner.stop(proc)


def web_patrol(runner: Runner, names: list[str], work: Path) -> None:
    print("\n== 网页端:登录 → 发起合并巡检 → 任务状态 ==")
    port, log_path = free_port(), work / "web.log"
    before = set(reports(runner.app_dir))
    with open(log_path, "wb") as log:
        proc = runner.spawn("--web", env=_web_env(port), log=log)
        try:
            client = Client(f"http://127.0.0.1:{port}")
            if not client.wait_ready("/ui/login", 90):
                log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
                check(False, "Web 服务启动,登录页可访问", log_tail)
                return
            check(True, "Web 服务启动,登录页可访问")
            check("登录" in client.get("/ui/login")[1], "登录页由页面模板渲染")
            check(client.get("/static/logo.png")[0] == 200, "静态资源可访问")
            check(client.get("/ui")[0] == 302, "未登录访问 /ui 跳转登录页")
            check(client.get("/devices")[0] == 401, "未登录访问接口被拒")
            check(client.post("/ui/login", {"username": "admin", "password": "admin123"})[0] == 303,
                  "默认账号登录")
            status, body = client.get("/devices")
            try:
                listed = sorted(d["name"] for d in json.loads(body))
            except ValueError:
                listed = []
            check(listed == sorted(names), "设备库是首次运行导入的 3 台模拟设备",
                  f"HTTP {status}: {body[:200]}")
            check(client.post("/ui/tasks", {"device_names": names})[0] == 303, "发起合并巡检")
            state = client.wait_task(240)
            check(state == "completed", "任务状态为完成(未失败、无采集异常)", f"任务状态:{state}")
            new = [p for p in reports(runner.app_dir) if p not in before]
            problem = report_problem(new[-1]) if new else "没有产出新报告"
            check(not problem, "产出新报告,3 台设备全部采集成功", problem)
            status, page = client.get("/ui")
            check(status == 200 and "昊云网络巡检助手" in page, "首页可访问", f"HTTP {status}")
        finally:
            runner.stop(proc)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cleanup(work: Path, extracted_before: set[str]) -> None:
    """清掉本次运行留下的临时目录(Windows 上强制结束进程后不会自行消失的两类)。

    一是包的副本:镜像文件在进程消失后还会被占用片刻(杀毒软件扫描新生成的文件时
    更久,时长不定),要重试,删不掉时明说而不是静默留下;
    二是单文件程序运行时解压到系统临时目录的 _MEI*,只有正常退出才会自己清掉——
    只处理本次运行期间新出现的,且先改名确认没有进程在用(被占用时改名会失败)。
    """
    for _ in range(30):
        shutil.rmtree(work, ignore_errors=True)
        if not work.exists():
            break
        time.sleep(0.5)
    if work.exists():
        print(f"提示:临时目录 {work} 仍被占用,未能自动清理,可稍后手动删除")
    for path in Path(tempfile.gettempdir()).glob("_MEI*"):
        if str(path) in extracted_before:
            continue
        try:
            path.rename(path.with_name(path.name + ".smoke"))
        except OSError:
            continue
        shutil.rmtree(path.with_name(path.name + ".smoke"), ignore_errors=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", nargs="?", help="包目录或 .zip/.tar.gz;默认取 dist 下刚构建的包")
    ap.add_argument("--image", help="把程序放进指定的干净容器里跑(仅 Linux 宿主机,需要 docker)")
    args = ap.parse_args()
    if args.image and sys.platform != "linux":
        sys.exit("--image 仅支持在 Linux 宿主机上使用")
    default = ROOT / "dist" / (WIN_DIR if sys.platform == "win32" else f"linux/haoyun-patrol")
    package = Path(args.package) if args.package else default

    work = Path(tempfile.mkdtemp(prefix="patrol-smoke-"))
    extracted_before = {str(p) for p in Path(tempfile.gettempdir()).glob("_MEI*")}
    servers: list[SimDeviceServer] = []
    try:
        app_dir = fetch(package, work)
        runner = Runner(app_dir, args.image)
        names, devices = [], []
        for seed, vendor, device_type in SEEDS:
            server = SimDeviceServer(responses=responses_from_seed(seed))
            servers.append(server)
            names.append(f"模拟-{seed}")
            devices.append({"name": names[-1], "host": "127.0.0.1", "port": server.start(),
                            "vendor": vendor, "device_type": device_type, "login_method": "telnet",
                            "username": "any", "password": "any", "timeout": 8, "command_timeout": 15})
        # 设备清单换成模拟设备(仅这份副本;首次运行时导入设备库)
        (app_dir / "config" / "devices.yaml").write_text("devices:\n" + "".join(
            "- {" + ", ".join(f"{k}: {v!r}" for k, v in d.items()) + "}\n" for d in devices),
            encoding="utf-8")
        print(f"成品包:{package}\n运行方式:{'容器 ' + args.image if args.image else '本机直接运行'}")
        if sys.platform != "win32":  # Windows 不带参数启动的是桌面小工具
            auto_web(runner, work)
        cli_patrol(runner)
        web_patrol(runner, names, work)
    finally:
        for server in servers:
            server.stop()
        cleanup(work, extracted_before)
    print(f"\n成品全链路冒烟:{_passed} 项通过,{_failed} 项失败")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

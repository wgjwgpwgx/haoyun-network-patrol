"""pytest 公共 fixtures"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 全局隔离:测试进程的工作目录切到临时副本。patrol.api.app 导入时即执行
# bootstrap() 绑定相对路径 data/patrol.db,历史库与 output/ 同为相对路径——
# 不隔离则每跑一次测试都会往真实库写审计行、往真实报告目录写文件。
# config/ 只复制规则与样式等非敏感配置,不复制真实设备/客户/登录凭据。
#
# 切目录放在 pytest_configure:早于"收集并导入测试模块"。
# 注意 pytest 8.x 的 --ignore / --ignore-glob 是在收集阶段按当时的工作目录解析的,
# 切目录之后再写在命令行上就会失效——排除整个目录要用下面的 collect_ignore_glob。
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEST_WORKDIR = Path(tempfile.mkdtemp(prefix="patrol-tests-"))
atexit.register(shutil.rmtree, _TEST_WORKDIR, ignore_errors=True)


def pytest_configure(config) -> None:
    shutil.copytree(
        _REPO_ROOT / "config", _TEST_WORKDIR / "config",
        ignore=shutil.ignore_patterns("auth.yaml", "devices.yaml", "customers.yaml"))
    os.chdir(_TEST_WORKDIR)


if sys.platform != "win32":
    # 桌面用例需要真实窗口(以及 Windows 计划任务等平台能力):非 Windows 的 CI 没有
    # 显示环境,整个目录不收集。相对本文件所在目录,不受上面切换工作目录的影响。
    collect_ignore_glob = ["test_desktop/*"]

import pytest  # noqa: E402

from patrol.analyzer.engine import RuleEngine  # noqa: E402
from patrol.models import DeviceAsset  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RULES_FILE = Path(__file__).parent.parent / "config" / "rules" / "default.yaml"


@pytest.fixture
def h3c_fixtures() -> Path:
    """H3C Comware 交换机测试回显文件目录。"""
    return FIXTURES_DIR / "h3c" / "comware_switch"


@pytest.fixture
def load_fixture(h3c_fixtures: Path):
    """加载回显文件的辅助函数。"""
    def _load(filename: str) -> str:
        return (h3c_fixtures / filename).read_text(encoding="utf-8")
    return _load


@pytest.fixture
def sample_asset() -> DeviceAsset:
    """一台示例设备资产，用于测试。"""
    return DeviceAsset(
        name="测试交换机",
        host="192.168.1.1",
        vendor="h3c",
        device_type="comware_switch",
        port=22,
        username="admin",
        password="test123",
        enabled=True,
        timeout=30,
        command_timeout=60,
    )


@pytest.fixture
def rule_engine() -> RuleEngine:
    """加载默认规则的 RuleEngine 实例。"""
    rules = RuleEngine.load_file(RULES_FILE)
    return RuleEngine(rules)


@pytest.fixture(autouse=True)
def _web_auth_off(request, monkeypatch):
    """默认关闭 Web 登录认证,既有用例不受影响;test_auth.py 自行管理认证状态。"""
    mod = getattr(request.node.module, "__name__", "") or ""
    if mod.endswith("test_auth"):
        return
    monkeypatch.setattr("patrol.api.auth.auth_enabled", lambda: False)

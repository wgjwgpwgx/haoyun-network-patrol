"""定时巡检计划任务测试(销号清单 #13b)"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from patrol.desktop import service


def test_tr_wraps_cd_and_run():
    tr = service._schedule_tr()
    assert tr.startswith("cmd /c cd /d ")
    assert ("run" in tr) or ("-m patrol" in tr)


def test_schedule_status_non_windows():
    """非 Windows:schtasks 不存在,直接返回未安装(不抛 FileNotFoundError)。"""
    with patch("sys.platform", "linux"):
        assert service.schedule_status() == {"installed": False, "weekly": False}


def test_install_weekly_args():
    with patch("subprocess.run") as m:
        m.return_value.returncode = 0
        service.install_schedule(weekly=True)
    args = m.call_args.args[0]
    assert args[:3] == ["schtasks", "/Create", "/F"]
    assert "/SC" in args and "WEEKLY" in args and "WED" in args
    assert "02:00" in args


def test_install_monthly_args():
    with patch("subprocess.run") as m:
        m.return_value.returncode = 0
        service.install_schedule(weekly=False)
    args = m.call_args.args[0]
    assert "MONTHLY" in args


def test_install_failure_raises():
    with patch("subprocess.run") as m:
        m.return_value.returncode = 1
        m.return_value.stderr = "access denied"
        with pytest.raises(RuntimeError, match="创建失败"):
            service.install_schedule()


def test_remove_silent():
    with patch("subprocess.run") as m:
        m.return_value.returncode = 0
        service.remove_schedule()
    assert "/Delete" in m.call_args.args[0]


def test_status_installed():
    with patch("subprocess.run") as m:
        m.return_value.returncode = 0
        m.return_value.stdout = "每周 WED"
        st = service.schedule_status()
    assert st["installed"] is True

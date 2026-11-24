"""后台巡检任务执行器

在独立线程中执行巡检，不阻塞 HTTP 请求。
任务状态：pending → running → completed / failed
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from patrol.analyzer.engine import RuleEngine
from patrol.api.schemas import TaskOut
from patrol.api.store import DeviceStore, TaskStore
from patrol.cli import run_inspection
from patrol.drivers.registry import get_driver
from patrol.models import DeviceAsset, DeviceReport, PatrolReport

logger = logging.getLogger(__name__)


def _fallback_asset(cfg: dict[str, Any]) -> DeviceAsset:
    """档案非法时的最小合法档案,保证错误信息有载体进报告与历史。"""
    return DeviceAsset(
        name=str(cfg.get("name") or "未命名设备")[:100], host="127.0.0.1",
        customer=str(cfg.get("customer") or "")[:100],
        vendor=str(cfg.get("vendor") or ""), device_type=str(cfg.get("device_type") or ""),
    )


class TaskManager:
    """巡检任务管理器"""

    def __init__(
        self,
        device_store: DeviceStore,
        task_store: TaskStore,
        rules_path: str = "config/rules",
        output_dir: str = "output",
    ) -> None:
        self._devices = device_store
        self._tasks = task_store
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        # 加载规则:目录则合并其下全部规则文件(厂商专项优先于通配),
        # 单文件则只加载该文件(脚本/测试显式指定的场景)
        try:
            if Path(rules_path).is_dir():
                rules = RuleEngine.load_dir(rules_path)
            else:
                rules = RuleEngine.load_file(rules_path)
            self._engine = RuleEngine(rules)
        except FileNotFoundError:
            logger.warning("规则文件不存在: %s，将使用空规则集", rules_path)
            self._engine = RuleEngine([])
        # 线程池（单线程，串行执行巡检任务）
        # P1:默认 3 路并发;PATROL_CONCURRENCY=1 可退回串行保护老设备
        import os
        workers = max(1, int(os.environ.get("PATROL_CONCURRENCY", "3")))
        self._executor = ThreadPoolExecutor(max_workers=workers)

    def create_task(self, device_name: str) -> TaskOut:
        """创建单设备巡检任务(兼容入口):等价于只选一台的合并巡检。"""
        return self.create_batch_task([device_name])

    def create_batch_task(self, device_names: list[str]) -> TaskOut:
        """创建合并巡检任务:一次选 N 台,产出一份整体报告(乙方交付形态)。"""
        if not device_names:
            raise KeyError("未选择任何设备")
        cfgs = []
        for name in device_names:
            device_cfg = self._devices.get(name)
            if device_cfg is None:
                raise KeyError(f"设备不存在: {name}")
            cfgs.append(device_cfg)

        task_id = uuid.uuid4().hex[:16]
        now = datetime.now().isoformat()

        # 单台沿用设备名/IP;多台显示合并标签,任务列表一眼可辨
        if len(cfgs) == 1:
            label, host = device_names[0], str(cfgs[0].get("host", ""))
        else:
            label = f"{len(cfgs)} 台设备合并巡检"
            host = f"共 {len(cfgs)} 台"

        task_data: dict[str, Any] = {
            "task_id": task_id,
            "device_name": label,
            "device_host": host,
            "device_names": list(device_names),  # 合并任务的成员(导出/分发时取客户)
            "status": "pending",
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "report_file": None,
            "error": None,
            "error_count": 0,
        }
        self._tasks.create(task_id, task_data)

        # 提交到线程池
        self._executor.submit(self._run_task, task_id, cfgs)

        return TaskOut(**task_data)

    def _inspect_one(self, cfg: dict[str, Any]) -> tuple[DeviceAsset, DeviceReport]:
        """单台巡检。档案非法或未注册驱动只让这一台报错,不拖垮同批其他设备。"""
        try:
            asset = DeviceAsset(**cfg)
        except Exception as e:  # noqa: BLE001 - 档案非法不波及整批
            asset = _fallback_asset(cfg)
            return asset, DeviceReport(asset=asset, error=f"设备档案非法: {e}")
        try:
            report = run_inspection(
                asset, get_driver(asset.vendor, asset.device_type), self._engine)
        except Exception as e:  # noqa: BLE001 - 单台未预期异常隔离在单台
            logger.error("巡检异常 [%s]: %s", asset.name, e, exc_info=True)
            report = DeviceReport(asset=asset, error=f"巡检异常: {e}")
        return asset, report

    def _run_task(self, task_id: str, device_cfgs: list[dict[str, Any]]) -> None:
        """在线程中执行巡检:逐台采集,合并为一份报告文件。"""
        self._tasks.update(task_id, {
            "status": "running",
            "started_at": datetime.now().isoformat(),
        })

        try:
            results = [self._inspect_one(cfg) for cfg in device_cfgs]
            reports = [r for _, r in results]

            # 生成报告文件:一台用主机名,多台用"N台设备合并"(host 已校验,再消毒一层)
            from patrol.utils.filename import safe_component

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            label = (safe_component(results[0][0].host) if len(reports) == 1
                     else f"{len(reports)}台设备合并")
            filename = f"patrol_{label}_{ts}.html"
            report_path = self._output_dir / filename

            from patrol.reporter.html import HTMLReporter

            patrol_report = PatrolReport(
                title="网络设备巡检报告", devices=reports
            )

            # 巡检历史先入库再出报告:报告里的趋势图与预测才包含本期
            try:
                from patrol.storage.history import HistoryStore, save_report_runs
                save_report_runs(HistoryStore(), results, report_file=filename)
            except Exception as e:  # noqa: BLE001 - 历史失败不影响主流程
                logger.warning("巡检历史入库失败: %s", e)

            # AI 大模型分析(未配置/失败均不影响巡检产出)
            ai_analyzed = False
            try:
                from patrol.ai import AINotConfigured, analyze_report, load_ai_config
                ai_cfg = load_ai_config()
                if ai_cfg.ready:
                    patrol_report.ai_analysis = analyze_report(
                        patrol_report, ai_cfg
                    )
                    ai_analyzed = True
            except AINotConfigured:
                pass
            except Exception as e:  # noqa: BLE001 - AI 失败不阻塞巡检
                logger.warning("AI 分析失败(巡检结果不受影响): %s", e)

            HTMLReporter().generate(patrol_report, report_path)

            # 全部设备都采集失败 → 如实标 failed(报告仍保留,可点开看各台原因);
            # 部分失败 → completed 并记录异常台数,界面可见
            failed = sum(1 for r in reports if r.error)
            all_failed = failed == len(reports)
            self._tasks.update(task_id, {
                "status": "failed" if all_failed else "completed",
                "finished_at": datetime.now().isoformat(),
                "report_file": filename,
                "ai_analyzed": ai_analyzed,
                "error_count": failed,
                **({"error": f"全部 {failed} 台设备无法采集,详见报告"}
                   if all_failed else {}),
            })
            logger.info("巡检任务完成: %s → %s(共 %d 台,采集异常 %d 台)",
                        task_id, filename, len(reports), failed)

        except Exception as e:
            self._tasks.update(task_id, {
                "status": "failed",
                "finished_at": datetime.now().isoformat(),
                "error": str(e),
            })
            logger.error("巡检任务失败: %s - %s", task_id, e)

    def reconcile_interrupted(self) -> int:
        """启动时对账:上次退出时未跑完的任务标为已中断,返回处理条数。"""
        count = 0
        for t in self._tasks.list_all():
            if t.get("status") in ("pending", "running"):
                self._tasks.update(t.get("task_id", ""), {
                    "status": "failed",
                    "finished_at": datetime.now().isoformat(),
                    "error": "程序退出时任务被中断,请重新发起",
                })
                count += 1
        return count

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

"""CLI 入口 - 命令行巡检工具

流程：
  加载 YAML 配置 → 加载规则 → 构造 DeviceAsset → 选择 Collector →
  连接设备 → Driver 获取命令 → 逐条采集 → Driver 解析 → 规则引擎判定 → 报告
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from patrol.analyzer.engine import RuleEngine, expand_parsed
from patrol.collector.base import BaseCollector
from patrol.collector.ssh import (
    SSHAuthenticationError,
    SSHCollector,
    SSHCommandError,
    SSHConnectionError,
)
from patrol.drivers.base import BaseDriver
from patrol.drivers.registry import get_driver

# 确保全部驱动已注册(drivers/__init__.py 统一导入)
import patrol.drivers  # noqa: F401
from patrol.models import CheckItem, CheckStatus, DeviceAsset, DeviceReport, PatrolReport
from patrol.reporter.html import HTMLReporter
from patrol.utils.logging import setup_logging

logger = logging.getLogger(__name__)

# 设备对"命令不支持 / 无权限 / 参数错误"的标准报错(华为、H3C、锐捷、中兴、
# 迈普及类 IOS 的 CLI 文案)。只认行数很少的回显,日志、告警等长输出不受影响。
_COMMAND_ERROR = re.compile(
    r"Unrecognized command|Unknown command|Invalid input|Incomplete command"
    r"|Ambiguous command|Wrong parameter|Too many parameters|Invalid parameter"
    r"|Command incomplete|Permission denied|command not found"
    r"|Authorization failed|Access rejected|No permission|not authorized",
    re.IGNORECASE,
)


def _is_command_error(raw_output: str) -> bool:
    """短回显里出现设备标准报错 → 该命令实际没有执行成功。"""
    lines = [ln for ln in raw_output.splitlines() if ln.strip()]
    return 0 < len(lines) <= 5 and bool(_COMMAND_ERROR.search(raw_output))


def load_config(config_path: str) -> dict[str, Any]:
    """加载 YAML 配置文件。"""
    path = Path(config_path)
    if not path.exists():
        print(f"错误: 配置文件不存在: {config_path}", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_assets(config: dict[str, Any]) -> list[DeviceAsset]:
    """从配置中构造 DeviceAsset 列表，跳过 disabled 设备。"""
    assets: list[DeviceAsset] = []
    for raw in config.get("devices", []):
        asset = DeviceAsset(**raw)
        if not asset.enabled:
            logger.info("跳过禁用设备: %s", asset.name)
            continue
        assets.append(asset)
    return assets


def _create_collector(asset: DeviceAsset) -> BaseCollector:
    """根据 login_method 创建对应的采集器。"""
    if asset.login_method in ("ssh", "telnet", "console"):
        # Telnet / Console(串口)与 SSH 同走 netmiko 采集器,
        # 通道类型由采集器按登录方式解析(见 _resolve_netmiko_device_type)
        return SSHCollector()
    elif asset.login_method == "web":
        from patrol.collector.web import WebCollector
        return WebCollector()
    elif asset.login_method == "api":
        from patrol.collector.api import APICollector
        return APICollector()
    elif asset.login_method == "snmp":
        from patrol.collector.snmp import SNMPCollector
        return SNMPCollector()
    else:
        raise ValueError(f"不支持的采集方式: {asset.login_method}")


def _connect_collector(
    collector: BaseCollector, asset: DeviceAsset, report: DeviceReport
) -> bool:
    """连接设备，失败时设置 report.error 并返回 False。"""
    try:
        collector.connect(asset)
        return True
    except Exception as e:
        report.error = str(e)
        logger.error("连接失败 [%s] %s: %s", asset.login_method, asset.name, e)
        return False


def run_inspection(
    asset: DeviceAsset,
    driver: BaseDriver,
    engine: RuleEngine,
    incremental: bool = False,
) -> DeviceReport:
    """对单台设备执行巡检。

    流程: 选择 Collector → 连接 → 逐条采集 → Driver 解析 → 规则引擎判定
    incremental=True 时快速模式:只跑核心项+上次异常项(跳过稳定项)。
    """
    report = DeviceReport(asset=asset)

    # 根据采集方式创建 Collector
    try:
        collector = _create_collector(asset)
    except ValueError as e:
        report.error = str(e)
        return report

    # 连接设备
    if not _connect_collector(collector, asset, report):
        return report

    # 采集设备基本信息（用于报告头部展示，不走规则引擎）
    try:
        try:
            version_cmd = driver.get_check_commands()[0]  # 第一条命令通常是 version
            version_output = collector.execute(
                version_cmd.command, timeout=asset.command_timeout
            )
            info_parsed = driver.parse_output("device_info", version_output)
            if info_parsed.success:
                report.model = info_parsed.parsed.get("model", "")
                report.software_version = info_parsed.parsed.get("software_version", "")
                report.uptime = info_parsed.parsed.get("uptime", "")
                report.serial_number = info_parsed.parsed.get("serial_number", "")
                report.check_items.append(CheckItem(
                    name="device_info",
                    category="基本信息",
                    command=version_cmd.command,
                    raw_output=version_output,
                    status=CheckStatus.PASS,
                    message=(
                        f"型号: {report.model or '未知'}, "
                        f"版本: {report.software_version or '未知'}, "
                        f"运行时间: {report.uptime or '未知'}"
                    ),
                    details=info_parsed.parsed,
                ))
        except Exception as e:
            logger.warning("获取设备信息失败: %s", e)

        # Web 采集时截图留证
        if asset.login_method == "web" and asset.screenshot:
            try:
                from patrol.collector.web import WebCollector
                if isinstance(collector, WebCollector):
                    collector.take_screenshot("overview")
            except Exception:
                pass

        # 增量模式:筛选检查项子集(核心+上次异常)
        check_commands = driver.get_check_commands()
        if incremental:
            from patrol.incremental import get_incremental_checks
            check_commands = get_incremental_checks(
                asset.vendor, asset.device_type, check_commands)

        # 执行规则化的检查项（跳过 device_info）
        for cmd_def in check_commands:
            if cmd_def.name == "device_info":
                continue

            logger.info("[%s] 执行: %s (%s)", asset.host, cmd_def.name, cmd_def.command)
            try:
                raw_output = collector.execute(
                    cmd_def.command, timeout=asset.command_timeout
                )
            except Exception as e:
                report.check_items.append(CheckItem(
                    name=cmd_def.name,
                    category=cmd_def.category,
                    command=cmd_def.command,
                    raw_output="",
                    status=CheckStatus.UNKNOWN,
                    message=f"采集失败: {e}",
                ))
                logger.warning("采集失败 %s: %s", cmd_def.command, e)
                continue

            # 设备回的是标准报错(命令不支持/无权限/参数错):命令并未真正执行。
            # 既不能进解析器(报错文本会被当成数据,接口/温度等计数型项会误判通过),
            # 也不能当配置快照留存(否则下一期会报出虚假的"配置变更")
            if _is_command_error(raw_output):
                report.check_items.append(CheckItem(
                    name=cmd_def.name,
                    category=cmd_def.category,
                    command=cmd_def.command,
                    raw_output=raw_output,
                    status=CheckStatus.UNKNOWN,
                    message="设备不支持该命令或无权限执行,无法判定",
                ))
                logger.warning("命令未被设备接受 %s: %s", cmd_def.command,
                               raw_output.strip()[:80])
                continue

            # 配置快照留存(销号清单 #9:供下期 diff 与审计)
            if cmd_def.name == "config_cur":
                try:
                    from patrol.utils.config_snapshot import save_config_snapshot
                    save_config_snapshot(asset.name, raw_output)
                except Exception:  # noqa: BLE001 - 快照失败不影响巡检
                    logger.debug("配置快照保存失败", exc_info=True)

            # Driver 解析(失败或"软失败"(关键字段全空)时回退到
            # 已入库的解析器 Copilot 规则;0 视为有效值不算空)
            parsed = driver.parse_output(cmd_def.name, raw_output)
            soft_empty = parsed.success and not any(
                v for v in parsed.parsed.values() if v not in (0, []))
            if not parsed.success or soft_empty:
                try:
                    from patrol.parser_copilot import apply_saved_rule
                    saved = apply_saved_rule(
                        asset.vendor, asset.device_type, cmd_def.name,
                        raw_output, category=cmd_def.category,
                        command=cmd_def.command)
                    if saved is not None:
                        parsed = saved
                        soft_empty = False
                        logger.info("[%s] %s: 命中 Copilot 规则",
                                    asset.host, cmd_def.name)
                except Exception:  # noqa: BLE001 - 回退失败保持原结果
                    logger.debug("Copilot 回退失败", exc_info=True)
                if soft_empty:
                    # 回显为空 / 命令不被设备支持 / 格式未识别,且无已存解析规则:
                    # 不能让解析器的默认值(计数为 0)被判成"检查通过",如实记 UNKNOWN
                    report.check_items.append(CheckItem(
                        name=cmd_def.name,
                        category=cmd_def.category,
                        command=cmd_def.command,
                        raw_output=raw_output,
                        status=CheckStatus.UNKNOWN,
                        message="回显为空或格式未识别,无法判定",
                    ))
                    continue

            # 展开嵌套检查(如配置解析的 telnet/snmp/vty/stp)后逐项规则判定
            known = {x.strip() for x in asset.known_issues.split(",")
                     if x.strip()}
            for pr in expand_parsed(parsed):
                check_item = engine.evaluate(
                    pr, vendor=asset.vendor, device_type=asset.device_type
                )
                # 已知异常白名单:FAIL 但属预期行为 → 不计异常
                if known and check_item.name in known and                         check_item.status == CheckStatus.FAIL:
                    check_item = CheckItem(
                        name=check_item.name,
                        category=check_item.category,
                        command=check_item.command,
                        raw_output=check_item.raw_output,
                        status=CheckStatus.PASS,
                        message=f"已知异常(预期行为): {check_item.message}",
                        details=check_item.details,
                    )
                report.check_items.append(check_item)
                logger.info(
                    "[%s] %s: %s", asset.host, check_item.name, check_item.status.value
                )
    finally:
        # 无论中途是否异常都断开连接,避免 SSH 会话/浏览器泄漏
        try:
            collector.disconnect()
        except Exception:
            logger.debug("断开连接失败", exc_info=True)
        # 知识库自动沉淀:该设备本次全部命令回显全量入库
        try:
            from patrol.knowledge import save_snapshot
            save_snapshot(
                {"customer": asset.customer, "name": asset.name,
                 "host": asset.host, "vendor": asset.vendor,
                 "device_type": asset.device_type,
                 "model": report.model,
                 "software_version": report.software_version},
                [{"name": it.name, "command": it.command,
                  "raw_output": it.raw_output}
                 for it in report.check_items],
                source="patrol", error=report.error)
        except Exception:  # noqa: BLE001 - 沉淀失败不影响巡检
            logger.debug("知识库沉淀失败", exc_info=True)
    return report


def main() -> None:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(description="网络设备巡检助手 - SSH 巡检工具")
    parser.add_argument(
        "command", nargs="?", choices=["run"],
        help="兼容写法 `patrol run`,与不带参数等价(供计划任务/快捷方式使用)",
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="可选:从指定设备 YAML 读取设备(默认:与界面共用的设备库)",
    )
    parser.add_argument(
        "-r", "--rules",
        default="config/rules",
        help="规则文件或目录 (默认: config/rules 目录,合并加载其下全部规则)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="报告输出目录 (默认: ./output)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细日志输出",
    )
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    # 设备来源:默认与桌面/Web 共用同一设备库(SQLite);显式 -c 时读指定 YAML
    if args.config:
        config = load_config(args.config)
        assets = build_assets(config)
        title = config.get("title", "网络设备巡检报告")
    else:
        from patrol.storage.sqlstore import bootstrap
        dev_store, _, _, _ = bootstrap()
        assets = []
        for d in dev_store.list():
            try:
                asset = DeviceAsset(**d)
            except Exception as e:  # noqa: BLE001 - 单条档案非法不阻断巡检
                logger.error("设备档案非法,已跳过 [%s]: %s", d.get("name"), e)
                continue
            if asset.enabled:
                assets.append(asset)
        title = "网络设备巡检报告"

    # 加载规则:目录则合并其下全部规则(厂商专项优先于通配),文件则只加载该文件
    try:
        rules = (RuleEngine.load_dir(args.rules) if Path(args.rules).is_dir()
                 else RuleEngine.load_file(args.rules))
        engine = RuleEngine(rules)
        logger.info("已加载 %d 条规则", len(rules))
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if not assets:
        print("错误: 没有启用的设备", file=sys.stderr)
        sys.exit(1)

    # 输出目录
    output_dir = Path(args.output) if args.output else Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 执行巡检
    patrol_report = PatrolReport(title=title)

    import os
    from concurrent.futures import ThreadPoolExecutor

    def _inspect_one(asset: DeviceAsset) -> DeviceReport:
        logger.info("开始巡检: %s (%s)", asset.name, asset.host)
        try:
            driver = get_driver(asset.vendor, asset.device_type)
        except KeyError as e:
            logger.error("获取 Driver 失败: %s", e)
            return DeviceReport(asset=asset, error=str(e))
        return run_inspection(asset, driver, engine)

    workers = max(1, min(int(os.environ.get("PATROL_CONCURRENCY", "3")),
                         len(assets)))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            patrol_report.devices.extend(pool.map(_inspect_one, assets))
    else:
        for asset in assets:
            patrol_report.devices.append(_inspect_one(asset))

    # AI 大模型分析(配置于 config/ai.yaml;未配置/失败不影响报告产出)
    try:
        from patrol.ai import AINotConfigured, analyze_report, load_ai_config
        ai_cfg = load_ai_config()
        if ai_cfg.ready:
            print("\n正在进行 AI 大模型分析...")
            patrol_report.ai_analysis = analyze_report(patrol_report, ai_cfg)
            print(f"  AI 分析完成: 健康评分 {patrol_report.ai_analysis['health_score']}"
                  f" · 风险等级 {patrol_report.ai_analysis['overall_risk']}")
    except AINotConfigured:
        pass
    except Exception as e:  # noqa: BLE001 - AI 失败不阻塞巡检
        logger.warning("AI 分析失败(巡检结果不受影响): %s", e)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = output_dir / f"patrol_{timestamp}.html"

    # 巡检历史入库(P1-3:含指标值,供趋势图;先入库后出报告,趋势含本期)
    try:
        from patrol.storage.history import HistoryStore, save_report_runs
        save_report_runs(HistoryStore(),
                         [(d.asset, d) for d in patrol_report.devices],
                         report_file=html_path.name)
    except Exception as e:  # noqa: BLE001
        logger.warning("巡检历史入库失败: %s", e)

    # 生成报告（HTML + Word）
    reporter = HTMLReporter()
    reporter.generate(patrol_report, html_path)

    from patrol.reporter.word import (
        WordReporter, build_report_meta, generate_word_filename,
    )
    word_filename = generate_word_filename(patrol_report)
    word_path = output_dir / word_filename
    WordReporter().generate(patrol_report, word_path,
                            meta=build_report_meta(patrol_report))

    # PDF 报告（如果环境支持）
    pdf_generated = False
    try:
        from patrol.reporter.pdf import PDFReporter, generate_pdf_filename
        pdf_filename = generate_pdf_filename(patrol_report)
        pdf_path = output_dir / pdf_filename
        PDFReporter().generate(patrol_report, pdf_path)
        pdf_generated = True
    except Exception as e:
        logger.warning("PDF 报告生成失败（可忽略）: %s", e)

    # 输出摘要
    print(f"\n巡检完成:")
    print(f"  设备数: {patrol_report.total_devices}")
    for dev in patrol_report.devices:
        status = dev.error if dev.error else dev.summary
        print(f"  - {dev.asset.name}: {status}")
    print(f"  HTML 报告: {html_path}")
    print(f"  Word 报告: {word_path}")
    if pdf_generated:
        print(f"  PDF 报告: {pdf_path}")

    # 退出码:0=有结果且无异常;2=存在异常项;3=全部设备都没采集到(计划任务据此判断)
    if patrol_report.has_failures:
        sys.exit(2)
    if all(d.error for d in patrol_report.devices):
        sys.exit(3)

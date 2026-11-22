"""本地健康评分模型(销号清单 #3)

设备健康分(0~100)= Σ(五组得分 × 权重),任一 critical 级 FAIL 一票否决
强制 ≤40;不依赖 AI,规则判定结果直接换算。

分组与权重(方案 v3,对标 Cisco Catalyst Center 加权 + Optigo 关键项否决):
  hardware 硬件环境 30% | resource 资源 20% | link 链路接口 20%
  security 安全合规 15% | logs_config 日志告警/配置管理 15%

UNKNOWN 不进分母(无法判断不扣分也不加分);某组无任何判定项时
其权重按剩余组归一,避免凭空得分。
"""
from __future__ import annotations

from patrol.models import CheckStatus, DeviceReport, PatrolReport

# 检查项 → 评分组(device_info 展示项不参与)
SCORE_GROUPS: dict[str, set[str]] = {
    "hardware": {"fan_status", "power_status", "temperature", "transceiver",
                 "board_status"},
    "resource": {"cpu_usage", "memory_usage", "storage"},
    "link": {"interface_status", "interface_errors", "l3_interface"},
    "security": {"telnet_service", "snmp_community", "vty_auth", "stp_status",
                 "login_lock", "password_policy", "mgmt_acl", "syslog_external",
                 "vty_idle_timeout", "ntp_status"},
    "logs_config": {"logbuffer", "routing_table", "ospf_neighbor", "arp_count",
                    "config_diff", "reboot_reason", "session_table",
                    "system_alarms"},
}

WEIGHTS: dict[str, float] = {
    "hardware": 0.30, "resource": 0.20, "link": 0.20,
    "security": 0.15, "logs_config": 0.15,
}

GROUP_LABELS = {
    "hardware": "硬件环境", "resource": "资源", "link": "链路接口",
    "security": "安全合规", "logs_config": "日志与配置",
}

_VETO_CAP = 40  # critical 一票否决后的分数上限


def _grade(score: float) -> str:
    if score >= 90:
        return "优"
    if score >= 75:
        return "良"
    if score >= 60:
        return "关注"
    return "差"


def score_device(device: DeviceReport) -> dict:
    """单设备健康评分。

    返回 {score, grade, veto, groups:{组:{score,pass,fail,unknown}}};
    error(连接失败)设备直接 0 分差级。
    """
    if device.error:
        return {"score": 0, "grade": "差", "veto": False, "groups": {},
                "note": device.error}

    stats: dict[str, dict[str, int]] = {g: {"pass": 0, "fail": 0, "unknown": 0}
                                        for g in SCORE_GROUPS}
    veto = False
    for item in device.check_items:
        group = next((g for g, names in SCORE_GROUPS.items()
                      if item.name in names), None)
        if group is None:
            continue  # 展示项/未知项不参与评分
        if item.status == CheckStatus.PASS:
            stats[group]["pass"] += 1
        elif item.status == CheckStatus.FAIL:
            stats[group]["fail"] += 1
            if str(item.details.get("severity", "")) == "critical":
                veto = True
        else:
            stats[group]["unknown"] += 1

    groups: dict[str, dict] = {}
    weighted_sum = 0.0
    weight_used = 0.0
    for g, s in stats.items():
        judged = s["pass"] + s["fail"]
        if judged == 0:
            continue  # 无判定项:权重归一到其余组
        gscore = round(s["pass"] / judged * 100)
        groups[g] = {"score": gscore, **s}
        weighted_sum += gscore * WEIGHTS[g]
        weight_used += WEIGHTS[g]

    score = round(weighted_sum / weight_used) if weight_used else 100
    if veto:
        score = min(score, _VETO_CAP)
    return {"score": score, "grade": _grade(score), "veto": veto,
            "groups": groups}


def score_report(report: PatrolReport) -> dict:
    """全网评分:各设备算术平均 + 分设备明细。"""
    devices = {d.asset.name: score_device(d) for d in report.devices}
    scores = [v["score"] for v in devices.values()]
    overall = round(sum(scores) / len(scores)) if scores else None
    return {
        "overall": overall,
        "overall_grade": _grade(overall) if overall is not None else "—",
        "devices": devices,
    }

"""异常预测(P1 第二批 ①):基于历史趋势的线性外推预警

利用巡检历史库中连续多期的指标值(CPU/内存/温度),
做简单线性回归外推,预测 N 天后是否超阈值。
报告在对应检查项旁标注"⚠ 预测 X 天后可能超阈值"。

对标:Cisco DNA Center predictive analytics
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 预测阈值(与 default.yaml R 系列一致)
_THRESHOLDS = {
    "cpu_usage": 80,
    "memory_usage": 80,
    "temperature": 60,
    "storage": 80,
}

# 最少数据点(不足则不预测)
_MIN_POINTS = 3


def predict_threshold(series: list[tuple[str, float]],
                      threshold: float,
                      horizon_days: int = 7) -> dict[str, Any] | None:
    """线性外推:给定 (时间, 值) 序列,预测 horizon_days 内是否超阈值。

    series: [(run_time_iso, value)] 按时间正序
    返回 {will_exceed, days_to_exceed, trend, current, threshold} 或 None。
    """
    if len(series) < _MIN_POINTS:
        return None

    from datetime import datetime

    # 解析时间为天数差
    times: list[float] = []
    values: list[float] = []
    base = None
    for ts, val in series:
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            continue
        if base is None:
            base = dt
        delta = (dt - base).total_seconds() / 86400  # 天
        times.append(delta)
        values.append(float(val))

    if len(times) < _MIN_POINTS:
        return None

    # 简单线性回归 y = a + b*x
    n = len(times)
    sum_x = sum(times)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(times, values))
    sum_x2 = sum(x * x for x in times)

    denom = n * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-10:
        return None  # 无趋势(全部同一时间)

    b = (n * sum_xy - sum_x * sum_y) / denom  # 斜率(值/天)
    a = (sum_y - b * sum_x) / n

    current = values[-1]
    if current >= threshold:
        return {"will_exceed": True, "days_to_exceed": 0,
                "trend": "rising" if b > 0.5 else "stable",
                "current": current, "threshold": threshold,
                "slope_per_day": round(b, 2)}

    if b <= 0.1:  # 斜率几乎为零或下降,不会超
        return None

    # 外推:current + b * days >= threshold → days = (threshold - current) / b
    days = (threshold - current) / b
    if days > horizon_days:
        return None  # 预测周期内不会超

    return {"will_exceed": True,
            "days_to_exceed": round(days, 1),
            "trend": "rising",
            "current": current,
            "threshold": threshold,
            "slope_per_day": round(b, 2)}


def predict_device(device_name: str) -> dict[str, dict[str, Any]]:
    """对一台设备做全部可预测指标的趋势外推。

    返回 {check_name: prediction_dict}。
    """
    from patrol.storage.history import HistoryStore

    predictions: dict[str, dict[str, Any]] = {}
    try:
        hist = HistoryStore()
        for check_name, threshold in _THRESHOLDS.items():
            series = hist.metric_series(device_name, check_name)
            pred = predict_threshold(series, threshold)
            if pred:
                predictions[check_name] = pred
    except Exception:  # noqa: BLE001 - 历史不可用不影响
        pass
    return predictions

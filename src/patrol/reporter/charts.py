"""报告图表(P1-3):服务端生成 SVG,零 JS 依赖,文件双击即渲染。

饼图(状态分布)/条形图(设备 CPU 内存)/趋势折线(history 指标序列)。
"""
from __future__ import annotations

from xml.sax.saxutils import escape as _esc

_PI = 3.14159265


def _arc_path(cx, cy, r, a0, a1):
    """极坐标弧 path(SVG 角度:y 向下,顺时针)。"""
    x0, y0 = cx + r * _PI * 0 / 180, cy  # 占位,下面直接算
    import math
    x0 = cx + r * math.cos(math.radians(a0 - 90))
    y0 = cy + r * math.sin(math.radians(a0 - 90))
    x1 = cx + r * math.cos(math.radians(a1 - 90))
    y1 = cy + r * math.sin(math.radians(a1 - 90))
    large = 1 if (a1 - a0) > 180 else 0
    return (f"M {cx} {cy} L {x0:.1f} {y0:.1f} "
            f"A {r} {r} 0 {large} 1 {x1:.1f} {y1:.1f} Z")


def pie_svg(items: list[tuple[str, int, str]], size: int = 180) -> str:
    """items: [(标签, 数量, 颜色)] → 环形饼图 + 图例。"""
    total = sum(v for _, v, _ in items)
    if total == 0:
        return ""
    cx, cy, r = size / 2, size / 2, size / 2 - 8
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size + 120}" '
             f'height="{size}" font-family="Microsoft YaHei">']
    angle = 0.0
    for label, value, color in items:
        if value <= 0:
            continue
        sweep = value / total * 360
        parts.append(f'<path d="{_arc_path(cx, cy, r, angle, angle + sweep)}" '
                     f'fill="{color}" stroke="#fff" stroke-width="1.5"/>')
        angle += sweep
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r * 0.55}" fill="#fff"/>')
    parts.append(f'<text x="{cx}" y="{cy + 5}" font-size="15" font-weight="bold" '
                 f'fill="#243b55" text-anchor="middle">{total}</text>')
    ly = size / 2 - len(items) * 11 + 8
    for label, value, color in items:
        parts.append(f'<rect x="{size + 6}" y="{ly - 8}" width="10" height="10" '
                     f'fill="{color}" rx="2"/>')
        parts.append(f'<text x="{size + 22}" y="{ly + 1}" font-size="12" '
                     f'fill="#4a5a70">{_esc(label)} {value}</text>')
        ly += 22
    parts.append("</svg>")
    return "".join(parts)


def bars_svg(items: list[tuple[str, float]], width: int = 340,
             bar_h: int = 18, max_val: float = 100) -> str:
    """items: [(标签, 值)] → 横向条形(0~max_val,超界截断)。"""
    if not items:
        return ""
    h = len(items) * (bar_h + 14) + 6
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{h}" font-family="Microsoft YaHei">']
    y = 6
    for label, value in items:
        v = max(0.0, min(float(value), max_val))
        color = ("#52c41a" if v < 60 else "#faad14" if v < 80 else "#ff4d4f")
        parts.append(f'<text x="0" y="{y + 13}" font-size="12" fill="#4a5a70">'
                     f'{_esc(label)}</text>')
        parts.append(f'<rect x="82" y="{y}" width="{width - 122}" height="{bar_h}" '
                     f'fill="#eef2f7" rx="3"/>')
        parts.append(f'<rect x="82" y="{y}" width="{(width - 122) * v / max_val:.0f}" '
                     f'height="{bar_h}" fill="{color}" rx="3"/>')
        parts.append(f'<text x="{width - 34}" y="{y + 13}" font-size="12" '
                     f'fill="#243b55" font-weight="bold">{value:g}%</text>')
        y += bar_h + 14
    parts.append("</svg>")
    return "".join(parts)


def trend_svg(series: list[tuple[str, float]], width: int = 340,
              height: int = 110, color: str = "#1B5FA8") -> str:
    """series: [(时间标签, 值)] → 折线趋势(最新在右)。"""
    if len(series) < 2:
        return ""
    vals = [v for _, v in series]
    vmax = max(vals + [100]) # 至少 0~100 量纲
    pad, step = 8, (width - 90) / (len(series) - 1)
    pts = [(36 + i * step, height - pad - (v / vmax) * (height - 2 * pad))
           for i, (_, v) in enumerate(series)]
    poly = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" font-family="Microsoft YaHei">']
    parts.append(f'<rect x="36" y="{pad}" width="{width - 44}" '
                 f'height="{height - 2 * pad}" fill="#f7f9fc" rx="4"/>')
    for frac in (0.25, 0.5, 0.75):
        gy = pad + frac * (height - 2 * pad)
        parts.append(f'<line x1="36" y1="{gy:.0f}" x2="{width - 8}" y2="{gy:.0f}" '
                     f'stroke="#e3e9f2" stroke-width="1"/>')
    parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" '
                 f'stroke-width="2"/>')
    for (x, y), (_, v) in zip(pts, series):
        parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="2.6" fill="{color}"/>')
    parts.append(f'<text x="36" y="{height - 0}" font-size="9" fill="#8b98a8">'
                 f'{_esc(series[0][0][5:16])}</text>')
    parts.append(f'<text x="{width - 8}" y="{height - 0}" font-size="9" '
                 f'fill="#8b98a8" text-anchor="end">{_esc(series[-1][0][5:16])}</text>')
    parts.append(f'<text x="{width - 8}" y="14" font-size="10" fill="#243b55" '
                 f'text-anchor="end" font-weight="bold">最新 {series[-1][1]:g}%</text>')
    parts.append("</svg>")
    return "".join(parts)

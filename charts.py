"""Validated chart snapshots with full warm-up for EMA, closed candles only."""

import math

PERIODS = {"15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}


def snapshot(rows, period, now, ema):
    if period not in PERIODS:
        raise ValueError("不支持的 K 线周期")
    closed = []
    for row in rows:
        if int(row[6]) >= now:
            continue
        values = [float(row[i]) for i in range(1, 6)]
        if not all(math.isfinite(v) for v in values):
            continue
        closed.append(row)
    closed.sort(key=lambda r: int(r[0]))
    prices = [float(r[4]) for r in closed]
    a = ema(prices, 200)
    b = ema(prices, 360)
    candles = []
    for i, r in enumerate(closed):
        candles.append(
            dict(
                time=int(r[0]),
                closeTime=int(r[6]),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
                ema200=a[i] if i < len(a) else None,
                ema360=b[i] if i < len(b) else None,
            )
        )
    return {
        "period": period,
        "intervalMs": PERIODS[period],
        "candles": candles[-96:],
        "fetchedAt": now,
        "warmupCount": len(closed),
        "source": "Binance USDⓈ-M 永续",
        "closedOnly": True,
    }


def oi_snapshot(rows, now):
    if not isinstance(rows, list):
        raise ValueError("OI 数据无效")
    points = {}
    for row in rows:
        try:
            t = int(row["timestamp"])
            v = float(row["sumOpenInterest"])
        except (TypeError, KeyError, ValueError):
            continue
        if 0 < t <= now and math.isfinite(v) and v >= 0:
            points[t] = {"time": t, "value": v}
    return [points[t] for t in sorted(points)]

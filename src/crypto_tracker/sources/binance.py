"""Public Binance USD-M market data (no credentials)."""

import concurrent.futures as cf
import json
import threading
import urllib.parse

from crypto_tracker.core import charts
from crypto_tracker.core.events import now
from crypto_tracker.net.http import error_label


def api(path, params, request):
    return json.loads(
        request(
            "https://fapi.binance.com" + path + "?" + urllib.parse.urlencode(params)
        )
    )


def ema(values, period):
    if len(values) < period:
        return []
    out = [None] * (period - 1)
    v = sum(values[:period]) / period
    out.append(v)
    for x in values[period:]:
        v = x * 2 / (period + 1) + v * (1 - 2 / (period + 1))
        out.append(v)
    return out


def market(p, request):
    """Binance USD-M perpetual snapshot: 24h ticker, closed 4h candles with EMA200/360, 1h OI."""
    symbol = p["symbol"] + "USDT"
    t = now()
    result = {
        "symbol": symbol,
        "source": "Binance USDⓈ-M 永续",
        "fetchedAt": t,
        "errors": {},
    }
    queries = {
        "ticker": ("/fapi/v1/ticker/24hr", {"symbol": symbol}),
        "klines": (
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": "4h", "limit": 1500},
        ),
        "oi": (
            "/futures/data/openInterestHist",
            {"symbol": symbol, "period": "5m", "limit": 13},
        ),
    }

    def fetch(item):
        k, (path, params) = item
        try:
            return k, api(path, params, request), None
        except Exception as e:
            return k, None, error_label(e)

    parts = {}
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        for k, value, error in ex.map(fetch, queries.items()):
            if error:
                result["errors"][k] = error
            else:
                parts[k] = value
    if isinstance(parts.get("ticker"), dict) and "lastPrice" in parts["ticker"]:
        q = parts["ticker"]
        result.update(
            price=float(q["lastPrice"]),
            change24h=float(q["priceChangePercent"]),
            quoteVolume=float(q["quoteVolume"]),
            priceAt=int(q["closeTime"]),
        )
    if isinstance(parts.get("klines"), list):
        ks = [x for x in parts["klines"] if int(x[6]) < t]
        values = [float(x[4]) for x in ks]
        a = ema(values, 200)
        b = ema(values, 360)
        result["candles"] = [
            {
                "time": int(x[0]),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5]),
            }
            for x in ks[-96:]
        ]
        if a and b and len(values) >= 361:
            crossUp = values[-2] <= max(a[-2], b[-2]) and values[-1] > max(a[-1], b[-1])
            crossDown = values[-2] >= min(a[-2], b[-2]) and values[-1] < min(
                a[-1], b[-1]
            )
            result.update(
                previousEma200=a[-2],
                ema200=a[-1],
                ema360=b[-1],
                close4h=values[-1],
                candleAt=int(ks[-1][6]),
                above200=values[-1] > a[-1],
                above360=values[-1] > b[-1],
                cross="up" if crossUp else "down" if crossDown else None,
                klineCount=len(values),
                spark=values[-30:],
            )
        else:
            result["errors"]["ema"] = "已收盘 K 线不足 361 根"
    if isinstance(parts.get("oi"), list) and len(parts["oi"]) >= 2:
        rows = sorted(parts["oi"], key=lambda x: int(x["timestamp"]))
        first, last = rows[0], rows[-1]
        span = int(last["timestamp"]) - int(first["timestamp"])
        base = float(first["sumOpenInterest"])
        result.update(
            oi=float(last["sumOpenInterest"]),
            oiAt=int(last["timestamp"]),
            oiFrom=int(first["timestamp"]),
            oiSpanMinutes=span / 60000,
        )
        if 55 * 60000 <= span <= 65 * 60000 and base > 0:
            result["oiChange1h"] = (float(last["sumOpenInterest"]) / base - 1) * 100
        else:
            result["errors"]["oiWindow"] = "未获得完整一小时 OI 窗口"
    return p["id"], result


class Charts:
    """Closed-candle chart snapshots per (project, period), cached for 60 s."""

    def __init__(self, request):
        self.request = request
        self.cache = {}
        self.lock = threading.Lock()

    def get(self, project, period):
        if not project or period not in charts.PERIODS:
            raise ValueError("项目或周期无效")
        key = (project["id"], period)
        symbol = project["symbol"] + "USDT"
        with self.lock:
            cached = self.cache.get(key)
            if cached and now() - cached["fetchedAt"] < 60000:
                return cached
            rows = api(
                "/fapi/v1/klines",
                {"symbol": symbol, "interval": period, "limit": 1500},
                self.request,
            )
            if not isinstance(rows, list):
                raise ValueError("K 线数据不可用")
            result = charts.snapshot(rows, period, now(), ema)
            try:
                oi = api(
                    "/futures/data/openInterestHist",
                    {"symbol": symbol, "period": period, "limit": 96},
                    self.request,
                )
                result["oi"] = charts.oi_snapshot(oi, now())
                result["oiStatus"] = "ok" if result["oi"] else "empty"
            except Exception:
                result["oi"] = []
                result["oiStatus"] = "unavailable"
            self.cache[key] = result
            return result

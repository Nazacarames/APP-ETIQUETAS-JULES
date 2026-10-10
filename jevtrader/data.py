"""Datos de mercado: velas OHLCV.

Fuentes:
- Binance (endpoint público de datos, sin API key): cripto 24/7.
- CSV propio (cualquier activo: acciones, futuros, forex).
- Sintético (régimen cambiante) para tests y para correr sin red.
"""
from __future__ import annotations

import csv
import json
import math
import random
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BINANCE_DATA_URL = "https://data-api.binance.vision/api/v3/klines"
INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000,
    "4h": 14_400_000, "1d": 86_400_000,
}
BARS_PER_YEAR = {"1m": 525_600, "5m": 105_120, "15m": 35_040, "1h": 8_760, "4h": 2_190, "1d": 365}


@dataclass(frozen=True)
class Bar:
    ts: int          # apertura de la vela, epoch en milisegundos (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def date(self) -> str:
        return datetime.fromtimestamp(self.ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _to_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_binance(symbol: str, interval: str = "1d", start: str | None = None,
                  end: str | None = None, limit: int | None = None,
                  only_closed: bool = True) -> list[Bar]:
    """Descarga velas de Binance paginando de a 1000.

    only_closed=True descarta la vela en curso (todavía no cerró): operar con
    ella es una forma clásica de mirar el futuro.
    """
    step = INTERVAL_MS[interval]
    bars: list[Bar] = []
    params = {"symbol": symbol.upper(), "interval": interval, "limit": 1000}
    if start:
        params["startTime"] = _to_ms(start)
    elif limit:
        params["startTime"] = int(time.time() * 1000) - (limit + 2) * step
    end_ms = _to_ms(end) if end else None
    while True:
        url = BINANCE_DATA_URL + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=20) as resp:
            rows = json.load(resp)
        if not rows:
            break
        for r in rows:
            bars.append(Bar(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        if len(rows) < 1000:
            break
        params["startTime"] = int(rows[-1][0]) + step
        if end_ms and params["startTime"] >= end_ms:
            break
    if end_ms:
        bars = [b for b in bars if b.ts < end_ms]
    if only_closed:
        now_ms = int(time.time() * 1000)
        bars = [b for b in bars if b.ts + step <= now_ms]
    if limit:
        bars = bars[-limit:]
    return bars


def save_csv(bars: list[Bar], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.ts, b.open, b.high, b.low, b.close, b.volume])


def load_csv(path: str | Path) -> list[Bar]:
    """Lee un CSV con columnas ts|date, open, high, low, close, volume."""
    bars = []
    with Path(path).open() as f:
        for row in csv.DictReader(f):
            row = {k.lower().strip(): v for k, v in row.items()}
            if "ts" in row:
                ts = int(float(row["ts"]))
            else:
                ts = _to_ms(row["date"][:10])
            bars.append(Bar(ts, float(row["open"]), float(row["high"]), float(row["low"]),
                            float(row["close"]), float(row.get("volume") or 0.0)))
    bars.sort(key=lambda b: b.ts)
    return bars


def synthetic(n: int = 1500, seed: int = 7, start_price: float = 100.0) -> list[Bar]:
    """Serie diaria sintética que alterna tendencias, rangos y pánicos.

    No representa ningún mercado real; sirve para tests y demos offline.
    """
    rng = random.Random(seed)
    regimes = [  # (drift diario, volatilidad diaria)
        (0.0025, 0.015),   # tendencia alcista ordenada
        (0.0, 0.012),      # rango
        (-0.002, 0.02),    # tendencia bajista
        (0.0, 0.045),      # caos
    ]
    price, ts = start_price, _to_ms("2018-01-01")
    bars: list[Bar] = []
    regime = regimes[0]
    for i in range(n):
        if i % 60 == 0:
            regime = rng.choices(regimes, weights=[0.35, 0.3, 0.2, 0.15])[0]
        drift, vol = regime
        ret = rng.gauss(drift, vol)
        o = price * math.exp(rng.gauss(0, vol * 0.2))
        c = price * math.exp(ret)
        hi = max(o, c) * math.exp(abs(rng.gauss(0, vol * 0.5)))
        lo = min(o, c) * math.exp(-abs(rng.gauss(0, vol * 0.5)))
        v = 1000 * math.exp(rng.gauss(0, 0.4)) * (1 + 20 * abs(ret))
        bars.append(Bar(ts, o, hi, lo, c, v))
        price, ts = c, ts + INTERVAL_MS["1d"]
    return bars

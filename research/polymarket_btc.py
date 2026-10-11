"""¿Polymarket anticipa a Bitcoin en Binance? Prueba con los mercados diarios "Bitcoin Up or Down".

Cada día Polymarket abre un mercado: ¿el cierre de BTC/USDT en Binance a las 12:00 (hora de Nueva York) va a ser
mayor que el del día anterior a la misma hora? Si el público supiera algo que el precio todavía no refleja, la
probabilidad de "Up" al empezar la ventana debería anticipar hacia dónde va BTC en las 24 h siguientes.

Sin mirar el futuro: se usa el último precio de "Up" que ya se conocía al inicio de la ventana (ver
Polymarket.prices_history) y se opera en Binance spot desde el inicio hasta el final de esa misma ventana.

    python3 research/polymarket_btc.py --capital 100

Solo lee datos públicos. Simula; no opera.
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from polylens.http import Http  # noqa: E402
from polylens.polymarket import GAMMA, Polymarket, parse_list  # noqa: E402
from polylens.study import parse_ts  # noqa: E402

SERIES_DAILY = 41   # "BTC Up or Down Daily" en Gamma
BINANCE = "https://data-api.binance.vision/api/v3/klines"  # datos públicos; api.binance.com da 451 desde la nube
COST = 0.001 + 0.0005  # por lado: comisión spot 0,1 % + deslizamiento 0,05 %
DAY = 86_400


def day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def daily_events(http: Http) -> list[dict]:
    out, offset = [], 0
    while True:
        rows = http.get(f"{GAMMA}/events", {"series_id": SERIES_DAILY, "closed": True, "limit": 100,
                                            "offset": offset, "order": "endDate", "ascending": True}, ttl=DAY) or []
        out += rows
        offset += len(rows)
        if len(rows) < 100:
            return [e for e in out if e.get("markets") and e["markets"][0].get("eventStartTime")]


def btc_hour_opens(http: Http, start: int, end: int) -> dict[int, float]:
    out, t = {}, start * 1000
    while t < end * 1000:
        rows = http.get(BINANCE, {"symbol": "BTCUSDT", "interval": "1h", "startTime": t, "endTime": end * 1000,
                                  "limit": 1000}, ttl=DAY) or []
        if not rows:
            break
        out.update({int(r[0]) // 1000: float(r[1]) for r in rows})
        t = int(rows[-1][0]) + 3_600_000
    return out


def window(pm: Polymarket, e: dict, opens: dict[int, float]) -> dict | None:
    m = e["markets"][0]
    s, end = parse_ts(m["eventStartTime"]), parse_ts(m["endDate"])
    outcomes, tokens, prices = (parse_list(m.get(k)) for k in ("outcomes", "clobTokenIds", "outcomePrices"))
    if "Up" not in outcomes or len(tokens) != len(outcomes):
        return None
    k = outcomes.index("Up")
    known = [p for t, p in pm.prices_history(tokens[k], s - 2 * DAY, s + 3600, ttl=30 * DAY) if t <= s]
    if not known or s not in opens or end not in opens:
        return None
    return {"slug": e["slug"], "start": s, "end": end, "p_up": known[-1], "up": float(prices[k]) == 1.0,
            "btc_start": opens[s], "btc_end": opens[end]}


def simulate(rows: list[dict], rule, capital: float) -> tuple[float, int, int]:
    cap, trades, wins = capital, 0, 0
    for r in rows:
        if rule(r):
            g = r["btc_end"] / r["btc_start"] * (1 - COST) ** 2
            cap *= g
            trades += 1
            wins += g > 1
    return cap, trades, wins


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--capital", type=float, default=100.0)
    ap.add_argument("--cache", default="data/cache")
    a = ap.parse_args()
    http = Http(a.cache, ttl_s=DAY, min_interval_s=0.1)
    pm = Polymarket(http)

    events = daily_events(http)
    starts = [parse_ts(e["markets"][0]["eventStartTime"]) for e in events]
    opens = btc_hour_opens(http, min(starts) - DAY, max(starts) + 2 * DAY)
    with ThreadPoolExecutor(8) as ex:
        rows = sorted((r for r in ex.map(lambda e: window(pm, e, opens), events) if r), key=lambda r: r["start"])
    print(f"{len(rows)} ventanas diarias, {day(rows[0]['start'])} → {day(rows[-1]['end'])}\n")

    ps = [r["p_up"] for r in rows]
    rets = [math.log(r["btc_end"] / r["btc_start"]) for r in rows]
    up = [1.0 if r["up"] else 0.0 for r in rows]
    agree = statistics.fmean((r["btc_end"] > r["btc_start"]) == r["up"] for r in rows)
    print(f"Chequeo de datos: la suba/baja en Binance (velas de 1 h) coincide con la resolución en {agree:.1%}.")
    print(f"p(Up) al inicio: media {statistics.fmean(ps):.3f}, rango {min(ps):.3f}–{max(ps):.3f}")
    print(f"BTC subió en {statistics.fmean(up):.1%} de las ventanas.")
    lean = [p - 0.5 for p in ps]
    corr = statistics.correlation(lean, rets)
    rng = random.Random(1)
    pval = statistics.fmean(abs(statistics.correlation(rng.sample(lean, len(lean)), rets)) >= abs(corr)
                            for _ in range(2000))
    brier = statistics.fmean((p - y) ** 2 for p, y in zip(ps, up))
    print(f"Correlación entre (p(Up) − 0,5) y el retorno de BTC: {corr:+.3f} (p-valor por permutación {pval:.2f})")
    print(f"Brier: Polymarket {brier:.4f} contra 0,2500 de decir siempre 50 % (menor es mejor)\n")

    cut = int(len(rows) * 0.7)
    parts = {"total": rows, "tramo A": rows[:cut], "tramo B": rows[cut:]}
    rules = {"comprar y mantener todo el período": None,
             "operar todos los días": lambda r: True}
    for m in (0.0, 0.02):
        rules[f"seguir al público (p(Up) > {0.5 + m:.2f})"] = (lambda m: lambda r: r["p_up"] > 0.5 + m)(m)
        rules[f"contra el público (p(Up) < {0.5 - m:.2f})"] = (lambda m: lambda r: r["p_up"] < 0.5 - m)(m)
    print(f"Simulación con {a.capital:.0f} USD en Binance spot (costo {COST:.2%} por lado):")
    print(f"  {'regla':<40} " + " ".join(f"{k:>16}" for k in parts))
    for name, rule in rules.items():
        cells = []
        for sub in parts.values():
            if rule is None:
                cap = a.capital * sub[-1]["btc_end"] / sub[0]["btc_start"] * (1 - COST) ** 2
                cells.append(f"{cap:>9.2f} USD    ")
            else:
                cap, n, w = simulate(sub, rule, a.capital)
                cells.append(f"{cap:>9.2f} USD ({n:>3})")
        print(f"  {name:<40} " + " ".join(f"{c:>16}" for c in cells))
    print(f"\n  tramo A: {day(rows[0]['start'])} → {day(rows[cut - 1]['end'])} · "
          f"tramo B: {day(rows[cut]['start'])} → {day(rows[-1]['end'])} · entre paréntesis, operaciones")


if __name__ == "__main__":
    main()

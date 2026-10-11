"""Evaluación completa de la estrategia antes de operar.

    python3 research/evaluate.py                # todo (tarda ~1-2 min)
    python3 research/evaluate.py --json out.json

Qué mide:
1. Por activo: comprar-y-mantener vs. estrategia base vs. base + juez, tramos A (desarrollo) y B (holdout).
2. Robustez: grilla de parámetros evaluada SOLO en el tramo A.
3. Sensibilidad a costos.
4. Estadística por trade (bootstrap del retorno medio).
5. Cartera equiponderada de todos los activos en la ventana común.
6. Velas de 4 h en BTC y ETH (más trades, más poder estadístico).

Activos "vistos" (BTC, ETH, SOL): su tramo B ya se miró al desarrollar, no es holdout limpio.
Activos "nuevos": nunca se miraron; su tramo B es la prueba fuera de muestra de verdad.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jevtrader.backtest import buy_and_hold, compute_metrics, run_backtest, segment, veto_analysis  # noqa: E402
from jevtrader.config import CostConfig, GateConfig, RiskConfig  # noqa: E402
from jevtrader.data import BARS_PER_YEAR, fetch_binance, load_csv, save_csv  # noqa: E402
from jevtrader.features import WARMUP  # noqa: E402
from jevtrader.jev_client import MockJev  # noqa: E402
from jevtrader.judge import JevJudge  # noqa: E402
from jevtrader.risk import RiskManager  # noqa: E402
from jevtrader.strategy import DonchianTrend  # noqa: E402

SEEN = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
FRESH = ["BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "AVAXUSDT", "TRXUSDT"]
HOLDOUT = 0.3
DEFAULT = (20, 10, 2.0)


def load(sym: str, interval: str = "1d"):
    """Lee data/<sym>_<interval>.csv; si no existe, lo baja de Binance (datos públicos)."""
    path = ROOT / "data" / f"{sym}_{interval}.csv"
    if not path.exists():
        save_csv(fetch_binance(sym, interval, start="2018-01-01"), path)
    return load_csv(path)


def split(bars):
    start = WARMUP
    cut = start + int((len(bars) - start) * (1 - HOLDOUT))
    return bars[start].ts, bars[cut].ts


def seg(res, bars, a, z, bpy):
    return segment(res, a, z, bpy, {k: b.ts for k, b in enumerate(bars)})


def run(bars, params=DEFAULT, costs=CostConfig(), judge=None, bpy=365, name="Estrategia base"):
    e, x, s = params
    return run_backtest(bars, name=name, strategy=DonchianTrend(e, x, s), risk=RiskManager(RiskConfig()),
                        costs=costs, judge=judge, bars_per_year=bpy, asset="X")


def fmt(x, pct=True):
    if x is None:
        return "—"
    return f"{x * 100:+.1f}%" if pct else f"{x:.2f}"


def bootstrap_mean(xs, n=4000, seed=1):
    if len(xs) < 2:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return statistics.fmean(xs), means[int(0.025 * n)], means[int(0.975 * n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    data = {s: load(s) for s in SEEN + FRESH}
    out = {"per_asset": {}, "grid": [], "costs": [], "trades": {}, "portfolio": {}, "h4": {}}

    # 1) por activo --------------------------------------------------------
    print("\n1) Por activo (diario, 10 bps comisión + 5 bps slippage por lado, riesgo 1 % por trade)")
    print(f"{'activo':<10}{'grupo':<7}{'tramo':<4}{'variante':<14}{'ret':>9}{'maxDD':>8}{'sharpe':>8}{'trades':>7}")
    judge = JevJudge(MockJev(), GateConfig())
    pooled = {"A": [], "B_seen": [], "B_fresh": []}
    for sym, bars in data.items():
        group = "visto" if sym in SEEN else "nuevo"
        a, z = split(bars)
        bh = buy_and_hold(bars, CostConfig())
        base = run(bars)
        mock = run(bars, judge=judge, name="Base+MockJev")
        rows = {}
        for tramo, (lo, hi) in (("A", (a, z)), ("B", (z, None))):
            for label, r in (("Comprar/mant.", bh), ("Base", base), ("Base+MockJev", mock)):
                m = seg(r, bars, lo, hi, 365)
                rows[f"{tramo}:{label}"] = m
                print(f"{sym:<10}{group:<7}{tramo:<4}{label:<14}{fmt(m['total_return']):>9}{fmt(m['max_drawdown']):>8}"
                      f"{fmt(m['sharpe'], False):>8}{m['trades']:>7}")
        ts_of = {k: b.ts for k, b in enumerate(bars)}
        for t in base.trades:
            key = "A" if ts_of[t.entry_i] < z else ("B_seen" if group == "visto" else "B_fresh")
            pooled[key].append(t.ret_pct)
        out["per_asset"][sym] = {"group": group, "holdout_from": bars[next(i for i, b in enumerate(bars) if b.ts == z)].date,
                                 "rows": rows, "veto": veto_analysis(mock)}

    # 2) grilla de robustez (solo tramo A) ----------------------------------
    print("\n2) Robustez: Sharpe mediano en el tramo A (11 activos) por combinación de parámetros")
    print(f"{'entrada':>8}{'salida':>8}{'stop ATR':>9}{'sharpe med.':>13}{'ret med.':>10}{'trades':>8}")
    for e in (10, 20, 40, 55):
        for x in (5, 10, 20):
            if x >= e:
                continue
            for s in (1.5, 2.0, 3.0):
                sh, rt, tr = [], [], 0
                for sym, bars in data.items():
                    a, z = split(bars)
                    m = seg(run(bars, (e, x, s)), bars, a, z, 365)
                    sh.append(m["sharpe"])
                    rt.append(m["total_return"])
                    tr += m["trades"]
                row = {"entry": e, "exit": x, "stop": s, "sharpe_med": statistics.median(sh),
                       "ret_med": statistics.median(rt), "trades": tr}
                out["grid"].append(row)
                mark = "  ← actual" if (e, x, s) == DEFAULT else ""
                print(f"{e:>8}{x:>8}{s:>9}{row['sharpe_med']:>13.2f}{fmt(row['ret_med']):>10}{tr:>8}{mark}")

    # 3) costos (período completo, parámetros actuales) ---------------------
    print("\n3) Sensibilidad a costos (período completo, Sharpe mediano de 11 activos)")
    for fee, slip in ((5, 2), (10, 5), (20, 10), (40, 20)):
        sh = [run(bars, costs=CostConfig(fee, slip)).metrics["sharpe"] for bars in data.values()]
        out["costs"].append({"fee_bps": fee, "slip_bps": slip, "sharpe_med": statistics.median(sh)})
        print(f"  comisión {fee:>2} bps + slippage {slip:>2} bps por lado → Sharpe mediano {statistics.median(sh):.2f}")

    # 4) estadística por trade ---------------------------------------------
    print("\n4) Retorno por trade (estrategia base), media e intervalo de confianza 95 % por bootstrap")
    for key, label in (("A", "tramo A, 11 activos"), ("B_seen", "tramo B, vistos"), ("B_fresh", "tramo B, nuevos")):
        xs = pooled[key]
        mu, lo, hi = bootstrap_mean(xs)
        win = sum(r > 0 for r in xs) / len(xs) if xs else 0
        out["trades"][key] = {"n": len(xs), "mean": mu, "ci": [lo, hi], "win_rate": win}
        print(f"  {label:<22} n={len(xs):>3}  media {fmt(mu)}  IC95 [{fmt(lo)}, {fmt(hi)}]  ganadores {win:.0%}")

    # 5) cartera equiponderada ----------------------------------------------
    print("\n5) Cartera equiponderada (11 activos, capital repartido en partes iguales, ventana común)")
    start = max(bars[WARMUP].ts for bars in data.values())
    curves = {}
    for label in ("Comprar/mant.", "Base"):
        series = []
        for bars in data.values():
            r = buy_and_hold(bars, CostConfig()) if label == "Comprar/mant." else run(bars)
            eq = {t: v for t, v in r.equity if t >= start}
            first = eq[min(eq)]
            series.append({t: v / first for t, v in eq.items()})
        common = sorted(set.intersection(*(set(s) for s in series)))
        curve = [(t, 10_000 * statistics.fmean(s[t] for s in series)) for t in common]
        curves[label] = curve
        m = compute_metrics(curve, [], 365)
        out["portfolio"][label] = m
        print(f"  {label:<14} ret {fmt(m['total_return'])}  CAGR {fmt(m['cagr'])}  maxDD {fmt(m['max_drawdown'])}"
              f"  Sharpe {m['sharpe']:.2f}")
    out["portfolio"]["window"] = [min(curves['Base'])[0], max(curves['Base'])[0]]

    # 6) velas de 4 h ---------------------------------------------------------
    print("\n6) Velas de 4 h (BTC y ETH)")
    bpy = BARS_PER_YEAR["4h"]
    for sym in ("BTCUSDT", "ETHUSDT"):
        bars = load(sym, "4h")
        a, z = split(bars)
        bh, base = buy_and_hold(bars, CostConfig(), bars_per_year=bpy), run(bars, bpy=bpy)
        out["h4"][sym] = {}
        for tramo, (lo, hi) in (("A", (a, z)), ("B", (z, None))):
            for label, r in (("Comprar/mant.", bh), ("Base", base)):
                m = seg(r, bars, lo, hi, bpy)
                out["h4"][sym][f"{tramo}:{label}"] = m
                print(f"  {sym:<9}{tramo:<3}{label:<14}{fmt(m['total_return']):>9}{fmt(m['max_drawdown']):>8}"
                      f"{m['sharpe']:>7.2f}{m['trades']:>6} trades")

    if args.json:
        Path(args.json).write_text(json.dumps(out, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""¿El resultado es real o suerte? Sharpe deflactado, PBO y Monte Carlo de trades.

    python3 research/significance.py [--json out.json]

Sigue las skills statistical-significance-and-deflated-metrics y
monte-carlo-trade-resampling-and-drawdown-distribution:

1. Sharpe deflactado (Bailey y López de Prado): corrige el Sharpe por las 27
   combinaciones de parámetros probadas, el largo de la serie, la asimetría y la curtosis.
2. PBO (probabilidad de sobreajuste) con validación cruzada combinatoria simétrica
   (CSCV, 16 bloques): ¿la combinación que gana "adentro" pierde "afuera"?
3. Monte Carlo de trades (2000+ remuestreos, simple y por bloques): rango de
   retornos y caídas esperables, y cuántos trades por año genera la estrategia.
   De acá salen los umbrales de research/PROTOCOLO-DEMO.md.

Cartera usada para 1 y 2: las 11 monedas de research/evaluate.py, equiponderadas
(rebalanceo diario), en la ventana en la que todas tienen datos.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import statistics
import sys
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from evaluate import FRESH, SEEN, load, run  # noqa: E402
from jevtrader.features import WARMUP  # noqa: E402

GRID = [(e, x, s) for e in (10, 20, 40, 55) for x in (5, 10, 20) if x < e for s in (1.5, 2.0, 3.0)]
CHOSEN = (20, 10, 2.0)
EULER = 0.5772156649
N01 = NormalDist()


# ------------------------------------------------------------ estadística ----

def moments(r: list[float]) -> tuple[float, float, float, float]:
    """media, desvío, asimetría, curtosis (no exceso; normal = 3)."""
    n = len(r)
    mu = statistics.fmean(r)
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / n)
    if sd == 0:
        return mu, 0.0, 0.0, 3.0
    skew = sum((x - mu) ** 3 for x in r) / n / sd ** 3
    kurt = sum((x - mu) ** 4 for x in r) / n / sd ** 4
    return mu, sd, skew, kurt


def sharpe(r: list[float]) -> float:
    mu, sd, _, _ = moments(r)
    return mu / sd if sd else 0.0


def psr(sr: float, sr0: float, t: int, skew: float, kurt: float) -> float:
    """Probabilistic Sharpe Ratio: P(Sharpe verdadero > sr0). Sharpe por período (no anualizado)."""
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return N01.cdf((sr - sr0) * math.sqrt(t - 1) / denom)


def expected_max_sharpe(trial_srs: list[float]) -> float:
    """Sharpe máximo esperado por azar entre N intentos (umbral del Sharpe deflactado)."""
    n = len(trial_srs)
    v = statistics.pvariance(trial_srs)
    return math.sqrt(v) * ((1 - EULER) * N01.inv_cdf(1 - 1 / n) + EULER * N01.inv_cdf(1 - 1 / (n * math.e)))


def pbo_cscv(matrix: list[list[float]], blocks: int = 16) -> dict:
    """CSCV: matrix[t][k] = retorno del día t para la combinación k."""
    t_len, n = len(matrix), len(matrix[0])
    size = t_len // blocks
    agg = []  # por bloque: (count, sum[k], sumsq[k])
    for b in range(blocks):
        rows = matrix[b * size:(b + 1) * size]
        sums = [sum(r[k] for r in rows) for k in range(n)]
        sq = [sum(r[k] ** 2 for r in rows) for k in range(n)]
        agg.append((len(rows), sums, sq))

    def sr_of(idx):
        cnt = sum(agg[i][0] for i in idx)
        out = []
        for k in range(n):
            s = sum(agg[i][1][k] for i in idx)
            q = sum(agg[i][2][k] for i in idx)
            mu = s / cnt
            var = max(q / cnt - mu * mu, 1e-18)
            out.append(mu / math.sqrt(var))
        return out

    logits, degradation = [], []
    all_idx = set(range(blocks))
    for is_idx in itertools.combinations(range(blocks), blocks // 2):
        oos_idx = sorted(all_idx - set(is_idx))
        is_sr, oos_sr = sr_of(is_idx), sr_of(oos_idx)
        best = max(range(n), key=lambda k: is_sr[k])
        rank = sum(1 for k in range(n) if oos_sr[k] < oos_sr[best]) + 1  # 1..n
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
        degradation.append((is_sr[best], oos_sr[best]))
    pbo = sum(1 for l in logits if l <= 0) / len(logits)
    loss = sum(1 for _, o in degradation if o < 0) / len(degradation)
    return {"pbo": pbo, "splits": len(logits), "p_oos_sharpe_negative": loss,
            "median_is_sr": statistics.median(i for i, _ in degradation),
            "median_oos_sr": statistics.median(o for _, o in degradation)}


# ------------------------------------------------------------- Monte Carlo ----

def max_drawdown_r(rs: list[float]) -> float:
    """Caída máxima (en R, positiva) de la suma acumulada de R."""
    cum, peak, mdd = 0.0, 0.0, 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return mdd


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(p / 100 * len(s))))]


def monte_carlo(rs: list[float], n_trades: int, runs: int = 4000, block: int = 1, seed: int = 7) -> dict:
    """Remuestrea trades medidos en R (1 R = el riesgo del trade). Suma, no compone:
    así no depende de cuántas monedas ni de qué capital se use."""
    rng = random.Random(seed)
    total, mdds = [], []
    for _ in range(runs):
        seq: list[float] = []
        while len(seq) < n_trades:
            start = rng.randrange(len(rs))
            seq.extend(rs[start:start + block])
        seq = seq[:n_trades]
        total.append(sum(seq))
        mdds.append(max_drawdown_r(seq))
    ps = (1, 5, 25, 50, 75, 95, 99)
    return {"n_trades": n_trades, "runs": runs, "block": block,
            "sum_r": {p: pct(total, p) for p in ps},
            "max_dd_r": {p: pct(mdds, p) for p in ps},  # p95 = caída que solo se supera 5 % de las veces
            "p_negative": sum(1 for x in total if x < 0) / runs}


# ------------------------------------------------------------------ main ----

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    out: dict = {}
    data = {s: load(s) for s in SEEN + FRESH}
    start = max(bars[WARMUP].ts for bars in data.values())

    # Retornos diarios de la cartera para cada combinación del grid.
    print(f"Corriendo {len(GRID)} combinaciones × {len(data)} monedas...")
    port: dict[tuple, dict[int, float]] = {}
    chosen_runs = {}
    for cfg in GRID:
        per_asset = []
        for sym, bars in data.items():
            res = run(bars, cfg)
            if cfg == CHOSEN:
                chosen_runs[sym] = (bars, res)
            eq = res.equity
            per_asset.append({eq[k][0]: eq[k][1] / eq[k - 1][1] - 1 for k in range(1, len(eq)) if eq[k][0] >= start})
        days = sorted(set.intersection(*(set(d) for d in per_asset)))
        port[cfg] = {t: statistics.fmean(d[t] for d in per_asset) for t in days}
    days = sorted(port[CHOSEN])
    matrix = [[port[cfg][t] for cfg in GRID] for t in days]

    # 1) Sharpe deflactado ----------------------------------------------------
    r = [port[CHOSEN][t] for t in days]
    mu, sd, skew, kurt = moments(r)
    sr = mu / sd
    trial_srs = [sharpe([port[cfg][t] for t in days]) for cfg in GRID]
    sr0 = expected_max_sharpe(trial_srs)
    dsr = psr(sr, sr0, len(r), skew, kurt)
    psr0 = psr(sr, 0.0, len(r), skew, kurt)
    rank = sorted(trial_srs, reverse=True).index(sr) + 1
    out["dsr"] = {"days": len(r), "sharpe_annual": sr * math.sqrt(365), "skew": skew, "kurtosis": kurt,
                  "trials": len(GRID), "sr0_annual": sr0 * math.sqrt(365), "psr_vs_0": psr0, "dsr": dsr,
                  "rank_among_trials": rank}
    print("\n1) Sharpe deflactado — cartera de 11 monedas, parámetros 20/10/2")
    print(f"   {len(r)} días · Sharpe anual {sr * math.sqrt(365):.2f} · asimetría {skew:.2f} · curtosis {kurt:.1f}")
    print(f"   puesto {rank} de {len(GRID)} combinaciones probadas")
    print(f"   P(Sharpe real > 0)                     = {psr0:.1%}   (sin corregir)")
    print(f"   Sharpe que daría el azar con 27 pruebas = {sr0 * math.sqrt(365):.2f} anual")
    print(f"   Sharpe deflactado: P(real > azar)      = {dsr:.1%}   (≥ 95 % sería significativo)")

    # 2) PBO -----------------------------------------------------------------
    p = pbo_cscv(matrix, 16)
    out["pbo"] = p
    print("\n2) Probabilidad de sobreajuste (CSCV, 16 bloques)")
    print(f"   {p['splits']} particiones · PBO = {p['pbo']:.1%}   (< 50 % es buena señal; ~0 % ideal)")
    print(f"   Sharpe diario mediano del 'ganador': adentro {p['median_is_sr']:.4f} → afuera {p['median_oos_sr']:.4f}")
    print(f"   P(Sharpe del ganador < 0 afuera) = {p['p_oos_sharpe_negative']:.1%}")

    # 3) Monte Carlo de trades -------------------------------------------------
    trades, per_asset_tr, years = [], {}, {}
    for sym, (bars, res) in chosen_runs.items():
        ts_list = []
        for t in res.trades:
            before = res.equity[t.entry_i - 1 - WARMUP][1]
            trades.append((bars[t.entry_i].ts, t.pnl / before))
            ts_list.append(t)
        per_asset_tr[sym] = len(ts_list)
        years[sym] = (bars[-1].ts - bars[WARMUP].ts) / (365 * 86_400_000)
    trades.sort()
    risk = 0.01  # RiskConfig.risk_per_trade: 1 R = 1 % del capital de esa moneda
    rs = [x / risk for _, x in trades]
    rate = {s: per_asset_tr[s] / years[s] for s in per_asset_tr}
    out["trades"] = {"n": len(rs), "mean_r": statistics.fmean(rs), "median_r": statistics.median(rs),
                     "win_rate": sum(x > 0 for x in rs) / len(rs), "worst_r": min(rs), "best_r": max(rs),
                     "per_year": rate, "per_year_total": sum(rate.values())}
    print(f"\n3) Monte Carlo — {len(rs)} trades de las 11 monedas, medidos en R (1 R = riesgo de 1 % del capital)")
    print(f"   media {statistics.fmean(rs):+.2f} R · mediana {statistics.median(rs):+.2f} R · ganadores "
          f"{out['trades']['win_rate']:.0%} · peor {min(rs):+.2f} R · mejor {max(rs):+.1f} R")
    print(f"   trades por año: BTC {rate['BTCUSDT']:.1f} · promedio por moneda {statistics.fmean(rate.values()):.1f}"
          f" · 11 monedas juntas {sum(rate.values()):.0f}")
    out["mc"] = {}
    for n_tr in (10, 20, 30, 50):
        for block in (1, 5):
            mc = monte_carlo(rs, n_tr, runs=4000, block=block)
            out["mc"][f"{n_tr}_{block}"] = mc
            kind = "simple" if block == 1 else "bloques de 5"
            q, d = mc["sum_r"], mc["max_dd_r"]
            print(f"   {n_tr:>2} trades ({kind:<12}) suma R p5 {q[5]:+6.1f} · p50 {q[50]:+6.1f} · p95 {q[95]:+6.1f}"
                  f" | caída R p50 {d[50]:4.1f} · p95 {d[95]:4.1f} · p99 {d[99]:4.1f} | P(suma<0) {mc['p_negative']:.0%}")
    hist = max_drawdown_r(rs)
    out["mc"]["historical_max_dd_r"] = hist
    full = monte_carlo(rs, len(rs), runs=4000, block=5)
    where = sum(1 for x in [full["max_dd_r"][p] for p in (5, 25, 50, 75, 95)] if x < hist)
    print(f"   caída histórica (orden real de los {len(rs)} trades): {hist:.1f} R · Monte Carlo del mismo largo:"
          f" p50 {full['max_dd_r'][50]:.1f} R · p95 {full['max_dd_r'][95]:.1f} R")
    out["mc"]["full_length_block5"] = full

    if args.json:
        Path(args.json).write_text(json.dumps(out, default=str, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

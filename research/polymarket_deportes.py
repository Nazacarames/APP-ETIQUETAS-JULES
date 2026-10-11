"""¿Las probabilidades de Polymarket en deportes son confiables? Calibración de los mercados de ganador.

Para cada partido ya jugado de varias ligas se toma el precio que se conocía 1 hora antes del inicio (sin mirar
el futuro: ver Polymarket.prices_history) y se compara con quién ganó. Si un precio de 0,70 gana ~70 % de las
veces, Polymarket sirve como "probabilidad justa" para comparar con las cuotas de una casa de apuestas.

    python3 research/polymarket_deportes.py --per-league 300

Polymarket está bloqueado en Argentina: esto solo lee sus datos públicos, no apuesta ahí.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from polylens.http import Http  # noqa: E402
from polylens.polymarket import GAMMA, Polymarket, parse_list  # noqa: E402
from polylens.study import parse_ts  # noqa: E402

LEAGUES = ["epl", "lal", "arg", "ucl", "nba", "nfl", "mlb", "atp"]
DAY = 86_400


def games(http: Http, series: str, limit: int) -> list[tuple[dict, list[dict]]]:
    out, offset = [], 0
    while len(out) < limit:
        try:
            evs = http.get(f"{GAMMA}/events", {"series_id": series, "closed": True, "limit": 100, "offset": offset,
                                               "order": "endDate", "ascending": False}, ttl=DAY) or []
        except Exception:
            break  # Gamma no deja paginar tan atrás con offset
        if not evs:
            break
        offset += len(evs)
        for e in evs:
            ml = [m for m in e.get("markets") or [] if m.get("sportsMarketType") == "moneyline" and m.get("gameStartTime")]
            if ml:
                out.append((e, ml))
        if len(evs) < 100:
            break
    return out[:limit]


def outcomes(pm: Polymarket, league: str, game: tuple[dict, list[dict]]) -> list[dict]:
    e, markets = game
    rows = []
    for m in markets:
        start = parse_ts(m["gameStartTime"])
        names, tokens, final = (parse_list(m.get(k)) for k in ("outcomes", "clobTokenIds", "outcomePrices"))
        if not tokens or not len(tokens) == len(names) == len(final):
            continue
        known = [p for t, p in pm.prices_history(tokens[0], start - 3 * DAY, start, ttl=30 * DAY) if t <= start - 3600]
        if not known:
            continue
        if names[0] == "Yes":  # fútbol: un mercado Sí/No por local, empate y visitante
            rows.append({"league": league, "p": known[-1], "won": float(final[0]) == 1.0})
        else:                  # dos equipos en un mismo mercado
            rows += [{"league": league, "p": known[-1], "won": float(final[0]) == 1.0},
                     {"league": league, "p": 1 - known[-1], "won": float(final[1]) == 1.0}]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--per-league", type=int, default=300)
    ap.add_argument("--cache", default="data/cache")
    a = ap.parse_args()
    http = Http(a.cache, ttl_s=7 * DAY, min_interval_s=0.03)
    pm = Polymarket(http)
    sports = {s["sport"]: s for s in http.get(f"{GAMMA}/sports", ttl=DAY)}
    rows = []
    for lg in LEAGUES:
        g = games(http, sports[lg]["series"], a.per_league)
        with ThreadPoolExecutor(8) as ex:
            for r in ex.map(lambda x: outcomes(pm, lg, x), g):
                rows += r
        print(f"  {lg}: {len(g)} partidos", file=sys.stderr)
    rows = [r for r in rows if 0.01 < r["p"] < 0.99]
    brier = statistics.fmean((r["p"] - r["won"]) ** 2 for r in rows)
    print(f"{len(rows)} resultados con precio 1 h antes del partido · Brier {brier:.4f}\n")
    print(f"  {'precio':<10} {'n':>5} {'precio medio':>13} {'ganó':>7} {'± 95 %':>7}")
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1)):
        s = [r for r in rows if lo <= r["p"] < hi]
        if len(s) < 15:
            continue
        w = statistics.fmean(r["won"] for r in s)
        print(f"  {lo:.1f}–{hi:.1f}    {len(s):>5} {statistics.fmean(r['p'] for r in s):>13.3f} {w:>7.3f} "
              f"{1.96 * (w * (1 - w) / len(s)) ** .5:>7.3f}")


if __name__ == "__main__":
    main()

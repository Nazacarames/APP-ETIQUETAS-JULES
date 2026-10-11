"""¿Hay apuestas de fútbol con alta tasa de acierto que además dejen ganancia? Simulación con 100 USD.

Datos: cuotas históricas de football-data.co.uk (gratis, para uso personal). Son 11 ligas europeas desde 2012/13
y la Liga Profesional Argentina. Para cada partido hay cuotas de varias casas, el promedio del mercado ("Avg") y
la mejor cuota disponible entre decenas de casas ("Max"), todas tomadas antes del partido, más el resultado.

    python3 research/apuestas_futbol.py            # baja lo que falte a data/football-data/ y analiza

Reglas: apuesta fija de 2 USD (2 % de 100) mientras alcance la plata. Tramo A = 2012/13–2021/22 (para elegir),
tramo B = 2022/23 en adelante (para confirmar). Simula; no apuesta.
"""
from __future__ import annotations

import csv
import random
import statistics
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "football-data"
LEAGUES = ["E0", "E1", "SP1", "I1", "D1", "F1", "N1", "P1", "SC0", "B1", "T1"]
SEASONS = ["1213", "1314", "1415", "1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324",
           "2425", "2526", "2627"]
OUT = ("H", "D", "A")
CAPITAL, STAKE = 100.0, 2.0


def download() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    urls = {f"{lg}_{s}.csv": f"https://www.football-data.co.uk/mmz4281/{s}/{lg}.csv" for s in SEASONS for lg in LEAGUES}
    urls["ARG.csv"] = "https://www.football-data.co.uk/new/ARG.csv"
    for name, url in urls.items():
        path = DATA / name
        if path.exists() and path.stat().st_size > 0 and not name.endswith("_2627.csv"):
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "polylens-research"})
            path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        except OSError as exc:
            print(f"  no pude bajar {url}: {exc}", file=sys.stderr)


def num(x) -> float | None:
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def odds(r: dict, *prefixes: str) -> list[float] | None:
    for p in prefixes:
        o = [num(r.get(f"{p}{k}")) for k in OUT]
        if all(o):
            return o
    return None


def load_europe() -> list[dict]:
    rows = []
    for path in sorted(DATA.glob("*_*.csv")):
        season = path.stem.split("_")[1]
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for r in csv.DictReader(fh):
                if r.get("FTR") in OUT:
                    rows.append({"season": season, "res": r["FTR"], "avg": odds(r, "Avg", "BbAv"),
                                 "max": odds(r, "Max", "BbMx"), "ps": odds(r, "PS"),
                                 **{b: odds(r, b) for b in ("B365", "BW", "WH")}})
    return rows


def boot(xs: list[float], n: int = 2000) -> tuple[float, float]:
    rng = random.Random(1)
    ms = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return ms[int(.025 * n)], ms[int(.975 * n)]


def line(name: str, bets: list[tuple[float, bool]]) -> None:
    """bets: (cuota cobrada, ganó) en orden cronológico."""
    if len(bets) < 10:
        print(f"  {name:<50} muy pocas apuestas ({len(bets)})")
        return
    rets = [(o - 1) if w else -1.0 for o, w in bets]
    cap, broke = CAPITAL, None
    for i, x in enumerate(rets):
        if cap < STAKE:
            broke = i
            break
        cap += STAKE * x
    lo, hi = boot(rets)
    hit = sum(w for _, w in bets) / len(bets)
    end = f"se quedó sin plata en la apuesta {broke}" if broke is not None else f"100 → {cap:.2f} USD"
    print(f"  {name:<50} n={len(bets):5d}  aciertos {hit:5.1%}  ROI {statistics.fmean(rets):+5.1%} "
          f"[{lo:+.1%}, {hi:+.1%}]  {end}")


def favorite_bets(rows, book, lo, hi, ref="avg", res="res"):
    bets = []
    for m in rows:
        o, r = m.get(book), m.get(ref)
        if not o or not r:
            continue
        k = min(range(3), key=lambda i: r[i])
        if lo <= r[k] < hi:
            bets.append((o[k], m[res] == OUT[k]))
    return bets


def fair(o: list[float]) -> list[float]:
    inv = [1 / x for x in o]
    return [x / sum(inv) for x in inv]


def value_bets(rows, book, edge, minp=0.0):
    bets = []
    for m in rows:
        if not m["ps"] or not m.get(book):
            continue
        for k, p in enumerate(fair(m["ps"])):
            if p >= minp and p * m[book][k] - 1 > edge:
                bets.append((m[book][k], m["res"] == OUT[k]))
    return bets


def main() -> None:
    download()
    rows = load_europe()
    A = [m for m in rows if m["season"] <= "2122"]
    B = [m for m in rows if m["season"] > "2122"]
    print(f"{len(rows)} partidos de 11 ligas europeas (2012/13 → 2026/27). Apuesta fija de {STAKE:.0f} USD sobre "
          f"{CAPITAL:.0f} USD.\nEntre corchetes, intervalo de confianza del 95 % del ROI por apuesta.\n")

    print("1) Apostar siempre al favorito, según su cuota promedio")
    for lo, hi in ((1.01, 1.25), (1.25, 1.40), (1.40, 1.60), (1.60, 1.90)):
        for book, label in (("avg", "cuota promedio"), ("max", "mejor cuota de todas las casas")):
            for part, sel in (("A", A), ("B", B)):
                line(f"{part} · favorito {lo:.2f}–{hi:.2f}, {label}", favorite_bets(sel, book, lo, hi))

    print("\n2) Favorito 1.25–1.40 comparando entre pocas casas (lo que puede hacer una persona), 2019/20 →")
    recent = [m for m in rows if m["season"] >= "1920"]
    for books in (["B365"], ["B365", "BW"], ["B365", "BW", "WH"], ["B365", "BW", "WH", "ps"]):
        sel = []
        for m in recent:
            os_ = [m.get(b) for b in books]
            if all(os_):
                sel.append({**m, "best": [max(o[i] for o in os_) for i in range(3)]})
        line(f"mejor de {len(books)} casa(s)", favorite_bets(sel, "best", 1.25, 1.40))

    print("\n3) Value betting: cuota de una casa por encima de la probabilidad justa de Pinnacle (sin margen)")
    for book in ("max", "B365"):
        for edge in (0.02, 0.05):
            for part, sel in (("A", A), ("B", B)):
                line(f"{part} · {book}, ventaja > {edge:.0%}", value_bets(sel, book, edge))
    for part, sel in (("A", A), ("B", B)):
        line(f"{part} · max, ventaja > 2 %, solo probabilidad ≥ 60 %", value_bets(sel, "max", 0.02, 0.60))

    print("\n4) Surebets 1X2 (cubrir los tres resultados con ganancia asegurada)")
    for label, get in (("mejor cuota de todas las casas", lambda m: m["max"]),
                       ("mejor de 4 casas grandes", lambda m: [max(o[i] for o in os_) for i in range(3)]
                        if all(os_ := [m.get(b) for b in ("B365", "BW", "WH", "ps")]) else None)):
        n = 0
        margins = []
        for m in rows:
            o = get(m)
            if not o:
                continue
            n += 1
            s = sum(1 / x for x in o)
            if s < 1:
                margins.append(1 / s - 1)
        med = statistics.median(margins) if margins else 0.0
        print(f"  {label:<32} en {len(margins) / n:5.1%} de los partidos; ganancia mediana {med:.2%} "
              f"(≈ {CAPITAL * med:.2f} USD por partido con 100 USD)")

    print("\n5) Liga Profesional Argentina (cuotas de cierre)")
    arg = []
    with open(DATA / "ARG.csv", encoding="utf-8-sig", errors="replace") as fh:
        for r in csv.DictReader(fh):
            if r.get("Res") in OUT:
                arg.append({"res": r["Res"], "avg": odds(r, "AvgC"), "max": odds(r, "MaxC")})
    print(f"  {len(arg)} partidos; empates: {sum(m['res'] == 'D' for m in arg) / len(arg):.1%}")
    for lo, hi in ((1.01, 1.50), (1.50, 1.80), (1.80, 2.20)):
        for book, label in (("avg", "cuota promedio"), ("max", "mejor cuota")):
            line(f"favorito {lo:.2f}–{hi:.2f}, {label}", favorite_bets(arg, book, lo, hi))


if __name__ == "__main__":
    main()

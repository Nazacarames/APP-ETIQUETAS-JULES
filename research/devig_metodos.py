"""¿Qué método para quitar el margen da probabilidades más certeras? Prueba con las cuotas de Pinnacle.

Usa los partidos de football-data.co.uk que baja research/apuestas_futbol.py (11 ligas europeas desde 2012/13 y
la Liga Profesional Argentina). Para cada partido convierte las cuotas 1X2 de Pinnacle en probabilidades con cada
método y mide log-loss y Brier contra el resultado (menor es mejor), en total y por rango de cuota.

    python3 research/apuestas_futbol.py   # (una vez) baja los datos
    python3 research/devig_metodos.py
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from futbol.cuotas import fair_probs  # noqa: E402

DATA = ROOT / "data" / "football-data"
OUT = ("H", "D", "A")
METHODS = ("multiplicative", "power", "shin")


def num(x):
    try:
        v = float(x)
        return v if v > 1 else None
    except (TypeError, ValueError):
        return None


def load():
    rows = []
    for path in sorted(DATA.glob("*.csv")):
        argentina = path.name == "ARG.csv"
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for r in csv.DictReader(fh):
                res = r.get("Res" if argentina else "FTR")
                pre = "PSC" if argentina else "PS"
                o = [num(r.get(f"{pre}{k}")) for k in OUT]
                if res in OUT and all(o):
                    rows.append({"odds": dict(zip(OUT, o)), "res": res, "arg": argentina})
    return rows


def main() -> None:
    rows = load()
    if not rows:
        sys.exit("No hay datos: corré primero python3 research/apuestas_futbol.py")
    print(f"{len(rows)} partidos con cuotas 1X2 de Pinnacle ({sum(r['arg'] for r in rows)} de la Liga Argentina)\n")
    print(f"{'método':<16} {'log-loss':>9} {'Brier':>8}   log-loss según la cuota del resultado:  <2   2-4   4-8   >8")
    for m in METHODS:
        ll, br, by = [], [], {0: [], 1: [], 2: [], 3: []}
        for r in rows:
            p = fair_probs(r["odds"], m)
            ll.append(-math.log(max(p[r["res"]], 1e-9)))
            br.append(sum((p[k] - (k == r["res"])) ** 2 for k in OUT))
            o = r["odds"][r["res"]]
            by[0 if o < 2 else 1 if o < 4 else 2 if o < 8 else 3].append(ll[-1])
        cells = "  ".join(f"{statistics.fmean(v):.3f}" if v else "  –  " for v in by.values())
        print(f"{m:<16} {statistics.fmean(ll):>9.5f} {statistics.fmean(br):>8.5f}   {' ' * 37}{cells}")
    print("\nCalibración de los batacazos (cuota de Pinnacle ≥ 6): probabilidad media según cada método vs. lo que pasó")
    sel = [(r, k) for r in rows for k in OUT if r["odds"][k] >= 6]
    real = statistics.fmean(1.0 if r["res"] == k else 0.0 for r, k in sel)
    for m in METHODS:
        pred = statistics.fmean(fair_probs(r["odds"], m)[k] for r, k in sel)
        print(f"  {m:<16} dice {pred:.2%}  ·  pasó {real:.2%}  (n={len(sel)})")


if __name__ == "__main__":
    main()

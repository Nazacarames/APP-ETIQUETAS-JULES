"""Minutos de partido: ¿qué tan probable es otro gol desde el minuto X, según cómo va el resultado?

Sirve para apuestas en vivo del tipo "habrá otro gol" o "más de N,5 goles": si la cuota en vivo paga más que
1 / probabilidad histórica (con margen), hay valor. Solo usa partidos terminados de la base local.
Ojo: en vivo la casa ve los datos antes que vos y suspende en las jugadas peligrosas; esto es una referencia.
"""
from __future__ import annotations

import math
import statistics

CHECKPOINTS = (15, 30, 45, 60, 70, 75, 80, 85)


def score_at(goals: list[dict], minute: int) -> tuple[int, int]:
    """Resultado al empezar el minuto `minute` (goles anotados antes de ese minuto)."""
    h = sum(1 for g in goals if g["minute"] < minute and g["home"])
    a = sum(1 for g in goals if g["minute"] < minute and not g["home"])
    return h, a


def state_label(h: int, a: int) -> str:
    if h == a:
        return "0-0" if h == 0 else "empate con goles"
    return "diferencia de 1" if abs(h - a) == 1 else "diferencia de 2 o más"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - half), min(1.0, c + half)


def another_goal(matches: list[dict], minute: int, state: str | None = None) -> dict:
    """P(al menos un gol más desde `minute` hasta el final), opcionalmente solo con ese estado del resultado."""
    n = k = 0
    for m in matches:
        h, a = score_at(m["goals"], minute)
        if state and state_label(h, a) != state:
            continue
        n += 1
        k += any(g["minute"] >= minute for g in m["goals"])
    lo, hi = wilson(k, n)
    p = k / n if n else None
    return {"minute": minute, "state": state or "todos", "n": n, "p": p, "ci95": (lo, hi),
            "fair_odd": (1 / p) if p else None}


def table(matches: list[dict]) -> list[dict]:
    rows = []
    for minute in CHECKPOINTS:
        rows.append(another_goal(matches, minute))
        for st in ("0-0", "empate con goles", "diferencia de 1", "diferencia de 2 o más"):
            r = another_goal(matches, minute, st)
            if r["n"] >= 15:
                rows.append(r)
    return rows


def goals_by_period(matches: list[dict]) -> list[dict]:
    """Goles por tramo de 15 minutos (el último incluye el descuento)."""
    edges = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75), (76, 90)]
    total = sum(len(m["goals"]) for m in matches) or 1
    out = []
    for lo, hi in edges:
        c = sum(1 for m in matches for g in m["goals"] if lo <= max(g["minute"], 1) <= hi)
        out.append({"tramo": f"{lo}-{hi}", "goles": c, "share": c / total,
                    "por_partido": c / len(matches) if matches else 0.0})
    return out


def live_value(matches: list[dict], minute: int, home: int, away: int, odd: float) -> dict:
    """¿Paga bien la cuota en vivo de "otro gol"? Usa partidos con el mismo estado; si son pocos, todos."""
    r = another_goal(matches, minute, state_label(home, away))
    if r["n"] < 30:
        r = another_goal(matches, minute)
    p = r["p"] or 0.0
    return {**r, "odd": odd, "ev": p * odd - 1, "ev_low": r["ci95"][0] * odd - 1,
            "avg_goals_per_match": statistics.fmean(len(m["goals"]) for m in matches) if matches else None}

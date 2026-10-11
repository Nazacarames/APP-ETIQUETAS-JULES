"""Flujos de "smart money": en qué mercados están hoy los traders que pasaron el filtro estadístico.

Solo lectura: muestra posiciones abiertas públicas, coincidencias y desacuerdos entre traders.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .polymarket import Polymarket

GOOD = ("sólido", "prometedor")


def select_traders(profiles: list[dict], top: int = 20, include_all: bool = False) -> list[dict]:
    chosen = profiles if include_all else [p for p in profiles if p.get("significance") in GOOD]
    return chosen[:top]


def smart_flows(pm: Polymarket, profiles: list[dict], top: int = 20, include_all: bool = False,
                min_value: float = 50.0, workers: int = 4,
                progress: Callable[[str], None] = lambda s: None) -> dict:
    traders = select_traders(profiles, top, include_all)
    progress(f"leyendo posiciones abiertas de {len(traders)} traders")

    def fetch(p):
        try:
            return p, pm.positions(p["user"], "OPEN", limit=500, sort_by="CURRENT_VALUE")
        except Exception:
            return p, []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        fetched = list(ex.map(fetch, traders))

    markets: dict[tuple, dict] = {}
    by_condition: dict[str, set] = {}
    for prof, positions in fetched:
        name = prof.get("name") or prof["user"][:10]
        for pos in positions:
            price = float(pos.get("current_price") or 0)
            value = float(pos.get("current_value") or 0)
            if pos.get("redeemable") or not 0.01 <= price <= 0.99 or value < min_value:
                continue  # ya resuelto, sin precio útil o demasiado chico
            key = (pos.get("condition_id"), pos.get("outcome"))
            m = markets.setdefault(key, {"title": pos.get("title"), "outcome": pos.get("outcome"),
                                         "event_slug": pos.get("event_slug"), "end_date": pos.get("end_date"),
                                         "condition_id": pos.get("condition_id"), "current_price": price,
                                         "traders": [], "value": 0.0, "cost": 0.0})
            cost = float(pos.get("avg_price") or 0) * float(pos.get("current_size") or 0)
            m["traders"].append({"name": name, "user": prof["user"], "value": round(value, 2),
                                 "avg_price": pos.get("avg_price"), "significance": prof.get("significance")})
            m["value"] += value
            m["cost"] += cost
            by_condition.setdefault(pos.get("condition_id"), set()).add(pos.get("outcome"))

    rows = []
    for m in markets.values():
        size = sum(float(t["value"]) / max(m["current_price"], 1e-9) for t in m["traders"])
        m["n"] = len(m["traders"])
        m["avg_entry"] = round(m["cost"] / size, 4) if size else None
        m["upside_if_wins"] = round(1 / m["current_price"] - 1, 3)  # cuánto paga cada dólar si ese resultado gana
        m["disputed"] = len(by_condition.get(m["condition_id"], ())) > 1  # otros buenos apuestan al resultado contrario
        m["value"] = round(m["value"], 2)
        del m["cost"]
        rows.append(m)
    rows.sort(key=lambda m: (m["n"], m["value"]), reverse=True)
    return {"traders": [{"name": p.get("name"), "user": p["user"], "significance": p.get("significance")}
                        for p in traders], "markets": rows}

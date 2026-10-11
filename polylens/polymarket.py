"""Lectura de datos públicos de Polymarket (Data API v2 y Gamma). Sin claves, sin órdenes.

Docs: https://docs.polymarket.com  ·  spec: https://data-api.polymarket.com/v2/openapi.json
"""
from __future__ import annotations

import json
from typing import Any

from .http import Http

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"

HOUR = 3600
DAY = 86_400
# Estados de posición que ya tienen resultado: cerradas, ganadas sin cobrar y perdidas que se dejaron vencer.
RESOLVED_STATUSES = ("CLOSED", "REDEEMABLE", "REDEEMABLE_LOST")


class Polymarket:
    def __init__(self, http: Http):
        self.http = http

    # -- traders ---------------------------------------------------------------
    def leaderboard(self, period: str = "month", category: str = "overall", sort_by: str = "PNL",
                    limit: int = 100) -> list[dict]:
        """period: day | week | month | all. category: overall, sports, politics, crypto, ..."""
        rows = self.http.paginate(f"{DATA}/v2/leaderboard",
                                  {"time_period": period, "category": category, "sort_by": sort_by},
                                  max_items=limit, page_size=min(limit, 100), ttl=HOUR)
        return list(rows)

    def user_stats(self, user: str) -> dict | None:
        return (self.http.get(f"{DATA}/v2/user-stats", {"user": user}, ttl=HOUR) or {}).get("data")

    def positions(self, user: str, status: str = "OPEN", limit: int = 1000, sort_by: str | None = None,
                  start: int | None = None) -> list[dict]:
        return list(self.http.paginate(f"{DATA}/v2/positions",
                                       {"user": user, "status": status, "sort_by": sort_by, "start": start},
                                       max_items=limit, ttl=HOUR))

    def resolved_positions(self, user: str, since: int | None = None, cap_per_status: int = 2000) -> tuple[list[dict], int | None]:
        """Posiciones con resultado (cerradas, ganadas sin cobrar y perdidas sin cerrar) en una MISMA ventana.

        Importante: por defecto la API ordena las cerradas por ganancia, así que cortar la lista deja solo
        las ganadoras. Acá se piden ordenadas por fecha (TIMESTAMP = last_event_at) desde `since`; si algún
        tipo llega al tope, todos se recortan a la misma fecha para no mezclar ventanas distintas.
        Devuelve (posiciones, inicio efectivo de la ventana).
        """
        by_status: dict[str, list[dict]] = {}
        floor = since
        for status in RESOLVED_STATUSES:
            rows = self.positions(user, status, cap_per_status, sort_by="TIMESTAMP", start=since)
            by_status[status] = rows
            if len(rows) >= cap_per_status and rows:
                oldest = min(int(r.get("last_event_at") or 0) for r in rows)
                floor = max(floor or 0, oldest)
        seen, out = set(), []
        for status in RESOLVED_STATUSES:
            for p in by_status[status]:
                if floor and int(p.get("last_event_at") or 0) < floor:
                    continue
                key = p.get("token_id") or (p.get("condition_id"), p.get("outcome"))
                if key in seen:
                    continue
                seen.add(key)
                out.append(p)
        return out, floor

    def trades(self, user: str | None = None, condition: str | None = None, start: int | None = None,
               end: int | None = None, side: str | None = None, taker_only: bool = True,
               limit: int = 1000) -> list[dict]:
        """Operaciones, de la más nueva a la más vieja. Para ver TODO lo que hizo un trader (también sus
        órdenes límite) hay que pasar taker_only=False; si no, la API muestra solo cuando tomó liquidez."""
        return list(self.http.paginate(f"{DATA}/v2/trades",
                                       {"user": user, "condition": condition, "start": start, "end": end,
                                        "side": side, "taker_only": taker_only},
                                       max_items=limit, ttl=HOUR))

    # -- mercados -------------------------------------------------------------
    def holders(self, condition: str, limit: int = 100) -> list[dict]:
        return list(self.http.paginate(f"{DATA}/v2/holders", {"condition": condition, "include_pnl": True},
                                       max_items=limit, ttl=HOUR))

    MAX_SPAN = 15 * DAY  # la API acepta como máximo 15 días entre start y end

    def prices_history(self, token_id: str, start: int, end: int, ttl: float | None = None) -> list[tuple[int, float]]:
        """Serie (timestamp, precio) de un token de resultado, con la resolución que elige la API
        (forzar bucket_seconds puede devolver vacío). Ventanas largas se piden en tramos de 15 días.
        Los mercados ya resueltos no cambian: conviene pasar un ttl largo."""
        out: dict[int, float] = {}
        t = int(start)
        while t < end:
            chunk_end = min(int(end), t + self.MAX_SPAN)
            for r in self.http.paginate(f"{DATA}/v2/prices-history",
                                        {"token_id": token_id, "start": t, "end": chunk_end},
                                        max_items=10_000, page_size=10_000, ttl=ttl):
                if r.get("price") is not None:
                    out[int(r["timestamp"])] = float(r["price"])
            t = chunk_end
        return sorted(out.items())

    def markets(self, condition_ids: list[str]) -> dict[str, dict]:
        """Metadatos de Gamma por condition_id (abiertos y cerrados), en tandas de 20."""
        out: dict[str, dict] = {}
        ids = list(dict.fromkeys(c for c in condition_ids if c))
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            for closed in (True, False):
                rows = self.http.get(f"{GAMMA}/markets",
                                     {"condition_ids": chunk, "closed": closed, "limit": 100},
                                     ttl=DAY if closed else HOUR) or []
                for m in rows:
                    cid = m.get("conditionId")
                    if cid:
                        out[cid] = m
        return out


def parse_list(value: Any) -> list:
    """Gamma devuelve listas como texto JSON ('["Yes", "No"]')."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value or "[]")
    except (TypeError, ValueError):
        return []


def token_outcome_price(market: dict, token_id: str) -> float | None:
    """Precio final (1 ganó, 0 perdió) de un token en un mercado ya resuelto de Gamma."""
    if not market or not market.get("closed"):
        return None
    tokens = [str(t) for t in parse_list(market.get("clobTokenIds"))]
    prices = parse_list(market.get("outcomePrices"))
    if token_id in tokens and len(prices) == len(tokens):
        try:
            return float(prices[tokens.index(token_id)])
        except (TypeError, ValueError):
            return None
    return None

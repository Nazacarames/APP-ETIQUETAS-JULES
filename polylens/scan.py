"""Escaneo: toma el ranking de Polymarket, arma el perfil de cada trader y los reordena por consistencia."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from .polymarket import Polymarket
from .profiles import build_profile, position_result, rank, thresholds


def scan(pm: Polymarket, period: str = "month", category: str = "overall", top: int = 100,
         days: int = 90, cap_per_status: int = 2000, categorizer=None, workers: int = 4, min_positions: int = 20,
         progress: Callable[[str], None] = lambda s: None, now: float | None = None) -> dict:
    since = int((now or time.time()) - days * 86_400)
    board = pm.leaderboard(period, category, limit=top)
    progress(f"ranking de Polymarket: {len(board)} traders ({period}, {category})")

    def fetch(row):
        user = row["user_id"]
        try:
            positions, floor = pm.resolved_positions(user, since, cap_per_status)
            return row, positions, pm.user_stats(user), None, floor
        except Exception as exc:  # un trader con error no frena el escaneo
            return row, [], None, repr(exc), None

    fetched = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, item in enumerate(ex.map(fetch, board), 1):
            fetched.append(item)
            if k % 10 == 0 or k == len(board):
                progress(f"  posiciones leídas: {k}/{len(board)}")

    if categorizer:
        items = []
        for _, positions, _, _, _ in fetched:
            for p in positions:
                r = position_result(p)
                if r:
                    items.append((r.cost, r.event_slug, r.title))
        items = [(slug, title) for _, slug, title in sorted(items, key=lambda x: -x[0])]  # si hay tope, Jev ve lo grande
        progress(f"clasificando {len({s or t for s, t in items})} eventos por categoría...")
        categorizer.classify_many(items)

    profiles, errors = [], {}
    for row, positions, stats, err, floor in fetched:
        if err:
            errors[row["user_id"]] = err
            continue
        prof = build_profile(row["user_id"], positions, stats, row, categorizer, now)
        prof.window_days = round(((now or time.time()) - floor) / 86_400, 1) if floor else float(days)
        profiles.append(prof)
    ranked = rank(profiles, min_positions)
    return {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "period": period,
                 "category": category, "top": top, "days": days, "analyzed": len(ranked), "errors": errors,
                 "min_positions": min_positions, "thresholds": thresholds(len(ranked)),
                 "categorizer": categorizer.name if categorizer else None},
        "profiles": [p.to_dict() for p in ranked],
    }

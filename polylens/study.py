"""Estudio de copiabilidad: ¿qué habría pasado si alguien copiaba las compras de estos traders con demora?

Se trabaja con las compras reales del trader (su historial de operaciones, incluidas órdenes límite),
no con el resumen por posición: quien entra y sale muchas veces del mismo mercado tiene un precio
promedio que no describe ninguna compra concreta.

Para cada compra (fills del mismo token dentro de una hora = una entrada), en mercados ya resueltos:
- El trader: precio promedio de esa entrada → valor final (1 si ganó, 0 si perdió).
- El copiador: compra el mismo resultado `demora` después, al precio que había en ese momento más un
  deslizamiento, y lo mantiene hasta la resolución. Si el mercado ya se resolvió, esa compra no se pudo copiar.

Así se separan dos cosas: si las entradas del trader tienen ventaja (mantener hasta el final rinde) y
cuánto de esa ventaja sobrevive a la demora (el precio ya se movió). Es análisis histórico: no opera.
"""
from __future__ import annotations

import random
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .flows import select_traders
from .polymarket import DAY, Polymarket, token_outcome_price

DELAYS = (0, 3600, 6 * 3600, 86_400)
GROUP_S = 3600            # fills del mismo token dentro de una hora = una sola entrada
TOLERANCE_S = 2 * 3600    # el precio "a la hora t" tiene que estar observado a menos de 2 h
FINAL_TTL = 30 * DAY      # los precios de mercados ya resueltos no cambian


@dataclass
class Entry:
    token_id: str
    condition_id: str
    title: str
    outcome: str
    ts: int          # primer fill
    price: float     # precio promedio ponderado de los fills
    usd: float
    fills: int


def group_entries(trades: list[dict], group_s: int = GROUP_S) -> list[Entry]:
    """Agrupa las compras (BUY) del mismo token que caen dentro de `group_s` desde la primera."""
    buys = sorted((t for t in trades if t.get("side") == "BUY"), key=lambda t: int(t.get("timestamp") or 0))
    out: list[Entry] = []
    acc: dict[str, dict] = {}

    def close(a: dict) -> None:
        if a["size"] > 0:
            out.append(Entry(a["token_id"], a["condition_id"], a["title"], a["outcome"], a["ts"],
                             a["usd"] / a["size"], a["usd"], a["fills"]))

    for t in buys:
        try:
            tok, ts = str(t["token_id"]), int(t["timestamp"])
            size, price = float(t["size"]), float(t["price"])
        except (KeyError, TypeError, ValueError):
            continue
        a = acc.get(tok)
        if a is None or ts - a["ts"] > group_s:
            if a is not None:
                close(a)
            a = acc[tok] = {"token_id": tok, "condition_id": t.get("condition_id") or "", "title": t.get("title") or "",
                            "outcome": t.get("outcome") or "", "ts": ts, "size": 0.0, "usd": 0.0, "fills": 0}
        a["size"] += size
        a["usd"] += size * price
        a["fills"] += 1
    for a in acc.values():
        close(a)
    return sorted(out, key=lambda e: e.ts)


def price_at(series: list[tuple[int, float]], ts: int, tolerance: int | None = None) -> float | None:
    """Primer precio observado en o después de `ts` (y a no más de `tolerance` segundos)."""
    for t, p in series:
        if t >= ts:
            return p if tolerance is None or t - ts <= tolerance else None
    return None


def parse_ts(v) -> int | None:
    """Fechas de Gamma: '2025-10-05T12:00:00Z', '2025-10-05 18:22:13+00', '2025-10-05'. Sin zona = UTC."""
    if not v:
        return None
    s = str(v).strip().replace(" ", "T").replace("Z", "+00:00")
    if re.search(r"[+-]\d\d$", s):
        s += ":00"  # '+00' -> '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def end_ts(market: dict) -> int | None:
    """Momento en que el mercado dejó de operar (cierre real si está, si no la fecha prevista)."""
    for key in ("closedTime", "umaEndDate", "endDate"):
        ts = parse_ts((market or {}).get(key))
        if ts:
            return ts
    return None


def copier_return(entry: float, final: float, slippage: float) -> float:
    """Comprar a `entry` + deslizamiento y cobrar `final` (1, 0 o 0,5 si se anuló)."""
    return final / min(0.999, entry + slippage) - 1


def study_entry(pm: Polymarket, e: Entry, market: dict, delays=DELAYS, slippage: float = 0.01) -> dict | None:
    final = token_outcome_price(market, e.token_id)
    if final is None:
        return None
    end = end_ts(market)
    series = pm.prices_history(e.token_id, e.ts - 600, e.ts + max(delays) + TOLERANCE_S, ttl=FINAL_TTL)
    row = {"title": e.title, "outcome": e.outcome, "ts": e.ts, "price": round(e.price, 4), "usd": round(e.usd, 2),
           "final": final, "trader_ret": final / e.price - 1, "copier": {}, "gap": {}}
    for d in delays:
        t = e.ts + d
        if end and t >= end:
            continue  # ya se había resuelto: no había nada que copiar
        p = price_at(series, t, TOLERANCE_S)
        if p is None or not 0 < p < 1:
            continue
        row["copier"][str(d)] = copier_return(p, final, slippage)
        row["gap"][str(d)] = p - e.price  # >0: el precio subió después de que compró (pagás más caro)
    return row


def bootstrap_ci(xs: list[float], n: int = 2000, seed: int = 3) -> tuple[float, float] | None:
    if len(xs) < 5:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def _stats(xs: list[float]) -> dict:
    ci = bootstrap_ci(xs)
    return {"n": len(xs), "mean": statistics.fmean(xs), "median": statistics.median(xs),
            "win_rate": sum(1 for x in xs if x > 0) / len(xs), "ci95": list(ci) if ci else None}


def summarize(rows: list[dict], delays=DELAYS) -> dict:
    out: dict = {"n": len(rows), "trader": _stats([r["trader_ret"] for r in rows]) if rows else None, "by_delay": {}}
    for d in delays:
        k = str(d)
        xs = [r["copier"][k] for r in rows if k in r["copier"]]
        if xs:
            out["by_delay"][k] = {**_stats(xs), "gap_mean": statistics.fmean(r["gap"][k] for r in rows if k in r["gap"])}
    out["verdict"] = verdict(out)
    return out


def verdict(summary: dict, delay: int = 3600) -> str:
    """Lectura corta para el reporte, mirando la demora de 1 hora (realista para alguien que sigue alertas)."""
    s = summary.get("by_delay", {}).get(str(delay))
    if not s or s["n"] < 20:
        return "muestra chica"
    ci = s.get("ci95")
    if ci and ci[0] > 0:
        return "copiable (con demora de 1 h sigue ganando)"
    if ci and ci[1] < 0:
        return "no copiable (con demora pierde)"
    return "no concluyente"


def copy_study(pm: Polymarket, profiles: list[dict], top: int = 10, sample: int = 60, days: int = 30,
               min_usd: float = 100.0, max_fills: int = 3000, max_markets: int = 300, include_all: bool = False,
               delays=DELAYS, slippage: float = 0.01, seed: int = 7, workers: int = 4,
               progress: Callable[[str], None] = lambda s: None, now: float | None = None) -> dict:
    now = now or time.time()
    since = int(now - days * DAY)
    traders = select_traders(profiles, top, include_all)
    rng = random.Random(seed)
    results, pooled = [], []
    for k, prof in enumerate(traders, 1):
        fills = pm.trades(prof["user"], start=since, side="BUY", taker_only=False, limit=max_fills)
        window = round((now - min(int(f["timestamp"]) for f in fills)) / DAY, 1) if fills else 0.0
        entries = [e for e in group_entries(fills) if e.usd >= min_usd and 0.02 <= e.price <= 0.98]
        conditions = list(dict.fromkeys(e.condition_id for e in reversed(entries)))[:max_markets]
        markets = pm.markets(conditions)
        resolved = [e for e in entries if token_outcome_price(markets.get(e.condition_id, {}), e.token_id) is not None]
        chosen = rng.sample(resolved, min(sample, len(resolved)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            studied = [s for s in ex.map(lambda e: _safe(pm, e, markets.get(e.condition_id, {}), delays, slippage),
                                         chosen) if s]
        summary = summarize(studied, delays)
        summary.update({"fills": len(fills), "entries": len(entries), "resolved": len(resolved), "window_days": window})
        results.append({"name": prof.get("name"), "user": prof["user"], "significance": prof.get("significance"),
                        "summary": summary, "rows": studied})
        pooled.extend(studied)
        progress(f"  {k}/{len(traders)} {prof.get('name') or prof['user'][:10]}: {len(entries)} entradas, "
                 f"{len(resolved)} en mercados resueltos, {len(studied)} estudiadas → {summary['verdict']}")
    return {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": days,
                     "sample": sample, "min_usd": min_usd, "slippage": slippage, "delays": list(delays)},
            "traders": results, "pooled": summarize(pooled, delays)}


def _safe(pm, e, market, delays, slippage):
    try:
        return study_entry(pm, e, market, delays, slippage)
    except Exception:
        return None

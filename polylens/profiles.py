"""Perfil de un trader a partir de sus posiciones con resultado.

Cada posición se mide por su retorno sobre lo invertido (pnl / costo, con costo = precio
promedio × cantidad). Se incluyen las cerradas, las ganadas sin cobrar y las perdidas que se
dejaron vencer: si no, quien nunca cierra sus apuestas perdedoras parecería infalible.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

MIN_COST_USD = 10.0     # posiciones más chicas se ignoran (polvo, pruebas)
CLIP_RET = (-1.0, 10.0)  # para medir consistencia, un +5000 % no puede dominar todo


@dataclass(frozen=True)
class PositionResult:
    title: str
    condition_id: str
    token_id: str
    outcome: str
    event_slug: str
    status: str
    avg_price: float
    size: float
    cost: float
    pnl: float
    ret: float
    first_entry: int
    last_event: int
    end_date: str


def position_result(p: dict) -> PositionResult | None:
    try:
        price = float(p.get("avg_price") or 0)
        size = float(p.get("total_size") or 0)
        pnl = float(p.get("total_pnl") if p.get("total_pnl") is not None else p.get("realized_pnl") or 0)
    except (TypeError, ValueError):
        return None
    cost = price * size
    if cost < MIN_COST_USD or price <= 0:
        return None
    return PositionResult(
        title=p.get("title") or "", condition_id=p.get("condition_id") or "", token_id=str(p.get("token_id") or ""),
        outcome=p.get("outcome") or "", event_slug=p.get("event_slug") or "", status=p.get("status") or "",
        avg_price=price, size=size, cost=cost, pnl=pnl, ret=pnl / cost,
        first_entry=int(p.get("first_entry_at") or 0), last_event=int(p.get("last_event_at") or 0),
        end_date=p.get("end_date") or "")


@dataclass
class TraderProfile:
    user: str
    name: str = ""
    board_pnl: float = 0.0          # ganancia según el ranking de Polymarket (período pedido)
    board_volume: float = 0.0
    n: int = 0                      # posiciones con resultado analizadas
    total_pnl: float = 0.0
    total_cost: float = 0.0
    roi: float = 0.0                # suma de pnl / suma de costo
    win_rate: float = 0.0
    mean_ret: float = 0.0
    median_ret: float = 0.0
    t_stat: float = 0.0             # consistencia: media / desvío × √n (retornos recortados)
    top_share: float = 0.0          # parte de la ganancia que explica la mejor posición
    worst_loss: float = 0.0
    share_favorites: float = 0.0    # parte del dinero puesto a precio ≥ 0,90 ("casi seguros")
    share_longshots: float = 0.0    # parte del dinero puesto a precio ≤ 0,20 ("batacazos")
    roi_first_half: float = 0.0     # ¿siguió ganando? ROI de la primera y la segunda mitad
    roi_second_half: float = 0.0
    trades: int = 0
    trades_per_day: float = 0.0
    late_longshot_wins: int = 0     # apuestas grandes a ≤0,20, ganadas, hechas a <48 h del cierre
    window_days: float = 0.0        # ventana analizada (puede ser menor a la pedida si hubo recorte)
    categories: dict[str, dict] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    score: float = 0.0
    significance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _roi(rows: list[PositionResult]) -> float:
    cost = sum(r.cost for r in rows)
    return sum(r.pnl for r in rows) / cost if cost else 0.0


def _end_ts(end_date: str) -> int | None:
    from datetime import datetime, timezone
    try:
        return int(datetime.strptime(end_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 86_400
    except (ValueError, TypeError):
        return None


def build_profile(user: str, positions: list[dict], stats: dict | None = None, board: dict | None = None,
                  categorize: Callable[[PositionResult], str] | None = None, now: float | None = None) -> TraderProfile:
    import time
    rows = [r for r in (position_result(p) for p in positions) if r]
    rows.sort(key=lambda r: r.first_entry)
    prof = TraderProfile(user=user, name=(board or {}).get("user_name") or "",
                         board_pnl=float((board or {}).get("pnl") or 0), board_volume=float((board or {}).get("volume") or 0))
    stats = stats or {}
    prof.trades = int(stats.get("trades") or 0)
    joined = stats.get("join_date")
    if joined and prof.trades:
        days = max(1.0, ((now or time.time()) - float(joined)) / 86_400)
        prof.trades_per_day = prof.trades / days
    if not rows:
        prof.flags.append("sin posiciones con resultado para analizar")
        return prof

    prof.n = len(rows)
    rets = [r.ret for r in rows]
    prof.total_pnl = sum(r.pnl for r in rows)
    prof.total_cost = sum(r.cost for r in rows)
    prof.roi = _roi(rows)
    prof.win_rate = sum(1 for r in rows if r.pnl > 0) / len(rows)
    prof.mean_ret = statistics.fmean(rets)
    prof.median_ret = statistics.median(rets)
    clipped = [min(max(x, CLIP_RET[0]), CLIP_RET[1]) for x in rets]
    if len(clipped) >= 2:
        sd = statistics.pstdev(clipped)
        prof.t_stat = statistics.fmean(clipped) / sd * math.sqrt(len(clipped)) if sd > 0 else 0.0
    gains = [r.pnl for r in rows if r.pnl > 0]
    prof.top_share = max(gains) / sum(gains) if gains else 0.0
    prof.worst_loss = min(r.pnl for r in rows)
    prof.share_favorites = sum(r.cost for r in rows if r.avg_price >= 0.90) / prof.total_cost
    prof.share_longshots = sum(r.cost for r in rows if r.avg_price <= 0.20) / prof.total_cost
    half = len(rows) // 2
    if half >= 5:
        prof.roi_first_half, prof.roi_second_half = _roi(rows[:half]), _roi(rows[half:])
    for r in rows:
        end = _end_ts(r.end_date)
        if r.avg_price <= 0.20 and r.cost >= 5_000 and r.pnl > 0 and end and 0 <= end - r.first_entry <= 2 * 86_400:
            prof.late_longshot_wins += 1
    if categorize:
        cats: dict[str, list[PositionResult]] = {}
        for r in rows:
            cats.setdefault(categorize(r), []).append(r)
        prof.categories = {c: {"n": len(v), "pnl": round(sum(x.pnl for x in v), 2), "roi": round(_roi(v), 4)}
                           for c, v in sorted(cats.items(), key=lambda kv: -sum(x.cost for x in kv[1]))}
    prof.flags = flags_for(prof)
    return prof


def flags_for(p: TraderProfile) -> list[str]:
    out = []
    if p.n < 20:
        out.append(f"pocas posiciones ({p.n}): el resultado puede ser suerte")
    if p.top_share > 0.5 and p.total_pnl > 0:
        out.append(f"una sola apuesta explica el {p.top_share:.0%} de lo ganado")
    if p.share_favorites > 0.5:
        out.append(f"{p.share_favorites:.0%} del dinero en 'casi seguros' (≥0,90): gana seguido, pero cada error cuesta caro")
    if p.share_longshots > 0.5:
        out.append(f"{p.share_longshots:.0%} del dinero en batacazos (≤0,20): pierde seguido y vive de pocos aciertos")
    if p.trades_per_day > 300:
        out.append(f"{p.trades_per_day:.0f} operaciones por día: probable bot o market maker, difícil de copiar")
    if p.roi_first_half > 0 and p.roi_second_half < 0:
        out.append("ganaba al principio y pierde en sus posiciones más recientes")
    if p.late_longshot_wins >= 2:
        out.append(f"{p.late_longshot_wins} apuestas grandes a precio bajo, a menos de 48 h del cierre, que salieron bien "
                   "(patrón de información anticipada o de mucha suerte: miralo de cerca)")
    if p.total_cost and p.worst_loss < -0.1 * p.total_cost:
        out.append(f"su peor posición perdió {abs(p.worst_loss):,.0f} USD (más del 10 % de todo lo que invirtió)")
    return out


def rank(profiles: list[TraderProfile], min_positions: int = 20) -> list[TraderProfile]:
    """Ordena por consistencia (t) y marca si sobrevive la corrección por la cantidad de traders mirados.

    Si se miran N traders, el mejor t que daría el puro azar ronda Φ⁻¹(1 − 1/N): ese es el umbral
    "prometedor". El umbral "sólido" es Bonferroni al 5 %: Φ⁻¹(1 − 0,05/N).
    """
    nd = statistics.NormalDist()
    n = max(2, len(profiles))
    chance = nd.inv_cdf(1 - 1 / n)
    solid = nd.inv_cdf(1 - 0.05 / n)
    for p in profiles:
        p.score = p.t_stat if p.n >= min_positions else p.t_stat * p.n / min_positions
        if p.n < min_positions:
            p.significance = "muestra chica"
        elif p.t_stat >= solid:
            p.significance = "sólido"
        elif p.t_stat >= chance:
            p.significance = "prometedor"
        elif p.t_stat > 0:
            p.significance = "no se distingue de la suerte"
        else:
            p.significance = "negativo"
    return sorted(profiles, key=lambda p: p.score, reverse=True)


def thresholds(n_traders: int) -> dict[str, float]:
    nd = statistics.NormalDist()
    n = max(2, n_traders)
    return {"azar": nd.inv_cdf(1 - 1 / n), "solido": nd.inv_cdf(1 - 0.05 / n)}

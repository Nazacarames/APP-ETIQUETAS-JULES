"""Backtester vela a vela, sin mirar el futuro.

Reglas de ejecución:
- La señal se calcula con el CIERRE de la vela i.
- La orden se ejecuta en la APERTURA de la vela i+1 (con slippage y comisión).
- El stop se revisa dentro de cada vela: si abre por debajo del stop sale en
  la apertura (gap); si el mínimo toca el stop, sale en el stop.
- Long-only, una posición a la vez, sin apalancamiento.

Además, cada señal vetada por Jev se simula "en la sombra" para saber si el
veto ayudó o perjudicó. Es la métrica clave para decidir si Jev aporta.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any

from .config import CostConfig
from .data import Bar
from .features import Indicators, WARMUP, describe, snapshot
from .judge import JevJudge
from .questions import entry_review
from .risk import AccountState, RiskManager
from .strategy import DonchianTrend, EntrySignal

JEV_PRICE_PER_M_INPUT = 0.042  # USD por millón de tokens de entrada (output gratis), precio de lanzamiento


@dataclass
class Trade:
    entry_i: int
    exit_i: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    ret_pct: float
    exit_reason: str
    size_mult: float = 1.0


@dataclass
class BacktestResult:
    name: str
    equity: list[tuple[int, float]]
    trades: list[Trade] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    jev_calls: int = 0
    jev_est_tokens: int = 0


def buy_fill(price: float, c: CostConfig) -> float:
    return price * (1 + c.slippage_bps / 10_000)


def sell_fill(price: float, c: CostConfig) -> float:
    return price * (1 - c.slippage_bps / 10_000)


def fee(notional: float, c: CostConfig) -> float:
    return abs(notional) * c.fee_bps / 10_000


def shadow_trade(ind: Indicators, sig: EntrySignal, strategy: DonchianTrend, c: CostConfig) -> float | None:
    """Retorno % (neto de costos) que habría tenido una señal si se tomaba."""
    bars = ind.bars
    i = sig.i + 1
    if i >= len(bars) or bars[i].open <= sig.stop:
        return None
    entry = buy_fill(bars[i].open, c)
    exit_px = None
    pending_exit = False
    while i < len(bars):
        b = bars[i]
        if pending_exit:
            exit_px = sell_fill(b.open, c)
            break
        if b.open <= sig.stop:
            exit_px = sell_fill(b.open, c)
            break
        if b.low <= sig.stop:
            exit_px = sell_fill(sig.stop, c)
            break
        if strategy.exit(ind, i):
            pending_exit = True
        i += 1
    if exit_px is None:
        exit_px = sell_fill(bars[-1].close, c)
    return (exit_px * (1 - c.fee_bps / 10_000)) / (entry * (1 + c.fee_bps / 10_000)) - 1


def run_backtest(bars: list[Bar], *, name: str, strategy: DonchianTrend | None = None,
                 risk: RiskManager, costs: CostConfig, judge: JevJudge | None = None,
                 initial_equity: float = 10_000.0, bars_per_year: int = 365,
                 timeframe: str = "daily", asset: str | None = None) -> BacktestResult:
    strategy = strategy or DonchianTrend()
    ind = Indicators(bars)
    cash, qty = initial_equity, 0.0
    stop = 0.0
    entry_info: dict[str, Any] = {}
    pending_entry: tuple[EntrySignal, float] | None = None
    pending_exit: str | None = None
    acct = AccountState(initial_equity, initial_equity, initial_equity)
    res = BacktestResult(name, [])

    def close_position(i: int, px: float, reason: str) -> None:
        nonlocal cash, qty
        proceeds = qty * px
        f = fee(proceeds, costs)
        cash += proceeds - f
        e = entry_info
        pnl = (px - e["price"]) * qty - e["fee"] - f
        res.trades.append(Trade(e["i"], i, bars[e["i"]].date, bars[i].date, e["price"], px, qty,
                                pnl, pnl / (e["price"] * qty), reason, e["mult"]))
        qty = 0.0

    for i in range(WARMUP, len(bars)):
        b = bars[i]
        acct.day_start_equity = cash + qty * b.open

        # 1) Órdenes pendientes de la vela anterior, en la apertura.
        if pending_exit and qty > 0:
            close_position(i, sell_fill(b.open, costs), pending_exit)
            pending_exit = None
        if pending_entry and qty == 0:
            sig, mult = pending_entry
            pending_entry = None
            if b.open > sig.stop:
                px = buy_fill(b.open, costs)
                equity_now = cash
                q = risk.position_size(equity_now, px, sig.stop, mult)
                cost = q * px
                f = fee(cost, costs)
                if q > 0 and cost + f <= cash:
                    cash -= cost + f
                    qty, stop = q, sig.stop
                    entry_info = {"i": i, "price": px, "fee": f, "mult": mult}

        # 2) Stop dentro de la vela.
        if qty > 0:
            if b.open <= stop:
                close_position(i, sell_fill(b.open, costs), "stop (gap)")
            elif b.low <= stop:
                close_position(i, sell_fill(stop, costs), "stop")

        # 3) Marcar a mercado al cierre.
        equity = cash + qty * b.close
        res.equity.append((b.ts, equity))
        acct.equity = equity
        acct.peak_equity = max(acct.peak_equity, equity)
        acct.open_positions = 1 if qty > 0 else 0

        # 4) Señales con el cierre (se ejecutan en la vela siguiente).
        if i == len(bars) - 1:
            break
        if qty > 0:
            reason = strategy.exit(ind, i)
            if reason:
                pending_exit = reason
            continue
        sig = strategy.entry(ind, i)
        if not sig:
            continue
        decision: dict[str, Any] = {"i": i, "date": b.date, "signal": sig.reason}
        ok, why = risk.can_open(acct)
        if not ok:
            decision.update(action="bloqueado_por_riesgo", reasons=[why])
            res.decisions.append(decision)
            continue
        mult = 1.0
        if judge:
            snap = snapshot(ind, i)
            state = describe(snap, timeframe)
            verdict = judge.review_entry(state, asset)
            res.jev_calls += 1
            res.jev_est_tokens += len(json.dumps(state) + json.dumps(entry_review(asset))) // 4
            decision.update(state=state, **verdict.summary())
            if not verdict.allow:
                decision["action"] = "vetada"
                decision["shadow_ret"] = shadow_trade(ind, sig, strategy, costs)
                res.decisions.append(decision)
                continue
            mult = verdict.size_mult
            decision["shadow_ret"] = shadow_trade(ind, sig, strategy, costs)
        decision["action"] = "entrada"
        res.decisions.append(decision)
        pending_entry = (sig, mult)

    if qty > 0:
        close_position(len(bars) - 1, sell_fill(bars[-1].close, costs), "fin del backtest")
        res.equity[-1] = (bars[-1].ts, cash)

    res.metrics = compute_metrics(res.equity, res.trades, bars_per_year, initial=initial_equity)
    return res


def buy_and_hold(bars: list[Bar], costs: CostConfig, initial_equity: float = 10_000.0,
                 bars_per_year: int = 365) -> BacktestResult:
    start = WARMUP
    px = buy_fill(bars[start].open, costs)
    qty = initial_equity / (px * (1 + costs.fee_bps / 10_000))
    eq = [(b.ts, qty * b.close) for b in bars[start:]]
    exit_px = sell_fill(bars[-1].close, costs)
    eq[-1] = (bars[-1].ts, qty * exit_px * (1 - costs.fee_bps / 10_000))
    res = BacktestResult("Comprar y mantener", eq)
    res.metrics = compute_metrics(eq, [], bars_per_year, exposure_override=1.0, initial=initial_equity)
    return res


def compute_metrics(equity: list[tuple[int, float]], trades: list[Trade], bars_per_year: int,
                    exposure_override: float | None = None, initial: float | None = None) -> dict[str, float]:
    """initial: capital antes de la primera vela (incluye el costo de entrada de comprar-y-mantener)."""
    vals = [v for _, v in equity]
    if initial is not None:
        vals = [initial] + vals
    if len(vals) < 2:
        return {}
    rets = [vals[k] / vals[k - 1] - 1 for k in range(1, len(vals))]
    years = len(vals) / bars_per_year
    total = vals[-1] / vals[0] - 1
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    sd = pstdev(rets)
    downside = [r for r in rets if r < 0]
    dsd = math.sqrt(sum(r * r for r in downside) / len(rets)) if downside else 0.0
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    in_pos = sum(t.exit_i - t.entry_i + 1 for t in trades)
    return {
        "total_return": total,
        "cagr": (vals[-1] / vals[0]) ** (1 / years) - 1 if years > 0 and vals[-1] > 0 else -1.0,
        "max_drawdown": mdd,
        "sharpe": mean(rets) / sd * math.sqrt(bars_per_year) if sd > 0 else 0.0,
        "sortino": mean(rets) / dsd * math.sqrt(bars_per_year) if dsd > 0 else 0.0,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf") if wins else 0.0,
        "avg_trade_pct": mean(t.ret_pct for t in trades) if trades else 0.0,
        "exposure": exposure_override if exposure_override is not None else min(1.0, in_pos / len(vals)),
        "final_equity": vals[-1],
    }


def segment(res: BacktestResult, start_ts: int, end_ts: int | None, bars_per_year: int,
            ts_of: dict[int, int]) -> dict[str, float]:
    """Métricas de un tramo (p. ej. holdout) usando la curva y los trades de ese tramo."""
    eq = [(t, v) for t, v in res.equity if t >= start_ts and (end_ts is None or t < end_ts)]
    trades = [t for t in res.trades if ts_of[t.entry_i] >= start_ts and (end_ts is None or ts_of[t.entry_i] < end_ts)]
    exposure = None if res.trades or res.name != "Comprar y mantener" else 1.0
    return compute_metrics(eq, trades, bars_per_year, exposure_override=exposure)


def veto_analysis(res: BacktestResult) -> dict[str, float]:
    """¿Las señales que Jev vetó eran peores que las que dejó pasar?"""
    taken = [d["shadow_ret"] for d in res.decisions if d.get("action") == "entrada" and d.get("shadow_ret") is not None]
    vetoed = [d["shadow_ret"] for d in res.decisions if d.get("action") == "vetada" and d.get("shadow_ret") is not None]
    return {
        "signals": len(taken) + len(vetoed),
        "taken": len(taken),
        "vetoed": len(vetoed),
        "taken_avg_ret": mean(taken) if taken else 0.0,
        "vetoed_avg_ret": mean(vetoed) if vetoed else 0.0,
        "taken_win_rate": sum(r > 0 for r in taken) / len(taken) if taken else 0.0,
        "vetoed_win_rate": sum(r > 0 for r in vetoed) / len(vetoed) if vetoed else 0.0,
    }

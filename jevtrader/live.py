"""Loop de trading en papel sobre datos reales (Binance, sin API key).

Pensado para correrse una vez por vela cerrada (cron, systemd timer, GitHub
Actions o una rutina programada):

    python -m jevtrader paper --symbol BTCUSDT --interval 1d --once

Cada corrida es idempotente: si la última vela ya fue procesada, no hace nada.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .broker import PaperBroker
from .config import Settings
from .data import INTERVAL_MS, fetch_binance
from .features import Indicators, describe, snapshot
from .journal import Journal
from .judge import JevJudge
from .risk import AccountState, RiskManager
from .strategy import DonchianTrend


def step(symbol: str, interval: str, settings: Settings, broker: PaperBroker, judge: JevJudge,
         journal: Journal, strategy: DonchianTrend | None = None, bars=None) -> dict:
    strategy = strategy or DonchianTrend()
    risk = RiskManager(settings.risk)
    bars = bars if bars is not None else fetch_binance(symbol, interval, limit=400)
    ind = Indicators(bars)
    i = len(bars) - 1
    b = bars[i]

    if broker.state["last_bar_ts"].get(symbol) == b.ts:
        return {"event": "sin_cambios", "bar": b.date}
    out: dict = {"bar": b.date, "close": b.close}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if broker.state.get("day") != today:  # el límite de pérdida diaria se mide desde acá
        broker.mark("day", today)
        broker.mark("day_start_equity", broker.equity({symbol: b.close}))

    pos = broker.position(symbol)
    if pos:
        if b.low <= pos["stop"]:
            px = b.open if b.open <= pos["stop"] else pos["stop"]  # gap: sale en la apertura
            fill = broker.sell(symbol, px, "stop")
            out = journal.log("salida", symbol=symbol, **out, fill=fill.__dict__)
        elif reason := strategy.exit(ind, i):
            fill = broker.sell(symbol, b.close, reason)
            out = journal.log("salida", symbol=symbol, **out, fill=fill.__dict__)
        else:
            out = journal.log("mantener", symbol=symbol, **out, stop=pos["stop"])
    else:
        sig = strategy.entry(ind, i)
        if not sig:
            out = journal.log("sin_senal", symbol=symbol, **out)
        else:
            equity = broker.equity({symbol: b.close})
            peak = max(broker.state.get("peak_equity", equity), equity)
            acct = AccountState(equity, peak, broker.state.get("day_start_equity", equity),
                                open_positions=len(broker.state["positions"]), halted=broker.state.get("halted", False))
            ok, why = risk.can_open(acct)
            if not ok:
                broker.mark("halted", acct.halted)
                out = journal.log("bloqueado_por_riesgo", symbol=symbol, **out, reason=why)
            else:
                state = describe(snapshot(ind, i), "daily" if interval == "1d" else interval)
                verdict = judge.review_entry(state, asset=symbol)
                if not verdict.allow:
                    out = journal.log("vetada", symbol=symbol, **out, signal=sig.reason, state=state, **verdict.summary())
                else:
                    qty = risk.position_size(equity, b.close, sig.stop, verdict.size_mult)
                    fill = broker.buy(symbol, qty, b.close, sig.stop, sig.reason)
                    out = journal.log("entrada", symbol=symbol, **out, signal=sig.reason, state=state,
                                      fill=fill.__dict__, **verdict.summary())

    equity = broker.equity({symbol: b.close})
    broker.mark("peak_equity", max(broker.state.get("peak_equity", equity), equity))
    broker.state["last_bar_ts"][symbol] = b.ts
    broker.mark("last_bar_ts", broker.state["last_bar_ts"])
    out["equity"] = round(equity, 2)
    return out


def run_forever(symbol: str, interval: str, settings: Settings, broker: PaperBroker, judge: JevJudge,
                journal: Journal) -> None:
    step_ms = INTERVAL_MS[interval]
    while True:
        try:
            print(step(symbol, interval, settings, broker, judge, journal))
        except Exception as exc:  # el loop no se cae por un error de red; queda en el diario
            journal.log("error", symbol=symbol, error=repr(exc))
            print("error:", exc)
        now = int(time.time() * 1000)
        wait = (step_ms - now % step_ms) / 1000 + 5  # 5 s después del cierre de la próxima vela
        print(f"próxima revisión: {datetime.fromtimestamp(time.time() + wait, tz=timezone.utc):%Y-%m-%d %H:%M} UTC")
        time.sleep(wait)

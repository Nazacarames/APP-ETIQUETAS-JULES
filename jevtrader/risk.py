"""Gestión de riesgo. Determinística, sin IA, y con la última palabra.

Nada de lo que diga Jev (o Claude) puede saltarse estas reglas.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import RiskConfig


@dataclass
class AccountState:
    equity: float
    peak_equity: float
    day_start_equity: float
    open_positions: int = 0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg

    def position_size(self, equity: float, entry: float, stop: float, size_mult: float = 1.0) -> float:
        """Cantidad tal que, si salta el stop, se pierde risk_per_trade * equity * size_mult."""
        per_unit = entry - stop
        if per_unit <= 0 or entry <= 0 or size_mult <= 0:
            return 0.0
        qty = equity * self.cfg.risk_per_trade * size_mult / per_unit
        cap = equity * self.cfg.max_position_pct / entry
        return max(0.0, min(qty, cap))

    def check_kill_switches(self, acct: AccountState) -> AccountState:
        if acct.peak_equity > 0 and acct.equity <= acct.peak_equity * (1 - self.cfg.max_drawdown_pct):
            acct.halted = True
            acct.halt_reason = f"drawdown > {self.cfg.max_drawdown_pct:.0%}: bot apagado"
        return acct

    def can_open(self, acct: AccountState) -> tuple[bool, str]:
        self.check_kill_switches(acct)
        if acct.halted:
            return False, acct.halt_reason
        if acct.day_start_equity > 0 and acct.equity <= acct.day_start_equity * (1 - self.cfg.max_daily_loss_pct):
            return False, f"pérdida diaria > {self.cfg.max_daily_loss_pct:.0%}"
        if acct.open_positions >= self.cfg.max_open_positions:
            return False, "máximo de posiciones abiertas"
        return True, "ok"

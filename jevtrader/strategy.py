"""Estrategia base 100 % determinística (la que genera los candidatos).

Seguimiento de tendencia tipo Donchian / "tortugas":
- Entrada larga: cierre por encima del máximo de las 20 velas previas y
  precio sobre la media de 200 (solo a favor de la tendencia mayor).
- Stop inicial: entrada - 2 x ATR.
- Salida: cierre por debajo del mínimo de las 10 velas previas (trailing).

Es deliberadamente simple: la idea es medir si Jev, como filtro, mejora o
empeora una regla conocida. Claude Code puede proponer otras estrategias que
implementen la misma interfaz.
"""
from __future__ import annotations

from dataclasses import dataclass

from .data import Bar
from .features import Indicators, WARMUP, prior_high, prior_low


@dataclass(frozen=True)
class EntrySignal:
    i: int
    ref_price: float   # cierre de la vela de señal (la orden se ejecuta en la apertura siguiente)
    stop: float
    reason: str


class DonchianTrend:
    name = "donchian_20_10"

    def __init__(self, entry_lookback: int = 20, exit_lookback: int = 10, stop_atr: float = 2.0):
        self.entry_lookback = entry_lookback
        self.exit_lookback = exit_lookback
        self.stop_atr = stop_atr

    def entry(self, ind: Indicators, i: int) -> EntrySignal | None:
        if i < WARMUP:
            return None
        bars: list[Bar] = ind.bars
        c = bars[i].close
        if c <= prior_high(bars, i, self.entry_lookback):
            return None
        if ind.sma200[i] is None or c <= ind.sma200[i]:
            return None
        atr = ind.atr14[i]
        return EntrySignal(i, c, c - self.stop_atr * atr, f"cierre > máximo de {self.entry_lookback} y > SMA200")

    def exit(self, ind: Indicators, i: int) -> str | None:
        if ind.bars[i].close < prior_low(ind.bars, i, self.exit_lookback):
            return f"cierre < mínimo de {self.exit_lookback}"
        return None

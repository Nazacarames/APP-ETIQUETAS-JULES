"""Indicadores (en código) y traducción a un "state" semántico para Jev.

Regla de oro, sacada de la documentación de TypeSafe: Jev NO es una
calculadora. Cuenta mal, compara números mal y lee fechas como texto. Por eso:

1. Toda la aritmética (medias, ATR, RSI, rupturas) se hace acá, en código.
2. A Jev le llega una descripción en palabras, ya "masticada" en categorías.
3. El state es anónimo: sin ticker, sin fecha y sin niveles de precio. Así el
   modelo no puede "recordar" qué pasó después con ese activo (sesgo de
   memorización en los backtests).

Todas las series son causales: el valor en el índice i solo usa velas <= i.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .data import Bar

WARMUP = 210  # velas necesarias antes de poder describir el mercado


# ---------------------------------------------------------------- series ----

def sma_series(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= n:
            acc -= values[i - n]
        if i >= n - 1:
            out[i] = acc / n
    return out


def true_range(bars: list[Bar]) -> list[float]:
    tr = []
    for i, b in enumerate(bars):
        if i == 0:
            tr.append(b.high - b.low)
        else:
            pc = bars[i - 1].close
            tr.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
    return tr


def atr_series(bars: list[Bar], n: int = 14) -> list[float | None]:
    """ATR de Wilder."""
    tr = true_range(bars)
    out: list[float | None] = [None] * len(bars)
    if len(bars) < n:
        return out
    prev = sum(tr[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(bars)):
        prev = (prev * (n - 1) + tr[i]) / n
        out[i] = prev
    return out


def rsi_series(closes: list[float], n: int = 14) -> list[float | None]:
    """RSI de Wilder."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / n, losses / n
    out[n] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0.0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def efficiency_ratio_series(closes: list[float], n: int = 20) -> list[float | None]:
    """Kaufman: desplazamiento neto / camino recorrido. 1 = línea recta, 0 = serrucho."""
    out: list[float | None] = [None] * len(closes)
    for i in range(n, len(closes)):
        path = sum(abs(closes[k] - closes[k - 1]) for k in range(i - n + 1, i + 1))
        out[i] = abs(closes[i] - closes[i - n]) / path if path > 0 else 0.0
    return out


def prior_high(bars: list[Bar], i: int, n: int) -> float:
    """Máximo de las n velas ANTERIORES a i (sin incluir i)."""
    return max(b.high for b in bars[max(0, i - n):i])


def prior_low(bars: list[Bar], i: int, n: int) -> float:
    return min(b.low for b in bars[max(0, i - n):i])


class Indicators:
    """Calcula todas las series una sola vez para una lista de velas."""

    def __init__(self, bars: list[Bar]):
        self.bars = bars
        closes = [b.close for b in bars]
        self.closes = closes
        self.sma20 = sma_series(closes, 20)
        self.sma50 = sma_series(closes, 50)
        self.sma200 = sma_series(closes, 200)
        self.atr14 = atr_series(bars, 14)
        self.rsi14 = rsi_series(closes, 14)
        self.er20 = efficiency_ratio_series(closes, 20)
        self.atr_pct = [a / c if a is not None and c else None for a, c in zip(self.atr14, closes)]

    def __len__(self) -> int:
        return len(self.bars)


# -------------------------------------------------------------- snapshot ----

@dataclass(frozen=True)
class Snapshot:
    """Números del mercado en la vela i (todo calculado en código)."""
    i: int
    close: float
    atr: float
    dist50_atr: float      # (close - SMA50) / ATR
    dist200_atr: float     # (close - SMA200) / ATR
    slope50_atr: float     # cambio de la SMA50 en 10 velas / ATR
    er20: float            # efficiency ratio 20
    rsi14: float
    vol_ratio: float       # ATR% actual / mediana de ATR% de 100 velas
    volume_pct: float      # percentil del volumen actual en 50 velas
    close_loc: float       # 0 = cerró en el mínimo, 1 = en el máximo
    breakout_atr: float    # (close - máximo previo de 20) / ATR
    up_closes_5: int       # cierres alcistas en las últimas 5 velas
    run20_atr: float       # (close - close de hace 20) / ATR


def snapshot(ind: Indicators, i: int) -> Snapshot | None:
    if i < WARMUP or i >= len(ind):
        return None
    bars = ind.bars
    b = bars[i]
    atr = ind.atr14[i]
    if not atr:
        return None
    past_atr_pct = [x for x in ind.atr_pct[i - 99:i + 1] if x is not None]
    vols = [x.volume for x in bars[i - 49:i + 1]]
    rng = b.high - b.low
    return Snapshot(
        i=i,
        close=b.close,
        atr=atr,
        dist50_atr=(b.close - ind.sma50[i]) / atr,
        dist200_atr=(b.close - ind.sma200[i]) / atr,
        slope50_atr=(ind.sma50[i] - ind.sma50[i - 10]) / atr,
        er20=ind.er20[i],
        rsi14=ind.rsi14[i],
        vol_ratio=ind.atr_pct[i] / median(past_atr_pct),
        volume_pct=sum(1 for v in vols if v < b.volume) / len(vols),
        close_loc=(b.close - b.low) / rng if rng > 0 else 0.5,
        breakout_atr=(b.close - prior_high(bars, i, 20)) / atr,
        up_closes_5=sum(1 for k in range(i - 4, i + 1) if bars[k].close > bars[k - 1].close),
        run20_atr=(b.close - bars[i - 20].close) / atr,
    )


# ------------------------------------------------- categorías y frases ----

def _band(x: float, cuts: list[tuple[float, str]], last: str) -> str:
    for threshold, label in cuts:
        if x > threshold:
            return label
    return last


def buckets(s: Snapshot) -> dict[str, str]:
    """Pasa números a categorías discretas (decisión de código, no de Jev)."""
    if s.breakout_atr >= 0.5:
        breakout = "clear"
    elif s.breakout_atr >= 0:
        breakout = "marginal"
    else:
        breakout = "none"
    if s.close_loc >= 0.75:
        last_bar = "near_high"
    elif s.close_loc <= 0.25:
        last_bar = "near_low"
    else:
        last_bar = "mid"
    return {
        "long_term_trend": _band(s.dist200_atr, [(4, "far_above"), (1, "above"), (-1, "near"), (-4, "below")], "far_below"),
        "medium_term_trend": _band(s.dist50_atr, [(3, "far_above"), (1, "above"), (-1, "near"), (-3, "below")], "far_below"),
        "trend_slope": _band(s.slope50_atr, [(1.5, "rising_fast"), (0.4, "rising"), (-0.4, "flat"), (-1.5, "falling")], "falling_fast"),
        "directionality": _band(s.er20, [(0.45, "steady"), (0.25, "moderate"), (0.12, "mixed")], "choppy"),
        "momentum": _band(s.rsi14, [(75, "overbought"), (60, "strong"), (40, "neutral"), (25, "weak")], "oversold"),
        "volatility": _band(s.vol_ratio, [(1.6, "very_high"), (1.15, "high"), (0.85, "normal")], "low"),
        "participation": _band(s.volume_pct, [(0.89, "extreme"), (0.64, "above_avg"), (0.34, "average")], "below_avg"),
        "last_bar": last_bar,
        "breakout": breakout,
        "recent_bars": f"up_{s.up_closes_5}",
        "run_up": _band(s.run20_atr, [(8, "sharp_rise"), (3, "rise"), (-3, "flat"), (-8, "fall")], "sharp_fall"),
    }


_NUM_WORDS = ["None", "One", "Two", "Three", "Four", "All five"]

PHRASES: dict[str, dict[str, str]] = {
    "long_term_trend": {
        "far_above": "Price is far above its long-term (200-bar) average.",
        "above": "Price is above its long-term (200-bar) average.",
        "near": "Price is close to its long-term (200-bar) average.",
        "below": "Price is below its long-term (200-bar) average.",
        "far_below": "Price is far below its long-term (200-bar) average.",
    },
    "medium_term_trend": {
        "far_above": "Price is far above its 50-bar average.",
        "above": "Price is above its 50-bar average.",
        "near": "Price is close to its 50-bar average.",
        "below": "Price is below its 50-bar average.",
        "far_below": "Price is far below its 50-bar average.",
    },
    "trend_slope": {
        "rising_fast": "The 50-bar average is rising steeply.",
        "rising": "The 50-bar average is rising.",
        "flat": "The 50-bar average is flat.",
        "falling": "The 50-bar average is falling.",
        "falling_fast": "The 50-bar average is falling steeply.",
    },
    "directionality": {
        "steady": "Over the last 20 bars price moved steadily in one direction with little back-and-forth.",
        "moderate": "Over the last 20 bars price moved in one direction with some back-and-forth.",
        "mixed": "Over the last 20 bars price action was mixed, with a lot of back-and-forth.",
        "choppy": "Over the last 20 bars price went nowhere, chopping back and forth.",
    },
    "momentum": {
        "overbought": "Momentum is extremely strong and the move looks stretched (overbought).",
        "strong": "Momentum is strong.",
        "neutral": "Momentum is neutral.",
        "weak": "Momentum is weak.",
        "oversold": "Momentum is extremely weak (oversold).",
    },
    "volatility": {
        "very_high": "Volatility is much higher than usual.",
        "high": "Volatility is somewhat higher than usual.",
        "normal": "Volatility is normal.",
        "low": "Volatility is lower than usual (quiet market).",
    },
    "participation": {
        "extreme": "Volume on the latest bar is among the highest of the last 50 bars.",
        "above_avg": "Volume on the latest bar is above average.",
        "average": "Volume on the latest bar is about average.",
        "below_avg": "Volume on the latest bar is below average.",
    },
    "last_bar": {
        "near_high": "The latest bar closed near its high.",
        "mid": "The latest bar closed in the middle of its range.",
        "near_low": "The latest bar closed near its low.",
    },
    "breakout": {
        "clear": "Price closed clearly above the highest high of the previous 20 bars.",
        "marginal": "Price closed just barely above the highest high of the previous 20 bars.",
        "none": "Price is below the highest high of the previous 20 bars.",
    },
    "recent_bars": {
        f"up_{n}": f"{_NUM_WORDS[n]} of the last 5 bars closed higher than the bar before." for n in range(6)
    },
    "run_up": {
        "sharp_rise": "Price has risen sharply over the last 20 bars.",
        "rise": "Price has risen over the last 20 bars.",
        "flat": "Price is roughly unchanged over the last 20 bars.",
        "fall": "Price has fallen over the last 20 bars.",
        "sharp_fall": "Price has fallen sharply over the last 20 bars.",
    },
}

# Inversa frase -> (clave, etiqueta). La usa MockJev para "leer" el state.
PHRASE_INDEX: dict[str, tuple[str, str]] = {
    sentence: (key, label) for key, labels in PHRASES.items() for label, sentence in labels.items()
}


def describe(s: Snapshot, timeframe: str = "daily") -> dict[str, str]:
    """State para Jev: objeto JSON con frases en inglés (Jev rinde mejor en inglés)."""
    state = {"context": f"Market summary for an anonymised asset on {timeframe} bars, as of the latest closed bar."}
    for key, label in buckets(s).items():
        state[key] = PHRASES[key][label]
    return state

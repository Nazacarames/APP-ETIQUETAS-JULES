"""Preguntas tipadas que se le hacen a Jev.

Criterios de diseño (de la documentación de TypeSafe y de los backtests públicos):
- Preguntas atómicas: cada una mide UNA propiedad. El código combina.
- Nada de aritmética ni fechas: eso ya viene resuelto en el state.
- NO preguntamos "¿va a subir el precio?". Backtests independientes
  (egrm07/jev_bitcoin_backtest, TradeRank) no encontraron ventaja en eso.
  Jev se usa como juez/filtro de un setup que ya generó el código.
- Sesgo de orden: Jev tiende a elegir la primera opción de un choice. Por eso
  la opción más conservadora va primero: si el modelo duda, el sesgo juega a
  favor de NO operar.
- En inglés: el modelo rinde mejor en inglés.
"""
from __future__ import annotations

from .jev_client import choice, noul, score

REGIME = choice(
    "Which description best fits the market behaviour described in the state?",
    {
        "disorderly": "Erratic, whipsawing or panicky price action with no reliable direction",
        "range_bound": "Sideways movement inside a range where breakouts tend to fail",
        "trending_down": "A persistent downtrend",
        "trending_up": "A persistent and orderly uptrend",
    },
)

SETUP_QUALITY = score(
    "The state describes an upside breakout. How strong is the evidence that it will follow through rather than fail?",
    [
        "Weak: looks like a false breakout or an exhaustion move",
        "Mixed: some confirmation but clear warning signs",
        "Strong: confirmation from trend, participation and price action",
    ],
)

OVEREXTENDED = noul(
    "Price looks stretched after a sharp run, so a pullback before further gains is likely",
)


def news_risk(asset: str) -> dict:
    return noul({
        "question": "The headlines contain material negative information for the asset "
                    "(fraud, hack, regulatory action, lawsuit, guidance cut, delisting, default)",
        "asset": asset,
    })


def entry_review(asset: str | None = None, with_news: bool = False) -> dict:
    """Preguntas para revisar una entrada candidata. Todas van en UNA llamada (en paralelo)."""
    q = {"regime": REGIME, "setup_quality": SETUP_QUALITY, "overextended": OVEREXTENDED}
    if with_news:
        q["news_risk"] = news_risk(asset or "the asset")
    return q


def headline_triage(asset: str) -> dict:
    """Clasificación de un titular para un activo concreto (uso más sólido de Jev en trading)."""
    return {
        "about_asset": noul({"question": "The headline is mainly about this asset", "asset": asset}),
        "material": noul("The headline could plausibly move the price of the asset by itself"),
        "sentiment": choice(
            {"question": "What is the likely price impact of the headline for this asset?", "asset": asset},
            {
                "neutral": "No clear impact or mixed",
                "negative": "Bad news for holders of the asset",
                "positive": "Good news for holders of the asset",
            },
        ),
        "event": choice(
            "What type of event does the headline report?",
            {
                "other": "None of the categories below",
                "earnings": "Quarterly results or earnings figures",
                "guidance": "Change in forecasts or outlook",
                "deal": "Merger, acquisition, partnership or major contract",
                "regulatory_legal": "Regulation, lawsuit, investigation or fine",
                "security": "Hack, exploit, outage or data breach",
                "macro": "Interest rates, inflation, economy-wide or geopolitical news",
                "product": "Product launch, approval or recall",
                "management": "Executive change, layoffs or insider activity",
            },
        ),
    }

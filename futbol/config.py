"""Configuración del analista. Todo sale de variables de entorno o del archivo de claves local (ver .env.example)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from polylens.config import JevConfig, _env, load_settings

LPF = 128          # Liga Profesional Argentina en API-Football
COPA_LIGA = 1032   # Copa de la Liga Profesional (2023 y 2024)
# El plan gratis solo da 2022-2024; con un plan pago se cambia a "128:2026" (o se suma).
DEFAULT_COMPETITIONS = ((COPA_LIGA, 2024), (LPF, 2024))


def parse_competitions(text: str | None) -> tuple[tuple[int, int], ...]:
    """'1032:2024,128:2024' -> ((1032, 2024), (128, 2024)), en orden cronológico."""
    if not text:
        return DEFAULT_COMPETITIONS
    out = []
    for part in str(text).split(","):
        league, _, season = part.strip().partition(":")
        out.append((int(league), int(season)))
    return tuple(out)


@dataclass(frozen=True)
class FutbolConfig:
    api_key: str | None = None
    base_url: str = "https://v3.football.api-sports.io"
    competitions: tuple = DEFAULT_COMPETITIONS
    bookmaker: str = "Bet365"
    min_interval_s: float = 6.5    # el plan gratis permite ~10 pedidos por minuto
    bankroll: float = 100.0        # presupuesto del usuario: toda simulación arranca con 100 USD
    max_stake_pct: float = 0.03    # nunca más del 3 % del capital en una apuesta
    min_edge: float = 0.05         # apostar solo si el modelo ve al menos 5 % de valor
    data_dir: Path = Path("data") / "futbol"
    jev: JevConfig = field(default_factory=JevConfig)


def load_config(dotenv: str | Path = ".env") -> FutbolConfig:
    s = load_settings(dotenv)
    return FutbolConfig(
        api_key=_env("APIFOOTBALL_KEY", None),
        base_url=_env("APIFOOTBALL_URL", FutbolConfig.base_url),
        competitions=parse_competitions(_env("FUTBOL_COMPETENCIAS", None)),
        bookmaker=_env("FUTBOL_CASA", FutbolConfig.bookmaker),
        min_interval_s=_env("APIFOOTBALL_MIN_INTERVAL_S", FutbolConfig.min_interval_s, float),
        bankroll=_env("FUTBOL_CAPITAL", FutbolConfig.bankroll, float),
        max_stake_pct=_env("FUTBOL_MAX_APUESTA", FutbolConfig.max_stake_pct, float),
        min_edge=_env("FUTBOL_MIN_VALOR", FutbolConfig.min_edge, float),
        data_dir=s.data_dir / "futbol",
        jev=s.jev,
    )

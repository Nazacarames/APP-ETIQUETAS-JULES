"""Configuración del analista. Todo sale de variables de entorno o del archivo de claves local (ver .env.example)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from polylens.config import JevConfig, _env, load_settings

LPF = 128  # Liga Profesional Argentina en API-Football


@dataclass(frozen=True)
class FutbolConfig:
    api_key: str | None = None
    base_url: str = "https://v3.football.api-sports.io"
    league: int = LPF
    season: int = 2026
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
        league=_env("FUTBOL_LIGA", LPF, int),
        season=_env("FUTBOL_TEMPORADA", FutbolConfig.season, int),
        bookmaker=_env("FUTBOL_CASA", FutbolConfig.bookmaker),
        min_interval_s=_env("APIFOOTBALL_MIN_INTERVAL_S", FutbolConfig.min_interval_s, float),
        bankroll=_env("FUTBOL_CAPITAL", FutbolConfig.bankroll, float),
        max_stake_pct=_env("FUTBOL_MAX_APUESTA", FutbolConfig.max_stake_pct, float),
        min_edge=_env("FUTBOL_MIN_VALOR", FutbolConfig.min_edge, float),
        data_dir=s.data_dir / "futbol",
        jev=s.jev,
    )

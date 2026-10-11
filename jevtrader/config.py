"""Configuración central.

Todo se puede sobreescribir con variables de entorno (o un archivo .env).
Los valores por defecto son conservadores a propósito: modo papel, riesgo 1 %
por operación y, si Jev falla, no se abre nada ("fail closed").
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Carga un .env simple (CLAVE=valor) sin pisar variables ya definidas."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in ('"', "'") and value[0] in value[1:]:
            value = value[1:value.index(value[0], 1)]  # entre comillas: se respeta tal cual
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # comentario al final de la línea
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default, cast=str):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    if cast is bool:
        return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
    return cast(value)


@dataclass(frozen=True)
class JevConfig:
    api_key: str | None = None
    base_url: str = "https://api.typesafe.ai/v1/systemone"
    model: str = "jev-latest"
    timeout_s: float = 3.0
    max_retries: int = 2
    # Jev puede devolver distribuciones distintas para el mismo request.
    # samples > 1 promedia N respuestas (self-consistency) a cambio de N llamadas.
    samples: int = 1
    force_mock: bool = False

    @property
    def use_mock(self) -> bool:
        return self.force_mock or not self.api_key


@dataclass(frozen=True)
class GateConfig:
    """Umbrales con los que el CÓDIGO decide qué hacer con las respuestas de Jev."""
    min_regime_conf: float = 0.40   # confianza mínima de que el régimen es "trending_up"
    min_setup_score: float = 1.0    # esperanza mínima en la escala 0..2 de calidad del setup
    full_size_conf: float = 0.70    # por encima: tamaño completo; por debajo: medio tamaño
    max_overextended: float = 0.70  # noul >= esto => medio tamaño
    max_news_risk: float = 0.60     # noul >= esto => veto
    fail_closed: bool = True        # si Jev no responde: no abrir posiciones
    shadow: bool = False            # True: Jev solo opina (se registra); la estrategia opera igual


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade: float = 0.01      # 1 % del capital entre entrada y stop
    max_position_pct: float = 0.50    # nunca más del 50 % del capital en una posición
    max_open_positions: int = 3
    max_daily_loss_pct: float = 0.03  # corta el día si se pierde 3 %
    max_drawdown_pct: float = 0.25    # apaga el bot si cae 25 % desde el máximo


@dataclass(frozen=True)
class CostConfig:
    fee_bps: float = 10.0       # comisión por lado (0,10 %)
    slippage_bps: float = 5.0   # deslizamiento por lado (0,05 %)


@dataclass(frozen=True)
class Settings:
    jev: JevConfig = field(default_factory=JevConfig)
    gate: GateConfig = field(default_factory=GateConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    data_dir: Path = Path("data")
    live_trading: bool = False


def load_settings(dotenv: str | Path = ".env") -> Settings:
    load_dotenv(dotenv)
    jev = JevConfig(
        api_key=_env("TYPESAFE_API_KEY", None),
        base_url=_env("JEV_BASE_URL", JevConfig.base_url),
        model=_env("JEV_MODEL", JevConfig.model),
        timeout_s=_env("JEV_TIMEOUT_S", JevConfig.timeout_s, float),
        max_retries=_env("JEV_MAX_RETRIES", JevConfig.max_retries, int),
        samples=_env("JEV_SAMPLES", JevConfig.samples, int),
        force_mock=_env("JEV_MOCK", False, bool),
    )
    gate = GateConfig(
        min_regime_conf=_env("GATE_MIN_REGIME_CONF", GateConfig.min_regime_conf, float),
        min_setup_score=_env("GATE_MIN_SETUP_SCORE", GateConfig.min_setup_score, float),
        full_size_conf=_env("GATE_FULL_SIZE_CONF", GateConfig.full_size_conf, float),
        max_overextended=_env("GATE_MAX_OVEREXTENDED", GateConfig.max_overextended, float),
        max_news_risk=_env("GATE_MAX_NEWS_RISK", GateConfig.max_news_risk, float),
        fail_closed=_env("GATE_FAIL_CLOSED", True, bool),
        shadow=_env("GATE_SHADOW", False, bool),
    )
    risk = RiskConfig(
        risk_per_trade=_env("RISK_PER_TRADE", RiskConfig.risk_per_trade, float),
        max_position_pct=_env("RISK_MAX_POSITION_PCT", RiskConfig.max_position_pct, float),
        max_open_positions=_env("RISK_MAX_OPEN_POSITIONS", RiskConfig.max_open_positions, int),
        max_daily_loss_pct=_env("RISK_MAX_DAILY_LOSS_PCT", RiskConfig.max_daily_loss_pct, float),
        max_drawdown_pct=_env("RISK_MAX_DRAWDOWN_PCT", RiskConfig.max_drawdown_pct, float),
    )
    costs = CostConfig(
        fee_bps=_env("COST_FEE_BPS", CostConfig.fee_bps, float),
        slippage_bps=_env("COST_SLIPPAGE_BPS", CostConfig.slippage_bps, float),
    )
    return Settings(
        jev=jev,
        gate=gate,
        risk=risk,
        costs=costs,
        data_dir=Path(_env("DATA_DIR", "data")),
        live_trading=_env("LIVE_TRADING", False, bool),
    )

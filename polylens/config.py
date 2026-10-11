"""Configuración. Todo se puede sobreescribir con variables de entorno (o un archivo .env).

Polylens solo ANALIZA datos públicos de Polymarket: no opera, no firma órdenes y no usa
billeteras. Las únicas claves posibles son la de Jev (opcional).
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
    timeout_s: float = 10.0
    max_retries: int = 3
    samples: int = 1
    force_mock: bool = False

    @property
    def use_mock(self) -> bool:
        return self.force_mock or not self.api_key


@dataclass(frozen=True)
class Settings:
    jev: JevConfig = field(default_factory=JevConfig)
    data_dir: Path = Path("data")
    cache_ttl_s: float = 6 * 3600     # cuánto vive una respuesta en la caché de disco
    min_interval_s: float = 0.25      # ritmo máximo hacia Polymarket (~4 pedidos por segundo)


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
    return Settings(
        jev=jev,
        data_dir=Path(_env("DATA_DIR", "data")),
        cache_ttl_s=_env("CACHE_TTL_S", Settings.cache_ttl_s, float),
        min_interval_s=_env("POLY_MIN_INTERVAL_S", Settings.min_interval_s, float),
    )

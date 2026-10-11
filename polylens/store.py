"""Resultados guardados en data/<tipo>/: uno con fecha por corrida y `latest.json` con el último.

Comparar escaneos de distintas fechas es la mejor prueba de si una racha era habilidad o suerte.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

KINDS = ("scans", "flows", "studies", "news")


def save(kind: str, result: dict, data_dir: str | Path, label: str = "") -> Path:
    d = Path(data_dir) / kind
    d.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S") + (f"-{label}" if label else "")
    path = d / f"{name}.json"
    text = json.dumps(result, ensure_ascii=False, indent=1)
    path.write_text(text)
    (d / "latest.json").write_text(text)
    return path


def load(kind: str, ref: str | Path = "latest", data_dir: str | Path = "data") -> dict | None:
    """`ref` es 'latest', un nombre de archivo dentro de data/<tipo>/ o una ruta. None si no existe."""
    p = Path(ref)
    if not p.exists():
        p = Path(data_dir) / kind / (str(ref) if str(ref).endswith(".json") else f"{ref}.json")
    if not p.exists():
        return None
    return json.loads(p.read_text())

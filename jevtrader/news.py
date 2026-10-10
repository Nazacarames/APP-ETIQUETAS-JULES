"""Triage de noticias con Jev: el caso de uso donde el modelo tiene más sentido.

Para cada titular pregunta (en una sola llamada, en paralelo):
    ¿es sobre este activo? ¿es material? ¿impacto positivo/negativo? ¿qué tipo de evento?

Uso:
    python -m jevtrader news --asset "Bitcoin (BTC)" --rss https://www.coindesk.com/arc/outboundfeeds/rss/
    python -m jevtrader news --asset "Apple Inc. (AAPL)" --file titulares.txt
"""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from .jev_client import JevError
from .questions import headline_triage


def fetch_rss(url: str, limit: int = 20) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "jev-trader/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        root = ET.fromstring(resp.read())
    titles = [t.text.strip() for item in root.iter("item") if (t := item.find("title")) is not None and t.text]
    return titles[:limit]


def triage(client, asset: str, headlines: list[str], workers: int = 8) -> list[dict]:
    questions = headline_triage(asset)

    def one(h: str) -> dict:
        try:
            r = client.decide(h, questions)
        except JevError as exc:
            return {"headline": h, "error": str(exc)}
        a = r.answers
        return {
            "headline": h,
            "about_asset": round(a["about_asset"].p, 2),
            "material": round(a["material"].p, 2),
            "sentiment": a["sentiment"].choice,
            "sentiment_conf": round(a["sentiment"].confidence, 2),
            "event": a["event"].choice,
            "latency_ms": round(r.latency_ms),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, headlines))


def relevant_alerts(rows: list[dict], min_about: float = 0.6, min_material: float = 0.6,
                    min_conf: float = 0.5) -> list[dict]:
    """Filtro en código: solo lo que es del activo, material y con opinión clara."""
    return [r for r in rows if "error" not in r and r["about_asset"] >= min_about
            and r["material"] >= min_material and r["sentiment"] != "neutral" and r["sentiment_conf"] >= min_conf]

"""Categoría de cada mercado (política, deportes, cripto...) con Jev, o con palabras clave sin API key.

Se clasifica una vez por evento (event_slug), no por mercado: un evento como "Fed decision in July"
agrupa varios mercados de la misma categoría. Las respuestas de Jev quedan en caché.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from .jev_client import JevError, MockJev, choice

# La primera opción es la neutral: Jev tiende a elegir la primera cuando duda.
CATEGORIES = {
    "other": "None of the categories below",
    "politics": "Elections, governments, parties, politicians, legislation",
    "sports": "Matches, leagues, tournaments, athletes, races",
    "crypto": "Cryptocurrency prices, tokens, exchanges, blockchain",
    "economy": "Central banks, interest rates, inflation, jobs, GDP, companies' financial results",
    "geopolitics": "Wars, ceasefires, military actions, diplomacy, sanctions",
    "culture": "Entertainment, awards, celebrities, social media, music, movies",
    "tech": "Technology companies, AI, product launches, science, space",
}

QUESTION = choice("Which category does this prediction market belong to?", CATEGORIES)


def event_text(event_slug: str, title: str) -> str:
    slug = (event_slug or "").replace("-", " ")
    return f"Event: {slug}. Market: {title}".strip()


class Categorizer:
    """Llamable con una PositionResult: devuelve su categoría (memoriza por evento)."""

    def __init__(self, client=None, workers: int = 8, min_confidence: float = 0.2, max_calls: int | None = None):
        self.client = client or MockJev()
        self.fallback = MockJev()
        self.workers = workers
        self.min_confidence = min_confidence
        self.max_calls = max_calls  # tope de preguntas al cliente (Jev cobra por uso); el resto va por palabras clave
        self.cache: dict[str, str] = {}
        self.calls = 0
        self.errors = 0
        self._lock = threading.Lock()

    def _take_call(self) -> bool:
        with self._lock:
            if self.max_calls is not None and self.calls >= self.max_calls:
                return False
            self.calls += 1
            return True

    def _one(self, text: str) -> str:
        if self._take_call():
            try:
                a = self.client.decide(text, {"category": QUESTION}).answers["category"]
                if a.confidence >= self.min_confidence:
                    return a.choice
            except JevError:
                with self._lock:
                    self.errors += 1
        return self.fallback.decide(text, {"category": QUESTION}).answers["category"].choice

    def classify_many(self, items: list[tuple[str, str]]) -> None:
        """items: (event_slug, title). Clasifica en paralelo los que no estén memorizados."""
        todo = {}
        for slug, title in items:
            key = slug or title
            if key and key not in self.cache and key not in todo:
                todo[key] = event_text(slug, title)
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            for key, cat in zip(todo, ex.map(self._one, todo.values())):
                self.cache[key] = cat

    def __call__(self, pos) -> str:
        key = pos.event_slug or pos.title
        if key not in self.cache:
            self.cache[key] = self._one(event_text(pos.event_slug, pos.title))
        return self.cache[key]

    @property
    def name(self) -> str:
        return getattr(self.client, "name", getattr(getattr(self.client, "cfg", None), "model", "jev"))

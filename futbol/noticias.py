"""Noticias de jugadores con Jev: ¿un titular dice que alguien no juega o está en duda?

Antes de que salga la formación oficial, una lesión o una suspensión cambia todo en un mercado de remates. Jev lee
cada titular que nombra a un jugador y responde una pregunta tipada; la opción neutral va primero. Sin clave de
Jev se usa una heurística de palabras clave en castellano (y se avisa). Cuando la formación oficial está, manda
la formación: esto es solo un aviso previo.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from polylens.jev_client import Answer, JevError, JevResponse, MockJev, choice
from polylens.news import Headline

from .valor import norm

STATUS = choice("According to this football news headline, what is the situation of the named player for the "
                "team's next match?", {
                    "unclear": "The headline does not say anything clear about whether this player will play",
                    "out": "The player will not play: injury, suspension, not called up or ruled out",
                    "doubt": "The player is doubtful or has a physical problem",
                    "starts": "The player is expected to start",
                })


class SpanishKeywords:
    """Respaldo sin Jev: palabras clave en castellano. NO es Jev."""

    name = "palabras clave (sin Jev)"
    OUT = r"lesi[oó]n|desgarr|fractur|suspendid|expulsad|descartad|baja|no viaja|no (fue|será) convocad|operad|rotura"
    DOUBT = r"en duda|duda|molestia|diferenciad|sobrecarga|trabajo aparte|golpe"
    STARTS = r"titular|confirmad|vuelve|regresa|recuperad"

    def decide(self, state, questions) -> JevResponse:
        text = str(state.get("headline", "")) if isinstance(state, dict) else str(state)
        w = {"unclear": 0.1, "out": 0.0, "doubt": 0.0, "starts": 0.0}
        for key, pat in (("out", self.OUT), ("doubt", self.DOUBT), ("starts", self.STARTS)):
            if re.search(pat, text, re.I):
                w[key] += 1.0
        if max(w.values()) == 0.1:
            w["unclear"] = 1.0
        total = sum(w.values())
        probs = {k: v / total for k, v in w.items()}
        best = max(probs, key=probs.get)
        return JevResponse(self.name, {"status": Answer("choice", best, probs, probs[best])})


def mentions(headline: str, player_name: str) -> bool:
    """El titular nombra al jugador por su apellido (palabra completa, sin tildes)."""
    words = norm(player_name).split()
    if not words:
        return False
    last = words[-1]
    return len(last) >= 4 and re.search(rf"\b{re.escape(last)}\b", norm(headline)) is not None


def player_news(client, headlines: list[Headline], players: list[dict], min_confidence: float = 0.3,
                workers: int = 4) -> list[dict]:
    pairs = [(h, p) for h in headlines for p in players if mentions(h.title, p.get("name", ""))]
    client = client or SpanishKeywords()
    fallback = SpanishKeywords()

    def one(pair):
        h, p = pair
        state = {"headline": h.title, "player": p.get("name"), "team": p.get("team_name", "")}
        judge = client
        if isinstance(client, MockJev):  # MockJev no entiende esta pregunta: mejor las palabras clave
            r, judge = fallback.decide(state, {"status": STATUS}), fallback
        else:
            try:
                r = client.decide(state, {"status": STATUS})
            except JevError:
                r, judge = fallback.decide(state, {"status": STATUS}), fallback
        a = r.answers["status"]
        return {"player": p.get("player"), "name": p.get("name"), "headline": h.title, "link": h.link,
                "status": a.choice if a.confidence >= min_confidence else "unclear", "confidence": a.confidence,
                "judge": getattr(judge, "name", None) or getattr(getattr(judge, "cfg", None), "model", "jev")}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(one, pairs))
    order = {"out": 0, "doubt": 1, "starts": 2, "unclear": 3}
    return sorted(rows, key=lambda r: (order.get(r["status"], 9), -r["confidence"]))

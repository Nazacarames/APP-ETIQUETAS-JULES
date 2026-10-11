"""El "juez": pregunta a Jev y aplica la política EN CÓDIGO.

Patrón recomendado por TypeSafe ("confidence-gated routing"):
    código calcula el estado -> Jev lo interpreta -> código aplica la política
    -> ejecución coloca la orden.

Jev nunca abre una operación por su cuenta: solo puede vetar o achicar una
entrada que la estrategia determinística ya propuso.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import GateConfig
from .jev_client import JevError
from .questions import entry_review


@dataclass
class Verdict:
    allow: bool
    size_mult: float
    reasons: list[str] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    model: str = ""
    shadow: dict[str, Any] | None = None  # en modo sombra: lo que Jev habría decidido

    def summary(self) -> dict:
        out = {"allow": self.allow, "size_mult": self.size_mult, "reasons": self.reasons,
               "answers": self.answers, "latency_ms": round(self.latency_ms, 1), "model": self.model}
        if self.shadow is not None:
            out["shadow"] = self.shadow
        return out


class JevJudge:
    def __init__(self, client, gate: GateConfig):
        self.client = client
        self.gate = gate

    def review_entry(self, state: dict, asset: str | None = None, headlines: list[str] | None = None) -> Verdict:
        """Con GATE_SHADOW=true la estrategia opera siempre a tamaño completo y el veredicto de Jev
        solo queda registrado: así se miden sus vetos hacia adelante sin perder operaciones."""
        v = self._review(state, asset, headlines)
        if not self.gate.shadow:
            return v
        would = "aprobaría" if v.allow else "vetaría"
        return Verdict(True, 1.0, [f"modo sombra: Jev {would} ({'; '.join(v.reasons)})"], v.answers,
                       v.latency_ms, v.model, shadow={"allow": v.allow, "size_mult": v.size_mult, "reasons": v.reasons})

    def _review(self, state: dict, asset: str | None, headlines: list[str] | None) -> Verdict:
        if headlines:
            state = {**state, "recent_headlines": headlines[:10]}
        questions = entry_review(asset, with_news=bool(headlines))
        try:
            resp = self.client.decide(state, questions)
        except JevError as exc:
            if self.gate.fail_closed:
                return Verdict(False, 0.0, [f"jev no disponible ({exc}); fail-closed"])
            return Verdict(True, 0.5, [f"jev no disponible ({exc}); se opera a medio tamaño"])

        g = self.gate
        a = resp.answers
        reasons: list[str] = []
        allow, size = True, 1.0

        regime = a["regime"]
        if regime.choice != "trending_up":
            allow = False
            reasons.append(f"régimen={regime.choice}")
        elif regime.confidence < g.min_regime_conf:
            allow = False
            reasons.append(f"régimen dudoso (conf {regime.confidence:.2f})")

        setup = a["setup_quality"]
        if setup.value < g.min_setup_score:
            allow = False
            reasons.append(f"setup débil (score {setup.value:.2f}/2)")

        if "news_risk" in a and a["news_risk"].p >= g.max_news_risk:
            allow = False
            reasons.append(f"noticias negativas (p={a['news_risk'].p:.2f})")

        if allow:
            if min(regime.confidence, setup.confidence) < g.full_size_conf:
                size = 0.5
                reasons.append("confianza media -> medio tamaño")
            if a["overextended"].p >= g.max_overextended:
                size *= 0.5
                reasons.append(f"sobreextendido (p={a['overextended'].p:.2f}) -> mitad")
            if not reasons:
                reasons.append("todo alineado")

        return Verdict(allow, size if allow else 0.0, reasons,
                       {k: v.to_dict() for k, v in a.items()}, resp.latency_ms, resp.model)

"""Cliente mínimo de la API System One de TypeSafe (modelo Jev).

API (docs.typesafe.ai/api):
    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer $TYPESAFE_API_KEY
    {"state": ..., "model": "jev-latest", "questions": {id: {type, instructions, criteria}}}

Tipos de pregunta:
    noul   -> probabilidad de "sí" (0..1)
    choice -> una opción de un conjunto cerrado + probabilidades + confidence
    score  -> esperanza sobre niveles ordenados + probabilidades + confidence

Usa solo la librería estándar. Si preferís el SDK oficial: `pip install typesafe-sdk`
(TypeSafeClient.system_one(...)); la interfaz de este módulo es equivalente.

También incluye MockJev, una heurística LOCAL que imita la forma de las
respuestas para poder correr todo sin API key. MockJev NO es Jev: cualquier
resultado obtenido con él mide la heurística, no el modelo.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import JevConfig

# ------------------------------------------------------ constructores ----


def noul(instructions: Any, true: Any = None, false: Any = None) -> dict:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if true is not None or false is not None:
        q["criteria"] = {"true": true or "", "false": false or ""}
    return q


def choice(instructions: Any, criteria: dict[str, Any]) -> dict:
    if not 2 <= len(criteria) <= 255:
        raise ValueError("choice necesita entre 2 y 255 opciones")
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: Any, levels: list[Any]) -> dict:
    if not 2 <= len(levels) <= 10:
        raise ValueError("score necesita entre 2 y 10 niveles")
    return {"type": "score", "instructions": instructions, "criteria": levels}


# --------------------------------------------------------- respuestas ----


def choice_confidence(probs: dict[str, float]) -> float:
    """(p_max - 1/n) / (1 - 1/n)  — fórmula de docs.typesafe.ai/confidence."""
    n = len(probs)
    if n < 2:
        return 1.0
    return max(0.0, (max(probs.values()) - 1 / n) / (1 - 1 / n))


def score_confidence(probs: list[float]) -> float:
    """1 - MAD alrededor de la moda / MAD de una uniforme (recortado a 0)."""
    n = len(probs)
    m = max(range(n), key=lambda k: probs[k])
    mad = sum(p * abs(k - m) for k, p in enumerate(probs))
    mad_unif = sum(abs(k - (n - 1) / 2) for k in range(n)) / n
    return max(0.0, 1 - mad / mad_unif) if mad_unif else 1.0


@dataclass
class Answer:
    type: str
    value: Any                          # choice: str | score: float | noul: float
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def choice(self) -> str:
        return self.value

    @property
    def p(self) -> float:
        return float(self.value)

    def to_dict(self) -> dict:
        return {"type": self.type, "value": self.value,
                "probabilities": self.probabilities, "confidence": round(self.confidence, 4)}


@dataclass
class JevResponse:
    model: str
    answers: dict[str, Answer]
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    cached: bool = False

    def __getitem__(self, qid: str) -> Answer:
        return self.answers[qid]


class JevError(RuntimeError):
    """La API no respondió algo usable. El llamador decide (por defecto: no operar)."""


def parse_answer(raw: dict) -> Answer:
    t = raw["type"]
    if t == "noul":
        p = float(raw["noul"])
        # Noul no trae confidence; docs sugieren |2p - 1| para tratarlo igual que el resto.
        return Answer("noul", p, {"true": p, "false": 1 - p}, abs(2 * p - 1))
    probs = {str(k): float(v) for k, v in raw.get("probabilities", {}).items()}
    if t == "choice":
        conf = raw.get("confidence")
        return Answer("choice", raw["choice"], probs,
                      float(conf) if conf is not None else choice_confidence(probs))
    if t == "score":
        ordered = [probs[str(k)] for k in range(len(probs))]
        conf = raw.get("confidence")
        return Answer("score", float(raw["score"]), probs,
                      float(conf) if conf is not None else score_confidence(ordered))
    raise JevError(f"tipo de respuesta desconocido: {t}")


def parse_response(body: dict, latency_ms: float = 0.0, cached: bool = False) -> JevResponse:
    try:
        answers = {qid: parse_answer(a) for qid, a in body["answers"].items()}
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(f"respuesta mal formada: {exc}") from exc
    return JevResponse(body.get("model", "?"), answers, body.get("usage", {}), latency_ms, cached)


def average_answers(samples: list[Answer]) -> Answer:
    """Promedia distribuciones de N muestras y recalcula valor y confidence."""
    t = samples[0].type
    keys = samples[0].probabilities.keys()
    probs = {k: sum(s.probabilities.get(k, 0.0) for s in samples) / len(samples) for k in keys}
    if t == "noul":
        p = probs["true"]
        return Answer("noul", p, probs, abs(2 * p - 1))
    if t == "choice":
        return Answer("choice", max(probs, key=probs.get), probs, choice_confidence(probs))
    ordered = [probs[str(k)] for k in range(len(probs))]
    return Answer("score", sum(k * p for k, p in enumerate(ordered)), probs, score_confidence(ordered))


# --------------------------------------------------------------- cache ----


class AnswerCache:
    """Cache en disco (JSONL) clave = hash(modelo, state, preguntas, muestra).

    Hace los backtests reproducibles y baratos: la segunda corrida no llama a la API.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._mem: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._mem[rec["key"]] = rec["body"]

    @staticmethod
    def key(model: str, state: Any, questions: dict, sample: int) -> str:
        blob = json.dumps([model, state, questions, sample], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        return self._mem.get(key)

    def put(self, key: str, body: dict) -> None:
        self._mem[key] = body
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"key": key, "body": body}) + "\n")


# --------------------------------------------------------------- cliente ----

Transport = Callable[[str, dict, dict, float], tuple[int, dict]]


def urllib_transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except Exception:
            body = {"error": str(exc)}
        return exc.code, body


RETRYABLE = {429, 500, 502, 503, 504, 529}


class JevClient:
    def __init__(self, cfg: JevConfig, cache: AnswerCache | None = None,
                 transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep):
        if not cfg.api_key:
            raise ValueError("Falta TYPESAFE_API_KEY (o usá MockJev)")
        self.cfg = cfg
        self.cache = cache
        self.transport = transport
        self.sleep = sleep
        self.name = cfg.model

    def _post(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}
        last = ""
        for attempt in range(self.cfg.max_retries + 1):
            try:
                status, body = self.transport(self.cfg.base_url, headers, payload, self.cfg.timeout_s)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                status, body = 0, {"error": str(exc)}
            if status == 200:
                return body
            last = f"HTTP {status}: {body}"
            if status in (401, 403, 422):
                break  # no tiene sentido reintentar
            if attempt < self.cfg.max_retries and (status in RETRYABLE or status == 0):
                self.sleep(0.25 * (2 ** attempt))
        raise JevError(last)

    def decide(self, state: Any, questions: dict) -> JevResponse:
        t0 = time.perf_counter()
        samples: list[JevResponse] = []
        all_cached = True
        for k in range(max(1, self.cfg.samples)):
            key = AnswerCache.key(self.cfg.model, state, questions, k)
            body = self.cache.get(key) if self.cache else None
            if body is None:
                all_cached = False
                body = self._post({"state": state, "model": self.cfg.model, "questions": questions})
                if self.cache:
                    self.cache.put(key, body)
            samples.append(parse_response(body))
        latency = (time.perf_counter() - t0) * 1000
        if len(samples) == 1:
            r = samples[0]
            return JevResponse(r.model, r.answers, r.usage, latency, all_cached)
        merged = {qid: average_answers([s.answers[qid] for s in samples]) for qid in samples[0].answers}
        usage = {"input_tokens": sum(s.usage.get("input_tokens", 0) for s in samples)}
        return JevResponse(samples[0].model, merged, usage, latency, all_cached)


# ------------------------------------------------------------------ mock ----

_NEG = re.compile(r"\b(fraud|hack(ed)?|exploit|lawsuit|sue[sd]?|probe|investigat\w*|downgrade[sd]?|bankrupt\w*|"
                  r"delist\w*|halt(ed)?|recall|default\w*|crash\w*|plunge[sd]?|miss(es|ed)?|cut[s]?|"
                  r"warning|outage|ban(s|ned)?|fine[sd]?|resign\w*|layoffs?|sec charges)\b", re.I)
_POS = re.compile(r"\b(beat[s]?|upgrade[sd]?|record|approv\w*|partnership|surge[sd]?|soar\w*|raise[sd]? "
                  r"guidance|buyback|wins?|launch\w*|etf inflows?|rall(y|ies|ied))\b", re.I)


class MockJev:
    """Heurística local con la MISMA interfaz que JevClient.

    Lee el state generado por features.describe() y las preguntas de
    questions.py. Sirve para desarrollar, testear y demostrar el pipeline sin
    API key. No predice nada: sus reglas son las mismas que podrías escribir a mano.
    """

    name = "mock-jev (heurística local, NO es Jev)"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def decide(self, state: Any, questions: dict) -> JevResponse:
        from .features import PHRASE_INDEX

        labels: dict[str, str] = {}
        text = ""
        if isinstance(state, dict):
            for k, v in state.items():
                if isinstance(v, str) and v in PHRASE_INDEX:
                    key, label = PHRASE_INDEX[v]
                    labels[key] = label
                elif isinstance(v, list):
                    text += " " + " ".join(map(str, v))
                else:
                    text += " " + str(v)
        else:
            text = json.dumps(state) if not isinstance(state, str) else state

        answers = {}
        for qid, q in questions.items():
            answers[qid] = self._answer(qid, q, labels, text)
        return JevResponse(self.name, answers, {"input_tokens": 0}, 0.0, False)

    # -- reglas -------------------------------------------------------------
    def _answer(self, qid: str, q: dict, lab: dict, text: str) -> Answer:
        if qid == "regime":
            return self._regime(q, lab)
        if qid == "setup_quality":
            return self._setup(q, lab)
        if qid == "overextended":
            stretched = lab.get("momentum") == "overbought" and lab.get("medium_term_trend") == "far_above"
            p = 0.8 if stretched else (0.55 if lab.get("run_up") == "sharp_rise" else 0.2)
            return Answer("noul", p, {"true": p, "false": 1 - p}, abs(2 * p - 1))
        if qid in ("news_risk", "sentiment", "material", "about_asset", "event"):
            return self._news(qid, q, text)
        # Pregunta desconocida: distribución uniforme (confidence 0).
        return self._uniform(q)

    def _regime(self, q: dict, lab: dict) -> Answer:
        opts = list(q["criteria"])
        w = {o: 0.05 for o in opts}
        directional = lab.get("directionality") in ("steady", "moderate")
        up = lab.get("trend_slope") in ("rising", "rising_fast") and lab.get("long_term_trend") in ("above", "far_above")
        down = lab.get("trend_slope") in ("falling", "falling_fast") and lab.get("long_term_trend") in ("below", "far_below")
        wild = lab.get("volatility") == "very_high" and lab.get("directionality") in ("mixed", "choppy")
        if wild:
            w["disorderly"] += 0.7
        elif directional and up:
            w["trending_up"] += 0.75 if lab.get("directionality") == "steady" else 0.45
            w["range_bound"] += 0.1
        elif directional and down:
            w["trending_down"] += 0.6
        elif up:
            w["trending_up"] += 0.3
            w["range_bound"] += 0.35
        else:
            w["range_bound"] += 0.5
            w["disorderly"] += 0.1
        total = sum(w.values())
        probs = {o: round(v / total, 4) for o, v in w.items()}
        return Answer("choice", max(probs, key=probs.get), probs, choice_confidence(probs))

    def _setup(self, q: dict, lab: dict) -> Answer:
        pts = 0
        pts += lab.get("participation") in ("extreme", "above_avg")
        pts += lab.get("last_bar") == "near_high"
        pts += lab.get("breakout") == "clear"
        pts += lab.get("directionality") in ("steady", "moderate")
        pts += lab.get("trend_slope") in ("rising", "rising_fast")
        pts -= lab.get("momentum") == "overbought"
        pts -= lab.get("volatility") == "very_high"
        table = {5: [0.02, 0.18, 0.8], 4: [0.05, 0.35, 0.6], 3: [0.15, 0.55, 0.3], 2: [0.4, 0.45, 0.15]}
        dist = table.get(max(pts, 0), [0.7, 0.25, 0.05])
        n = len(q["criteria"])
        dist = dist if n == 3 else [1 / n] * n
        probs = {str(k): p for k, p in enumerate(dist)}
        return Answer("score", sum(k * p for k, p in enumerate(dist)), probs, score_confidence(dist))

    def _news(self, qid: str, q: dict, text: str) -> Answer:
        neg = len(_NEG.findall(text))
        pos = len(_POS.findall(text))
        if qid == "news_risk":
            p = min(0.95, 0.1 + 0.35 * neg)
            return Answer("noul", p, {"true": p, "false": 1 - p}, abs(2 * p - 1))
        if qid == "material":
            p = min(0.9, 0.2 + 0.3 * (neg + pos))
            return Answer("noul", p, {"true": p, "false": 1 - p}, abs(2 * p - 1))
        if qid == "about_asset":
            asset = ""
            instr = q.get("instructions")
            if isinstance(instr, dict):
                asset = str(instr.get("asset", ""))
            tokens = [t for t in re.findall(r"[A-Za-z]{3,}", asset) if t.lower() not in {"inc", "corp", "the"}]
            hit = any(re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in tokens)
            p = 0.9 if hit else 0.15
            return Answer("noul", p, {"true": p, "false": 1 - p}, abs(2 * p - 1))
        if qid == "sentiment":
            opts = list(q["criteria"])
            w = {o: 0.1 for o in opts}
            if neg > pos:
                w["negative"] += 0.7
            elif pos > neg:
                w["positive"] += 0.7
            else:
                w["neutral"] += 0.6
            total = sum(w.values())
            probs = {o: v / total for o, v in w.items()}
            return Answer("choice", max(probs, key=probs.get), probs, choice_confidence(probs))
        return self._uniform(q)

    @staticmethod
    def _uniform(q: dict) -> Answer:
        t = q["type"]
        if t == "noul":
            return Answer("noul", 0.5, {"true": 0.5, "false": 0.5}, 0.0)
        crit = q["criteria"]
        if t == "choice":
            probs = {o: 1 / len(crit) for o in crit}
            return Answer("choice", next(iter(crit)), probs, 0.0)
        probs = {str(k): 1 / len(crit) for k in range(len(crit))}
        return Answer("score", (len(crit) - 1) / 2, probs, 0.0)


def make_client(cfg: JevConfig, cache_path: str | Path | None = None):
    """JevClient real si hay API key; si no, MockJev (y lo avisa)."""
    if cfg.use_mock:
        return MockJev()
    cache = AnswerCache(cache_path) if cache_path else None
    return JevClient(cfg, cache=cache)

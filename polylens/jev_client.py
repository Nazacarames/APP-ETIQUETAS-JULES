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
respuestas para poder correr todo sin API key. MockJev NO es Jev.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import threading
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
        self._lock = threading.Lock()  # se puede usar desde varios hilos (evaluaciones en paralelo)
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
        with self._lock:
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

_WORD = re.compile(r"[a-záéíóúñ0-9]{3,}", re.I)
_STOP = {"the", "will", "and", "for", "with", "that", "this", "from", "after", "before", "what", "who", "how",
         "una", "los", "las", "del", "por", "que", "con", "para"}


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")} - _STOP


class MockJev:
    """Heurística local con la MISMA interfaz que JevClient, para correr sin API key.

    Entiende las preguntas de polylens (categories.py y news.py) por su id ("category", "relevant", "favors");
    cualquier otra recibe una distribución uniforme (confianza 0). MockJev NO es Jev.
    """

    name = "mock-jev (heurística local, NO es Jev)"

    def decide(self, state: Any, questions: dict) -> JevResponse:
        text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
        answers = {qid: self._answer(qid, q, state, text) for qid, q in questions.items()}
        return JevResponse(self.name, answers, {"input_tokens": 0}, 0.0, False)

    def _answer(self, qid: str, q: dict, state: Any, text: str) -> Answer:
        if qid == "category" and q["type"] == "choice":
            return self._category(q, text)
        if qid == "relevant" and q["type"] == "noul":
            headline = state.get("headline", "") if isinstance(state, dict) else text
            market = state.get("market", "") if isinstance(state, dict) else text
            overlap = len(_words(headline) & _words(market))
            p = min(0.9, 0.1 + 0.25 * overlap)
            return Answer("noul", p, {"true": p, "false": 1 - p}, abs(2 * p - 1))
        return self._uniform(q)

    @staticmethod
    def _category(q: dict, text: str) -> Answer:
        keywords = {
            "politics": r"elect|president|senate|house|parliament|minister|vote|party|congress|trump|biden|government",
            "sports": r" vs\.? | win on |nba|nfl|mlb|nhl|f1|grand prix|fifa|world cup|champions|match|game|tennis|ufc",
            "crypto": r"bitcoin|btc|eth|ethereum|solana|crypto|token|coin|etf",
            "economy": r"fed|interest rate|inflation|cpi|gdp|recession|unemployment|tariff|bps",
            "geopolitics": r"wars?\b|ceasefire|invade|invasion|nato|sanction|military|strike|ukraine|russia|israel|iran|china",
            "culture": r"oscar|grammy|movie|album|song|tweet|celebrity|tiktok|youtube|box office",
            "tech": r"\bai\b|openai|apple|google|tesla|nvidia|launch|spacex|iphone",
        }
        opts = list(q["criteria"])
        w = {o: 0.02 for o in opts}
        for cat, pat in keywords.items():
            if cat in w and re.search(rf"\b(?:{pat})", text, re.I):  # palabra que empieza así ("eth" no es "Something")
                w[cat] += 1.0
        if all(v == 0.02 for v in w.values()) and "other" in w:
            w["other"] += 1.0
        total = sum(w.values())
        probs = {o: v / total for o, v in w.items()}
        return Answer("choice", max(probs, key=probs.get), probs, choice_confidence(probs))

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

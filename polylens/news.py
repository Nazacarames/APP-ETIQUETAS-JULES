"""Noticias ↔ mercados: ¿qué titulares tocan los mercados donde está apostando el "smart money"?

1. Se leen titulares de feeds RSS/Atom.
2. Un filtro barato (palabras en común) arma pares titular–mercado candidatos.
3. Jev juzga cada par con dos preguntas tipadas: ¿es relevante? y ¿a favor o en contra del resultado
   que tienen los traders seguidos? La opción conservadora va primero ("no está claro").

Jev solo lee texto: nada de cuentas ni fechas en las preguntas (eso lo resuelve el código).
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from typing import Callable

from .http import USER_AGENT
from .jev_client import JevError, MockJev, choice, noul
from .study import parse_ts

QUESTIONS = {
    "relevant": noul("Does this news headline directly affect how likely this prediction market outcome is?"),
    "favors": choice("Which way does the headline push the outcome held by the tracked traders?", {
        "unclear": "The headline does not clearly change the odds of that outcome, or it is unrelated",
        "supports": "The headline makes the outcome held by the tracked traders more likely",
        "against": "The headline makes the outcome held by the tracked traders less likely",
    }),
}

_WORD = re.compile(r"[a-záéíóúñ0-9]{4,}", re.I)
_STOP = {"will", "with", "that", "this", "from", "after", "before", "what", "when", "where", "which", "their", "there",
         "about", "than", "then", "have", "been", "were", "they", "says", "said", "into", "over", "more", "most",
         "next", "by", "2025", "2026", "2027", "2028", "market", "markets", "price", "news", "week", "year", "today",
         "end", "december", "january", "october", "november", "september", "june", "july", "august", "march",
         "april", "february", "win", "wins", "won"}


@dataclass
class Headline:
    title: str
    link: str = ""
    published: int | None = None
    source: str = ""


def words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")} - _STOP


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _date(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(parsedate_to_datetime(text).timestamp())  # RSS: 'Sat, 11 Oct 2026 10:00:00 GMT'
    except (TypeError, ValueError, IndexError):
        return parse_ts(text)  # Atom: ISO 8601


def parse_feed(xml_text: str, source: str = "") -> list[Headline]:
    """RSS 2.0 (<item>) o Atom (<entry>). Ignora lo que no entiende."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields = {_local(c.tag): c for c in node}
        title = (fields.get("title").text or "").strip() if fields.get("title") is not None else ""
        if not title:
            continue
        link_el = fields.get("link")
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        when = None
        for key in ("pubDate", "published", "updated", "date"):
            if fields.get(key) is not None:
                when = _date(fields[key].text)
                break
        out.append(Headline(title, link, when, source))
    return out


def fetch_feed(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def market_text(m: dict) -> str:
    return f"Market: {m.get('title')}. Outcome held by the tracked traders: {m.get('outcome')}"


def candidate_pairs(headlines: list[Headline], markets: list[dict], min_overlap: int = 2,
                    max_pairs: int = 40) -> list[tuple[Headline, dict, int]]:
    """Pares con al menos `min_overlap` palabras significativas en común, los más parecidos primero."""
    mw = [(m, words(f"{m.get('title')} {m.get('outcome')} {(m.get('event_slug') or '').replace('-', ' ')}"))
          for m in markets]
    pairs = []
    for h in headlines:
        hw = words(h.title)
        for m, w in mw:
            k = len(hw & w)
            if k >= min_overlap:
                pairs.append((h, m, k))
    pairs.sort(key=lambda x: -x[2])
    return pairs[:max_pairs]


def judge_pairs(client, pairs: list[tuple[Headline, dict, int]], min_relevance: float = 0.5,
                workers: int = 4) -> list[dict]:
    """Pregunta a Jev por cada par. Si Jev falla, el par queda afuera (no se inventa una respuesta)."""
    def one(pair):
        h, m, k = pair
        state = {"headline": h.title, "market": market_text(m)}
        try:
            r = client.decide(state, QUESTIONS)
        except JevError:
            return None
        rel, fav = r.answers["relevant"], r.answers["favors"]
        return {"headline": asdict(h), "market": {k2: m.get(k2) for k2 in
                                                  ("title", "outcome", "event_slug", "current_price", "n", "value")},
                "overlap": k, "relevance": round(rel.p, 3), "favors": fav.choice,
                "favors_confidence": round(fav.confidence, 3)}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = [r for r in ex.map(one, pairs) if r]
    rows = [r for r in rows if r["relevance"] >= min_relevance]
    rows.sort(key=lambda r: (r["relevance"], r["favors_confidence"]), reverse=True)
    return rows


def news_scan(client, feeds: list[str], markets: list[dict], fetch: Callable[[str], str] = fetch_feed,
              min_overlap: int = 2, max_pairs: int = 40, min_relevance: float = 0.5,
              progress: Callable[[str], None] = lambda s: None) -> dict:
    headlines, errors = [], {}
    for url in feeds:
        try:
            got = parse_feed(fetch(url), source=url)
            headlines.extend(got)
            progress(f"  {len(got)} titulares de {url}")
        except Exception as exc:  # un feed caído no frena el resto
            errors[url] = repr(exc)
    seen, unique = set(), []
    for h in headlines:
        if h.title.lower() not in seen:
            seen.add(h.title.lower())
            unique.append(h)
    pairs = candidate_pairs(unique, markets, min_overlap, max_pairs)
    progress(f"{len(pairs)} pares titular–mercado para que juzgue {getattr(client, 'name', 'Jev')}")
    rows = judge_pairs(client or MockJev(), pairs, min_relevance)
    return {"meta": {"feeds": feeds, "headlines": len(unique), "pairs": len(pairs), "errors": errors,
                     "judge": getattr(client, "name", None) or getattr(getattr(client, "cfg", None), "model", "jev")},
            "matches": rows}

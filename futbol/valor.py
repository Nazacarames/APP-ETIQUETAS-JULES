"""Valor contra las cuotas de bet365, monto sugerido con 100 USD y diario de apuestas en papel.

- Cuotas: las que trae API-Football para bet365 y las que el usuario carga a mano en data/futbol/cuotas.csv
  (formato: fixture,jugador,mercado,linea,cuota — mercado = remates | remates_al_arco, linea = 0.5, 1.5, 2.5).
  No se scrapea bet365: sus reglas prohíben el acceso automático.
- Valor = probabilidad del modelo × cuota − 1. Se sugiere apostar solo con valor ≥ 5 % y nunca más del 3 % del
  capital (un cuarto de Kelly). Las cuotas con errores evidentes la casa las anula: no son "oportunidades".
- Todo va primero al diario en papel (data/futbol/papel.jsonl) y se liquida con los datos reales del partido.
"""
from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from pathlib import Path

MARKET_ALIASES = {"remates": "shots", "remates_al_arco": "sot", "shots": "shots", "sot": "sot",
                  "tiros": "shots", "tiros_al_arco": "sot"}


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def match_player(name: str, players: list[dict]) -> dict | None:
    """Encuentra al jugador por nombre (sin tildes; acepta "E. Cavani", "Cavani" o el nombre completo)."""
    n = norm(name)
    if not n:
        return None
    exact = [p for p in players if norm(p.get("name")) == n]
    if exact:
        return exact[0]
    last = n.split()[-1]
    cands = [p for p in players if norm(p.get("name")).split()[-1:] == [last]]
    if len(cands) == 1:
        return cands[0]
    if len(n.split()) < 2:
        return None  # solo el apellido y hay varios: no adivinar
    first = n.split()[0].rstrip(".")
    cands = [p for p in cands if norm(p.get("name")).startswith(first[:1])]
    return cands[0] if len(cands) == 1 else None


def ev(p: float, odd: float) -> float:
    return p * odd - 1


def stake(p: float, odd: float, bankroll: float, kelly_fraction: float = 0.25, cap: float = 0.03) -> float:
    """Un cuarto de Kelly, con tope en `cap` del capital. Sin valor, cero."""
    if odd <= 1 or p <= 0:
        return 0.0
    kelly = (p * odd - 1) / (odd - 1)
    return round(bankroll * max(0.0, min(cap, kelly_fraction * kelly)), 2)


_LINE = re.compile(r"(?:over|más de|mas de|\+)\s*(\d+(?:[.,]5)?)|(\d+)\s*\+", re.I)


def threshold_from(text: str) -> int | None:
    """'Over 0.5' → 1, '1.5' → 2, '2+' → 2."""
    m = _LINE.search(str(text))
    if m:
        if m.group(1):
            return int(float(m.group(1).replace(",", ".")) + 0.5)
        return int(m.group(2))
    try:
        return int(float(str(text).replace(",", ".")) + 0.5)
    except ValueError:
        return None


def api_player_odds(rows: list[dict], players: list[dict]) -> tuple[list[dict], list[dict]]:
    """De las filas de /odds, toma los mercados de remates de jugadores (si la casa los ofrece por la API)."""
    found, other = [], []
    for r in rows:
        m = norm(r["market"])
        if "shot" not in m:
            other.append(r)
            continue
        stat = "sot" if ("target" in m or "on goal" in m) else "shots"
        sel = r["selection"]
        if "under" in norm(sel):
            continue
        name = re.split(r"\s+-\s+|\s+over\s+|\s+\(", sel, maxsplit=1, flags=re.I)[0]
        p = match_player(name, players)
        k = threshold_from(r.get("handicap") or sel)
        if p and k:
            found.append({"player": p["player"], "name": p["name"], "stat": stat, "k": k, "odd": r["odd"],
                          "source": "api"})
        else:
            other.append(r)
    return found, other


def manual_odds(path: Path, fixture: int, players: list[dict]) -> tuple[list[dict], list[str]]:
    out, problems = [], []
    if not Path(path).exists():
        return out, problems
    with open(path, encoding="utf-8") as fh:
        for i, r in enumerate(csv.DictReader(fh), 2):
            try:
                if int(r["fixture"]) != int(fixture):
                    continue
                stat = MARKET_ALIASES[r["mercado"].strip().lower()]
                k = threshold_from(r["linea"])
                odd = float(str(r["cuota"]).replace(",", "."))
            except (KeyError, ValueError, TypeError):
                problems.append(f"línea {i}: formato inválido")
                continue
            p = match_player(r["jugador"], players)
            if not p or not k:
                problems.append(f"línea {i}: no encontré a {r['jugador']!r} entre los titulares probables")
                continue
            out.append({"player": p["player"], "name": p["name"], "stat": stat, "k": k, "odd": odd,
                        "source": "manual"})
    return out, problems


def value_bets(odds: list[dict], table: list[dict], bankroll: float, min_edge: float = 0.05,
               cap: float = 0.03) -> list[dict]:
    probs = {r["player"]: r for r in table}
    out = []
    for o in odds:
        row = probs.get(o["player"])
        key = f"p_{o['stat']}_{o['k']}"
        if not row or key not in row:
            continue
        p = row[key]
        e = ev(p, o["odd"])
        out.append({**o, "p": p, "fair_odd": 1 / p if p else None, "ev": e,
                    "stake": stake(p, o["odd"], bankroll, cap=cap) if e >= min_edge else 0.0})
    return sorted(out, key=lambda b: -b["ev"])


# -- diario en papel --------------------------------------------------------------------------
def journal_add(path: Path, fixture: int, bets: list[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "a", encoding="utf-8") as fh:
        for b in bets:
            if b.get("stake", 0) <= 0:
                continue
            fh.write(json.dumps({"t": int(time.time()), "fixture": fixture, "player": b["player"], "name": b["name"],
                                 "stat": b["stat"], "k": b["k"], "odd": b["odd"], "p": round(b["p"], 4),
                                 "stake": b["stake"], "status": "pendiente"}, ensure_ascii=False) + "\n")
            n += 1
    return n


def journal_settle(path: Path, appearances: list[dict], bankroll: float = 100.0) -> dict:
    """Liquida las apuestas pendientes con lo que hizo el jugador. Si no jugó, se anula (como en bet365)."""
    path = Path(path)
    if not path.exists():
        return {"bets": 0, "bankroll": bankroll}
    actual = {(a["fixture"], a["player"]): a for a in appearances}
    played_fixtures = {a["fixture"] for a in appearances}
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for e in entries:
        if e["status"] != "pendiente" or e["fixture"] not in played_fixtures:
            continue
        a = actual.get((e["fixture"], e["player"]))
        if a is None:
            e.update(status="anulada", pnl=0.0)
        else:
            won = a[e["stat"]] >= e["k"]
            e.update(status="ganada" if won else "perdida", pnl=round(e["stake"] * (e["odd"] - 1) if won else -e["stake"], 2))
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    settled = [e for e in entries if e["status"] in ("ganada", "perdida")]
    staked = sum(e["stake"] for e in settled)
    pnl = sum(e["pnl"] for e in settled)
    return {"bets": len(entries), "settled": len(settled), "won": sum(e["status"] == "ganada" for e in settled),
            "pending": sum(e["status"] == "pendiente" for e in entries), "staked": round(staked, 2),
            "pnl": round(pnl, 2), "roi": pnl / staked if staked else None, "bankroll": round(bankroll + pnl, 2),
            "expected_win_rate": (sum(e["p"] for e in settled) / len(settled)) if settled else None}

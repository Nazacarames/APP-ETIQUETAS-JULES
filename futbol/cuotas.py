"""Cuotas actuales de bet365 (vía API-Football) contra Pinnacle y contra sí mismas.

El plan gratis de API-Football no da la temporada 2026 por liga, pero sí las cuotas de cada partido (incluidas las
de bet365, con los planteles actuales). Con eso se buscan dos cosas, sin entrar a bet365:

1. **bet365 contra Pinnacle** en mercados del partido (ganador, goles, ambos marcan...). Pinnacle es la casa de
   referencia más precisa: se le quita el margen y queda una probabilidad "justa". Si bet365 paga más que eso
   (valor = prob. justa × cuota bet365 − 1), la cuota está desalineada a favor del apostador.
2. **Incoherencias de bet365** en mercados de jugadores: todo gol cuenta como remate al arco (Opta), y "2+ remates"
   no puede ser más probable que "1+". Si las cuotas de bet365 dicen lo contrario, uno de los dos precios está mal.

Ojo con lo que esto NO es: las cuotas con errores evidentes la casa las anula, y en la historia (ver
research/RESULTADOS-apuestas-deportivas.md) bet365 contra Pinnacle no mostró una ventaja confirmada. Todo va
primero al diario en papel.
"""
from __future__ import annotations

import re
from collections import defaultdict

REFERENCE = "Pinnacle"
BOOK = "Bet365"
# mercados de equipo que se comparan; la clave es el nombre en API-Football
# (el hándicap asiático queda afuera: cada casa nombra distinto el lado visitante de la línea y se cruzan mal)
TEAM_MARKETS = ("Match Winner", "Goals Over/Under", "Both Teams Score", "Goals Over/Under First Half",
                "First Half Winner", "Total - Home", "Total - Away")
_LINE = re.compile(r"^(Over|Under)\s*(\d+(?:\.\d+)?)$", re.I)
_PLAYER_K = re.compile(r"^(.*\S)\s+-\s+(\d+)$")


def book_markets(item: dict) -> dict[str, dict[str, dict[str, float]]]:
    """{casa: {mercado: {selección: cuota}}} para un partido de la respuesta de /odds."""
    out: dict = defaultdict(dict)
    for b in item.get("bookmakers") or []:
        for bet in b.get("bets") or []:
            sel = {}
            for v in bet.get("values") or []:
                try:
                    sel[str(v["value"]).strip()] = float(v["odd"])
                except (KeyError, TypeError, ValueError):
                    continue
            if sel:
                out[b.get("name")][bet.get("name")] = sel
    return out


def outcome_groups(market: str, selections: dict[str, float]) -> list[dict[str, float]]:
    """Agrupa las selecciones en conjuntos que suman 100 %: local/empate/visitante, sí/no, 'Over 2.5'/'Under 2.5'."""
    if market in ("Match Winner", "First Half Winner"):
        g = {k: selections[k] for k in ("Home", "Draw", "Away") if k in selections}
        return [g] if len(g) == 3 else []
    if market == "Both Teams Score":
        g = {k: selections[k] for k in ("Yes", "No") if k in selections}
        return [g] if len(g) == 2 else []
    by_line: dict = defaultdict(dict)
    for sel, odd in selections.items():
        m = _LINE.match(sel)
        if not m:
            continue
        by_line[float(m.group(2))][sel] = odd
    return [g for g in by_line.values() if len(g) == 2]


def fair_probs(group: dict[str, float]) -> dict[str, float]:
    """Quita el margen repartiéndolo en proporción (método multiplicativo)."""
    inv = {k: 1 / o for k, o in group.items() if o > 1}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()} if total else {}


def team_value(item: dict, book: str = BOOK, reference: str = REFERENCE, min_edge: float = 0.0,
               max_margin: float = 0.15) -> list[dict]:
    """Cada selección de `book` con su probabilidad justa según `reference` y el valor que eso implica.

    Se descartan grupos con margen negativo o mayor a `max_margin` en cualquiera de las dos casas: son datos que
    no cierran (líneas cruzadas, cuotas viejas), no oportunidades."""
    markets = book_markets(item)
    ref, mine = markets.get(reference) or {}, markets.get(book) or {}
    out = []
    for market in TEAM_MARKETS:
        if market not in ref or market not in mine:
            continue
        for group in outcome_groups(market, ref[market]):
            margin = sum(1 / o for o in group.values()) - 1
            mine_group = {k: mine[market].get(k) for k in group}
            if None in mine_group.values() or not 0 <= margin <= max_margin:
                continue
            if not 0 <= sum(1 / o for o in mine_group.values()) - 1 <= max_margin:
                continue
            probs = fair_probs(group)
            for sel, p in probs.items():
                odd = mine[market].get(sel)
                if not odd:
                    continue
                ev = p * odd - 1
                if ev >= min_edge:
                    out.append({"market": market, "selection": sel, "odd": odd, "ref_odd": group[sel],
                                "fair_odd": 1 / p, "p": p, "ev": ev, "ref_margin": margin})
    return sorted(out, key=lambda r: -r["ev"])


def bet365_players(item: dict, book: str = BOOK) -> dict[str, dict]:
    """{jugador: {"shots": {k: cuota}, "sot": {k: cuota}, "goal": cuota}} desde los mercados de bet365."""
    players: dict = defaultdict(lambda: {"shots": {}, "sot": {}, "goal": None, "side": None})
    for market, sel in (book_markets(item).get(book) or {}).items():
        side = "home" if market.startswith("Home ") else "away" if market.startswith("Away ") else None
        if "Player Shots" in market:
            stat = "sot" if "On Target" in market else "shots"
            for name_k, odd in sel.items():
                m = _PLAYER_K.match(name_k)
                if m:
                    p = players[m.group(1)]
                    p[stat][int(m.group(2))] = odd
                    p["side"] = p["side"] or side
        elif market == "Anytime Goal Scorer" or market.endswith(" Anytime Goal Scorer"):
            for name, odd in sel.items():
                if name.lower() not in ("no goalscorer", "no goal"):
                    players[name]["goal"] = odd
                    players[name]["side"] = players[name]["side"] or side
    return dict(players)


def coherence_flags(players: dict[str, dict], tolerance: float = 0.0) -> list[dict]:
    """Precios de bet365 que se contradicen entre sí (comparando probabilidades implícitas = 1/cuota).

    - gol vs 1+ remate al arco: todo gol es remate al arco, así que P(gol) ≤ P(1+ al arco).
    - 1+ al arco vs 1+ remate: P(1+ al arco) ≤ P(1+ remate).
    - k+1 vs k: P(k+1) ≤ P(k), en remates y en remates al arco.
    Como cada cuota trae su margen, se marca solo si la contradicción supera `tolerance`.
    """
    flags = []

    def check(name, kind, cheap, cheap_odd, dear, dear_odd):
        # 'cheap' debería ser el evento menos probable (cuota más alta) que 'dear'
        if cheap_odd and dear_odd and 1 / cheap_odd > 1 / dear_odd * (1 + tolerance):
            flags.append({"player": name, "check": kind, "should_be_less_likely": cheap, "odd": cheap_odd,
                          "than": dear, "than_odd": dear_odd,
                          "gap": 1 / cheap_odd - 1 / dear_odd})

    for name, p in players.items():
        check(name, "gol > 1+ al arco", "gol", p["goal"], "1+ al arco", p["sot"].get(1))
        check(name, "al arco > remates", "1+ al arco", p["sot"].get(1), "1+ remate", p["shots"].get(1))
        for stat, label in (("shots", "remates"), ("sot", "al arco")):
            ks = sorted(p[stat])
            for a, b in zip(ks, ks[1:]):
                check(name, f"{b}+ > {a}+ {label}", f"{b}+ {label}", p[stat][b], f"{a}+ {label}", p[stat][a])
    return sorted(flags, key=lambda f: -f["gap"])


def summary(item: dict) -> dict:
    fx = item.get("fixture") or {}
    lg = item.get("league") or {}
    return {"fixture": fx.get("id"), "date": fx.get("date"), "league": lg.get("name"), "league_id": lg.get("id"),
            "update": item.get("update"), "books": sorted(book_markets(item))}


def settle_team(market: str, selection: str, home: int, away: int, ht: tuple[int, int] | None = None) -> bool | None:
    """¿Ganó la selección con este resultado? None si no se puede saber (p. ej. falta el entretiempo) o es nula."""
    first_half = market in ("Goals Over/Under First Half", "First Half Winner")
    if first_half:
        if ht is None:
            return None
        home, away = ht
    if market in ("Match Winner", "First Half Winner"):
        res = "Home" if home > away else "Away" if away > home else "Draw"
        return selection == res
    if market == "Both Teams Score":
        return (home > 0 and away > 0) == (selection == "Yes")
    m = _LINE.match(selection)
    if not m:
        return None
    total = {"Total - Home": home, "Total - Away": away}.get(market, home + away)
    line = float(m.group(2))
    if total == line:
        return None  # línea entera exacta: se devuelve la apuesta
    return (total > line) == (m.group(1).lower() == "over")


def league_fixtures_for_date(api, date: str, league: int, max_pages: int = 40) -> list[dict]:
    """IDs de partidos de `league` en `date`: primero por calendario (1 pedido); si el plan no lo permite,
    recorre el listado de partidos con cuotas (hasta `max_pages` pedidos, guardados en caché por 3 h)."""
    from .api import ApiError
    try:
        fx = [f for f in api.fixtures_by_date(date) if (f.get("league") or {}).get("id") == league]
        return [{"fixture": f["fixture"]["id"], "date": f["fixture"].get("date"),
                 "home": f["teams"]["home"]["name"], "away": f["teams"]["away"]["name"]} for f in fx]
    except ApiError:
        pass
    out = []
    for rows in api.odds_mapping_pages(max_pages):
        for r in rows:
            if (r.get("league") or {}).get("id") == league and str((r.get("fixture") or {}).get("date", "")).startswith(date):
                out.append({"fixture": r["fixture"]["id"], "date": r["fixture"]["date"], "home": None, "away": None})
    return out

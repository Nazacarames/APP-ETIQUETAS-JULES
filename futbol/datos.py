"""Sincronización con API-Football y tablas locales de la Liga Argentina.

`sync` baja, de a poco y sin pasarse del cupo diario, las estadísticas por jugador y los eventos (goles, tarjetas)
de cada partido terminado, y los guarda en data/futbol/raw/. Lo ya bajado no se vuelve a pedir.
`appearances` arma una fila por jugador y partido: es la base del modelo de remates.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .api import FINISHED, ApiError, ApiFootball


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def _read(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def fixtures_path(data_dir: Path, league: int, season: int) -> Path:
    return Path(data_dir) / f"fixtures_{league}_{season}.json"


def sync(api: ApiFootball, league: int, season: int, data_dir: Path, max_calls: int = 90,
         kinds: tuple[str, ...] = ("players", "events"),
         progress: Callable[[str], None] = lambda s: None) -> dict:
    """Baja lo que falte, de los partidos más viejos a los más nuevos, hasta gastar `max_calls` pedidos."""
    data_dir = Path(data_dir)
    start = api.http.requests
    fixtures = api.fixtures(league, season)
    _write(fixtures_path(data_dir, league, season), fixtures)
    done = sorted((f for f in fixtures if (f.get("fixture") or {}).get("status", {}).get("short") in FINISHED),
                  key=lambda f: f["fixture"].get("timestamp") or 0)
    fetchers = {"players": api.fixture_players, "events": api.fixture_events}
    got = {k: 0 for k in kinds}
    pending = 0
    stopped = None
    for f in done:
        fid = f["fixture"]["id"]
        for kind in kinds:
            path = data_dir / "raw" / kind / f"{fid}.json"
            if path.exists():
                continue
            if api.http.requests - start >= max_calls:
                pending += 1
                continue
            try:
                _write(path, fetchers[kind](fid))
                got[kind] += 1
            except ApiError as exc:  # p. ej. cupo diario agotado: se sigue otro día
                stopped = str(exc)
                pending += 1
                break
        if stopped:
            break
    used = api.http.requests - start
    progress(f"partidos terminados: {len(done)} · nuevos: {got} · pendientes: {pending} · pedidos usados: {used}")
    return {"finished": len(done), "fetched": got, "pending": pending, "calls": used, "stopped": stopped}


def _num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def appearances(data_dir: Path, league: int, season: int) -> list[dict]:
    """Una fila por jugador que jugó (minutos > 0) en un partido terminado ya bajado, en orden cronológico."""
    data_dir = Path(data_dir)
    fixtures = {f["fixture"]["id"]: f for f in _read(fixtures_path(data_dir, league, season)) or []}
    rows = []
    for fid, f in fixtures.items():
        teams_raw = _read(data_dir / "raw" / "players" / f"{fid}.json")
        if not teams_raw:
            continue
        has_shots = any(((p.get("statistics") or [{}])[0].get("shots") or {}).get("total") is not None
                        for team in teams_raw for p in team.get("players") or [])
        if not has_shots:
            continue  # partido sin datos de remates: contarlo como ceros sesgaría el modelo
        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        for team in teams_raw:
            tid = (team.get("team") or {}).get("id")
            if tid not in (home_id, away_id):
                continue
            opp = away_id if tid == home_id else home_id
            for p in team.get("players") or []:
                st = (p.get("statistics") or [{}])[0]
                games = st.get("games") or {}
                minutes = _num(games.get("minutes"))
                if minutes <= 0:
                    continue
                shots = st.get("shots") or {}
                goals = st.get("goals") or {}
                cards = st.get("cards") or {}
                rows.append({
                    "fixture": fid, "ts": f["fixture"].get("timestamp") or 0, "round": f["league"].get("round"),
                    "team": tid, "team_name": team["team"].get("name"), "opp": opp,
                    "opp_name": f["teams"]["away" if tid == home_id else "home"]["name"], "home": tid == home_id,
                    "player": (p.get("player") or {}).get("id"), "name": (p.get("player") or {}).get("name"),
                    "pos": games.get("position") or "", "minutes": minutes, "started": not games.get("substitute"),
                    "shots": _num(shots.get("total")), "sot": _num(shots.get("on")),
                    "goals": _num(goals.get("total")), "assists": _num(goals.get("assists")),
                    "yellow": _num(cards.get("yellow")), "red": _num(cards.get("red")),
                })
    rows.sort(key=lambda r: (r["ts"], r["fixture"], r["team"], r["player"] or 0))
    return rows


def goal_events(data_dir: Path, league: int, season: int) -> list[dict]:
    """Partidos terminados con la lista de goles (minuto y equipo), para el análisis por minuto."""
    data_dir = Path(data_dir)
    out = []
    for f in _read(fixtures_path(data_dir, league, season)) or []:
        fid = f["fixture"]["id"]
        if f["fixture"].get("status", {}).get("short") not in FINISHED:
            continue
        events = _read(data_dir / "raw" / "events" / f"{fid}.json")
        if events is None:
            continue
        home = f["teams"]["home"]["id"]
        goals = []
        for e in events:
            if e.get("type") != "Goal" or "Missed" in str(e.get("detail")):
                continue
            t = e.get("time") or {}
            elapsed, extra = int(t.get("elapsed") or 0), int(t.get("extra") or 0)
            if elapsed > 90:  # alargue: queda afuera del análisis de 90 minutos
                continue
            goals.append({"minute": elapsed, "extra": extra, "home": (e.get("team") or {}).get("id") == home})
        goals.sort(key=lambda g: (g["minute"], g["extra"]))
        out.append({"fixture": fid, "ts": f["fixture"].get("timestamp") or 0, "goals": goals,
                    "final": (f["goals"].get("home"), f["goals"].get("away"))})
    return sorted(out, key=lambda m: m["ts"])


def load_appearances(data_dir: Path, competitions) -> list[dict]:
    rows = []
    for league, season in competitions:
        rows += [{**r, "league": league, "season": season} for r in appearances(data_dir, league, season)]
    rows.sort(key=lambda r: (r["ts"], r["fixture"], r["team"], r["player"] or 0))
    return rows


def load_goal_events(data_dir: Path, competitions) -> list[dict]:
    out = []
    for league, season in competitions:
        out += goal_events(data_dir, league, season)
    return sorted(out, key=lambda m: m["ts"])


def find_fixture(data_dir: Path, competitions, fixture_id: int) -> dict | None:
    for league, season in competitions:
        for f in _read(fixtures_path(Path(data_dir), league, season)) or []:
            if f["fixture"]["id"] == fixture_id:
                return f
    return None


def all_fixtures(data_dir: Path, competitions) -> list[dict]:
    out = []
    for league, season in competitions:
        out += _read(fixtures_path(Path(data_dir), league, season)) or []
    return sorted(out, key=lambda f: f["fixture"].get("timestamp") or 0)

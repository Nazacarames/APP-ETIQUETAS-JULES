"""Analista de fútbol argentino. Ejemplos:

    python3 -m futbol estado                       # plan y pedidos usados hoy en API-Football
    python3 -m futbol sync                         # baja lo que falte (respeta el cupo diario)
    python3 -m futbol validar                      # ¿el modelo de remates acierta? (sin mirar el futuro)
    python3 -m futbol remates --top 20             # ritmo de remates por equipo y por jugador
    python3 -m futbol partido 1234567 --anotar     # probabilidades, cuotas de bet365 y valor; anota en papel
    python3 -m futbol minutos --minuto 70 --resultado 1-0 --cuota 2.10
    python3 -m futbol noticias --partido 1234567 --rss https://...
    python3 -m futbol papel                        # liquida y resume las apuestas en papel (100 USD)
    python3 -m futbol cuotas --fecha 2026-10-12    # cuotas actuales: bet365 contra Pinnacle e incoherencias
    python3 -m futbol cuotas --partido 1490520 --anotar

Solo analiza. Las apuestas las decide y las hace el usuario en una casa con licencia de su provincia.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from itertools import groupby

from polylens.jev_client import MockJev, make_client
from polylens.news import fetch_feed, parse_feed

from . import cuotas as cq
from . import minutos, valor
from .api import FINISHED, ApiError, ApiFootball, odds_rows
from .config import FutbolConfig, load_config, parse_competitions
from .datos import all_fixtures, find_fixture, load_appearances, load_goal_events, sync
from .modelo import LABEL, MARKETS, ShotModel, validate
from .noticias import SpanishKeywords, player_news


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def api_from(cfg: FutbolConfig) -> ApiFootball:
    try:
        return ApiFootball(cfg.api_key, cfg.base_url, cfg.data_dir / "cache", cfg.min_interval_s)
    except ApiError as exc:
        sys.exit(str(exc))


def comps(a, cfg: FutbolConfig):
    return parse_competitions(a.competencias) if getattr(a, "competencias", None) else cfg.competitions


def when(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


# -- comandos -------------------------------------------------------------------------------
def cmd_estado(a, cfg):
    st = api_from(cfg).status()
    sub, req = st.get("subscription") or {}, st.get("requests") or {}
    print(f"plan {sub.get('plan')} · vence {sub.get('end')} · pedidos hoy {req.get('current')}/{req.get('limit_day')}")


def cmd_ligas(a, cfg):
    for item in api_from(cfg).leagues(a.pais):
        lg, seasons = item["league"], item.get("seasons") or []
        last = seasons[-1] if seasons else {}
        cov = (last.get("coverage") or {}).get("fixtures") or {}
        print(f"{lg['id']:>5}  {lg['name']:<35} {lg['type']:<7} última {last.get('year')} · "
              f"jugadores {'sí' if cov.get('statistics_players') else 'no'} · "
              f"cuotas {'sí' if (last.get('coverage') or {}).get('odds') else 'no'}")


def cmd_sync(a, cfg):
    api = api_from(cfg)
    kinds = ("players", "events") if a.eventos else ("players",)
    for league, season in comps(a, cfg):
        left = a.max_pedidos - api.http.requests
        if left <= 1:
            break
        say(f"competencia {league}, temporada {season}:")
        try:
            r = sync(api, league, season, cfg.data_dir, max_calls=left, kinds=kinds, progress=say)
        except ApiError as exc:
            sys.exit(f"{exc}\nSi dice que el plan no tiene acceso a la temporada, usá FUTBOL_COMPETENCIAS con 2022-2024 "
                     "o pasá a un plan pago.")
        if r["stopped"]:
            say(f"se cortó: {r['stopped']} (seguí mañana: no se repite lo ya bajado)")
            break


def cmd_validar(a, cfg):
    rows = load_appearances(cfg.data_dir, comps(a, cfg))
    if not rows:
        sys.exit("No hay datos: corré primero python3 -m futbol sync")
    n_fix = len({r["fixture"] for r in rows})
    say(f"{n_fix} partidos, {len(rows)} apariciones de jugadores")
    res = validate(rows)
    if "error" in res:
        sys.exit(res["error"])
    disp = {k: ("Poisson" if v is None else f"binomial negativa r={v:g}") for k, v in res["dispersion"].items()}
    print(f"Validación sin mirar el futuro: dispersión elegida con {res['n_train']} predicciones; prueba con "
          f"{res['n_test']} titulares ({when(res['from_ts'])[:10]} → {when(res['to_ts'])[:10]}). {disp}\n")
    print(f"{'mercado':<26} {'ocurre':>7} {'Brier modelo':>13} {'Brier a ojo':>12} {'mejora':>7}")
    for stat, k in MARKETS:
        m = res["test"][f"{stat}_{k}"]
        gain = 1 - m["brier_model"] / m["brier_base"] if m["brier_base"] else 0
        print(f"{k}+ {LABEL[stat]:<23} {pct(m['rate']):>7} {m['brier_model']:>13.4f} {m['brier_base']:>12.4f} {gain:>+7.1%}")
    print("\nCalibración de '1+ remates al arco' (si el modelo dice 40 %, ¿pasa el 40 % de las veces?):")
    for c in res["test"]["sot_1"]["calibration"]:
        print(f"  dice {c['pred']:.0%}  →  pasó {c['real']:.0%}   (n={c['n']})")


def fitted_model(cfg, competitions, before_ts: int | None = None) -> ShotModel:
    rows = load_appearances(cfg.data_dir, competitions)
    if before_ts:
        rows = [r for r in rows if r["ts"] < before_ts]
    if not rows:
        sys.exit("No hay datos: corré primero python3 -m futbol sync")
    res = validate(rows) if len(rows) > 3000 else {}
    model = ShotModel(dispersion=res.get("dispersion"))
    return model.fit(rows)


def cmd_remates(a, cfg):
    rows = load_appearances(cfg.data_dir, comps(a, cfg))
    if not rows:
        sys.exit("No hay datos: corré primero python3 -m futbol sync")
    model = ShotModel().fit(rows)
    teams: dict = {}
    for fid, frs in groupby(rows, key=lambda r: r["fixture"]):
        frs = list(frs)
        for team, trs in groupby(sorted(frs, key=lambda r: r["team"]), key=lambda r: r["team"]):
            trs = list(trs)
            t = teams.setdefault(team, {"name": trs[0]["team_name"], "n": 0, "shots": 0, "sot": 0, "c_shots": 0, "c_sot": 0})
            t["n"] += 1
            t["shots"] += sum(r["shots"] for r in trs)
            t["sot"] += sum(r["sot"] for r in trs)
            others = [r for r in frs if r["team"] != team]
            t["c_shots"] += sum(r["shots"] for r in others)
            t["c_sot"] += sum(r["sot"] for r in others)
    print(f"{'equipo':<26} {'PJ':>3} {'remates':>8} {'al arco':>8} {'concede':>8} {'al arco':>8}   (por partido)")
    for t in sorted(teams.values(), key=lambda t: -t["sot"] / t["n"]):
        if a.equipo and a.equipo.lower() not in t["name"].lower():
            continue
        print(f"{t['name'][:26]:<26} {t['n']:>3} {t['shots']/t['n']:>8.1f} {t['sot']/t['n']:>8.1f} "
              f"{t['c_shots']/t['n']:>8.1f} {t['c_sot']/t['n']:>8.1f}")
    print(f"\nJugadores con más remates al arco por 90 minutos (mínimo {a.min_minutos} minutos):")
    stats: dict = {}
    for r in rows:
        s = stats.setdefault(r["player"], {"name": r["name"], "team": r["team_name"], "pos": r["pos"], "min": 0,
                                           "shots": 0, "sot": 0, "starts": 0, "sot1": 0})
        s.update(team=r["team_name"])
        s["min"] += r["minutes"]
        s["shots"] += r["shots"]
        s["sot"] += r["sot"]
        if r["started"]:
            s["starts"] += 1
            s["sot1"] += r["sot"] >= 1
    best = [s for s in stats.values() if s["min"] >= a.min_minutos and (not a.equipo or a.equipo.lower() in s["team"].lower())]
    best.sort(key=lambda s: -s["sot"] / s["min"])
    print(f"  {'jugador':<24} {'equipo':<20} {'min':>5} {'rem/90':>7} {'arco/90':>8} {'titular con 1+ al arco':>23}")
    for s in best[:a.top]:
        print(f"  {s['name'][:24]:<24} {s['team'][:20]:<20} {s['min']:>5.0f} {s['shots']/s['min']*90:>7.2f} "
              f"{s['sot']/s['min']*90:>8.2f} {pct(s['sot1']/s['starts'] if s['starts'] else None):>23}")


def cmd_partido(a, cfg):
    competitions = comps(a, cfg)
    f = find_fixture(cfg.data_dir, competitions, a.fixture)
    if not f:
        sys.exit("No encontré ese partido en los fixtures bajados (python3 -m futbol sync baja el calendario).")
    ts = f["fixture"]["timestamp"]
    model = fitted_model(cfg, competitions, before_ts=ts)  # solo lo anterior al partido
    home, away = f["teams"]["home"], f["teams"]["away"]
    api = api_from(cfg) if a.api else None
    lineups = {}
    if api:
        try:
            for team in api.lineups(a.fixture):
                lineups[team["team"]["id"]] = [{"player": p["player"]["id"], "name": p["player"]["name"],
                                                "pos": p["player"].get("pos")} for p in team.get("startXI") or []]
        except ApiError as exc:
            say(f"formaciones: {exc}")
    tables = {}
    for side, other, is_home in ((home, away, True), (away, home, False)):
        players = lineups.get(side["id"])
        tables[side["id"]] = [{**r, "team_name": side["name"]} for r in
                              model.player_table(side["id"], other["id"], is_home, players)]
    everyone = tables[home["id"]] + tables[away["id"]]
    print(f"{home['name']} vs {away['name']} · {when(ts)} · "
          f"{'formaciones oficiales' if lineups else 'titulares probables (sin formación oficial)'}\n")
    for side in (home, away):
        print(f"{side['name']}:")
        print(f"  {'jugador':<24} {'pos':>3} {'min':>4} {'remates':>8} {'1+ arco':>8} {'2+ arco':>8} {'2+ rem':>7} {'3+ rem':>7}")
        for r in tables[side["id"]]:
            print(f"  {str(r['name'])[:24]:<24} {r['pos'] or '':>3} {r['minutes']:>4} {r['lam_shots']:>8.2f} "
                  f"{pct(r['p_sot_1']):>8} {pct(r['p_sot_2']):>8} {pct(r['p_shots_2']):>7} {pct(r['p_shots_3']):>7}")
        print()
    odds, other = [], []
    if api:
        try:
            bm = api.bookmaker_id(cfg.bookmaker) or 8
            found, other = valor.api_player_odds(odds_rows(api.odds(a.fixture, bm)), everyone)
            odds += found
            say(f"cuotas de {cfg.bookmaker} por la API: {len(found)} de remates de jugadores, {len(other)} de otros mercados")
        except ApiError as exc:
            say(f"cuotas por la API: {exc}")
    manual, problems = valor.manual_odds(cfg.data_dir / "cuotas.csv", a.fixture, everyone)
    odds += manual
    for p in problems:
        say(f"cuotas.csv: {p}")
    if not odds:
        print("Sin cuotas de remates para comparar. Cargalas en data/futbol/cuotas.csv "
              "(fixture,jugador,mercado,linea,cuota) o probá con --api.")
        return
    bets = valor.value_bets(odds, everyone, cfg.bankroll, cfg.min_edge, cfg.max_stake_pct)
    print(f"{'jugador':<24} {'mercado':<20} {'cuota':>6} {'justa':>6} {'prob.':>6} {'valor':>7} {'monto':>7}")
    for b in bets:
        print(f"{b['name'][:24]:<24} {str(b['k']) + '+ ' + LABEL[b['stat']]:<20} {b['odd']:>6.2f} "
              f"{b['fair_odd']:>6.2f} {b['p']:>6.0%} {b['ev']:>+7.1%} {b['stake']:>7.2f}")
    if a.anotar:
        n = valor.journal_add(cfg.data_dir / "papel.jsonl", a.fixture, bets)
        say(f"{n} apuesta(s) anotadas en papel (data/futbol/papel.jsonl)")


def cmd_minutos(a, cfg):
    matches = load_goal_events(cfg.data_dir, comps(a, cfg))
    if not matches:
        sys.exit("No hay eventos de partidos: corré python3 -m futbol sync --eventos")
    if a.minuto is not None and a.resultado and a.cuota:
        h, _, w = a.resultado.partition("-")
        r = minutos.live_value(matches, a.minuto, int(h), int(w), a.cuota)
        lo, hi = r["ci95"]
        print(f"Desde el minuto {a.minuto} con {a.resultado} ({r['state']}, {r['n']} partidos): otro gol en el "
              f"{r['p']:.0%} (IC 95 % {lo:.0%}–{hi:.0%}) · cuota justa {r['fair_odd']:.2f} · "
              f"tu cuota {a.cuota:.2f} → valor {r['ev']:+.1%} (en el peor caso del intervalo {r['ev_low']:+.1%})")
        return
    print(f"{len(matches)} partidos · goles por partido "
          f"{sum(len(m['goals']) for m in matches) / len(matches):.2f}\n")
    for p in minutos.goals_by_period(matches):
        print(f"  {p['tramo']:>6}: {p['share']:5.1%} de los goles")
    print(f"\n{'desde':>6} {'resultado':<24} {'partidos':>8} {'otro gol':>9} {'cuota justa':>12}")
    for r in minutos.table(matches):
        print(f"{r['minute']:>6} {r['state']:<24} {r['n']:>8} {pct(r['p']):>9} "
              f"{(r['fair_odd'] or 0):>12.2f}")


def cmd_noticias(a, cfg):
    competitions = comps(a, cfg)
    f = find_fixture(cfg.data_dir, competitions, a.partido)
    if not f:
        sys.exit("No encontré ese partido en los fixtures bajados.")
    model = fitted_model(cfg, competitions, before_ts=f["fixture"]["timestamp"])
    players = []
    for side in (f["teams"]["home"], f["teams"]["away"]):
        players += [{**p, "team_name": side["name"]} for p in model.likely_starters(side["id"])]
    headlines = []
    for url in a.rss:
        try:
            headlines += parse_feed(fetch_feed(url), source=url)
        except Exception as exc:
            say(f"no pude leer {url}: {exc}")
    client = make_client(cfg.jev, cfg.data_dir / "jev_cache.jsonl")
    if isinstance(client, MockJev):
        say("Sin TYPESAFE_API_KEY: se usan palabras clave en castellano, NO Jev.")
        client = SpanishKeywords()
    rows = player_news(client, headlines, players)
    if not rows:
        print(f"Ningún titular de los {len(headlines)} leídos nombra a los titulares probables.")
    for r in rows:
        print(f"[{r['status']:>7} {r['confidence']:.2f}] {r['name']}: {r['headline']}  ({r['judge']})")


def parse_score(text: str) -> tuple[int, tuple]:
    """'1490520:2-1' o '1490520:2-1:1-0' (con entretiempo) -> (partido, (local, visitante[, (et_l, et_v)]))."""
    fid, _, rest = text.partition(":")
    parts = rest.split(":")
    ft = tuple(int(x) for x in parts[0].split("-"))
    ht = tuple(int(x) for x in parts[1].split("-")) if len(parts) > 1 else None
    return int(fid), (ft[0], ft[1], ht)


def cmd_papel(a, cfg):
    rows = load_appearances(cfg.data_dir, comps(a, cfg))
    scores = dict(parse_score(t) for t in (a.resultado or []))
    s = valor.journal_settle(cfg.data_dir / "papel.jsonl", rows, cfg.bankroll, scores)
    if not s.get("bets"):
        print("El diario en papel está vacío: usá python3 -m futbol partido <id> --anotar")
        return
    print(f"apuestas {s['bets']} · liquidadas {s['settled']} · ganadas {s['won']} · pendientes {s['pending']}")
    if s["settled"]:
        print(f"apostado {s['staked']:.2f} USD · resultado {s['pnl']:+.2f} USD · ROI {s['roi']:+.1%} · "
              f"capital {cfg.bankroll:.0f} → {s['bankroll']:.2f} USD · aciertos esperados {s['expected_win_rate']:.0%}")


def cmd_cuotas(a, cfg):
    api = api_from(cfg)
    min_edge = cfg.min_edge if a.min_valor is None else a.min_valor
    targets = [{"fixture": f} for f in a.partido or []]
    if a.fecha:
        try:
            targets += cq.league_fixtures_for_date(api, a.fecha, a.liga, max_pages=min(40, a.max_pedidos))
        except ApiError as exc:
            sys.exit(str(exc))
        if not targets:
            sys.exit(f"No encontré partidos de la liga {a.liga} con cuotas el {a.fecha}.")
    if not targets:
        sys.exit("Indicá --partido ID o --fecha AAAA-MM-DD")
    for t in targets:
        if api.http.requests >= a.max_pedidos:
            say(f"Llegué al tope de {a.max_pedidos} pedidos; seguí con --partido para los que faltan.")
            break
        try:
            resp = api.fixture_odds(t["fixture"])
        except ApiError as exc:
            say(f"partido {t['fixture']}: {exc}")
            continue
        if not resp:
            print(f"partido {t['fixture']}: sin cuotas todavía")
            continue
        item = resp[0]
        info = cq.summary(item)
        title = f"{t.get('home')} vs {t.get('away')}" if t.get("home") else f"partido {info['fixture']}"
        print(f"\n{title} · {info['league']} · {info['date']} · casas: {', '.join(info['books'])}")
        tv = cq.team_value(item, min_edge=min_edge)
        for r in tv:
            r["stake"] = valor.stake(r["p"], r["odd"], cfg.bankroll, cap=cfg.max_stake_pct)
        if tv:
            print(f"  bet365 paga más que lo justo según Pinnacle (valor ≥ {min_edge:.0%}):")
            for r in tv:
                print(f"    {r['market']:<28} {r['selection']:<11} bet365 {r['odd']:>5.2f}  justa {r['fair_odd']:>5.2f}  "
                      f"valor {r['ev']:+5.1%}  monto {r['stake']:.2f} USD")
        elif "Pinnacle" not in info["books"]:
            print("  Pinnacle no tiene cuotas de este partido: no hay referencia para comparar.")
        else:
            print(f"  Ningún mercado de bet365 supera a Pinnacle por {min_edge:.0%} o más.")
        players = cq.bet365_players(item)
        flags = cq.coherence_flags(players)
        for f in flags:
            print(f"  ¡Incoherencia! {f['player']}: '{f['should_be_less_likely']}' a {f['odd']:.2f} paga menos que "
                  f"'{f['than']}' a {f['than_odd']:.2f}, y debería pagar más.")
        if players and a.jugadores:
            ranked = sorted(players.items(), key=lambda kv: kv[1]["sot"].get(1) or 99)[:a.jugadores]
            print(f"  Jugadores según bet365 (cuota; entre paréntesis, probabilidad implícita con margen):")
            for name, p in ranked:
                cells = []
                for label, odd in (("1+ rem", p["shots"].get(1)), ("2+ rem", p["shots"].get(2)),
                                   ("1+ arco", p["sot"].get(1)), ("gol", p["goal"])):
                    cells.append(f"{label} {odd:.2f} ({1 / odd:.0%})" if odd else f"{label} –")
                print(f"    {name[:24]:<24} " + " · ".join(cells))
        if a.anotar and tv:
            n = valor.journal_add_team(cfg.data_dir / "papel.jsonl", info["fixture"], tv, title)
            say(f"  {n} apuesta(s) anotadas en papel")
    say(f"pedidos usados: {api.http.requests}")


def cmd_proximos(a, cfg):
    fx = [f for f in all_fixtures(cfg.data_dir, comps(a, cfg)) if f["fixture"]["status"]["short"] not in FINISHED]
    if not fx:
        print("No hay partidos por jugar en las competencias bajadas (con el plan gratis, solo hay 2022-2024).")
    for f in fx[:a.top]:
        print(f"{f['fixture']['id']:>9}  {when(f['fixture']['timestamp'])}  {f['teams']['home']['name']} vs "
              f"{f['teams']['away']['name']}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="futbol", description="Analista de fútbol argentino (solo análisis).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado", help="plan y pedidos usados hoy")
    s = sub.add_parser("ligas", help="competencias de un país y su cobertura")
    s.add_argument("--pais", default="Argentina")
    s = sub.add_parser("sync", help="baja estadísticas de partidos terminados (respeta el cupo)")
    s.add_argument("--competencias", help="p. ej. 1032:2024,128:2024")
    s.add_argument("--max-pedidos", type=int, default=95)
    s.add_argument("--eventos", action="store_true", help="también goles y tarjetas por minuto")
    for name, help_ in (("validar", "¿el modelo de remates acierta?"), ("papel", "liquida y resume el diario en papel")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--competencias")
        if name == "papel":
            s.add_argument("--resultado", action="append",
                           help="resultado de un partido para liquidar mercados de equipo: ID:2-1 o ID:2-1:1-0")
    s = sub.add_parser("remates", help="ritmo de remates por equipo y jugador")
    s.add_argument("--competencias")
    s.add_argument("--equipo")
    s.add_argument("--top", type=int, default=25)
    s.add_argument("--min-minutos", type=int, default=600)
    s = sub.add_parser("proximos", help="partidos por jugar en lo bajado")
    s.add_argument("--competencias")
    s.add_argument("--top", type=int, default=20)
    s = sub.add_parser("partido", help="probabilidades por jugador, cuotas y valor")
    s.add_argument("fixture", type=int)
    s.add_argument("--competencias")
    s.add_argument("--api", action="store_true", help="pedir formaciones y cuotas de bet365 a la API (2 pedidos)")
    s.add_argument("--anotar", action="store_true", help="anotar las apuestas con valor en el diario en papel")
    s = sub.add_parser("minutos", help="probabilidad de otro gol según minuto y resultado")
    s.add_argument("--competencias")
    s.add_argument("--minuto", type=int)
    s.add_argument("--resultado", help="p. ej. 1-0 (local-visitante)")
    s.add_argument("--cuota", type=float, help="cuota en vivo de 'habrá otro gol'")
    s = sub.add_parser("cuotas", help="cuotas actuales de bet365 contra Pinnacle e incoherencias (plan gratis)")
    s.add_argument("--partido", type=int, action="append", help="ID de partido (repetible)")
    s.add_argument("--fecha", help="AAAA-MM-DD: busca los partidos de la liga en esa fecha")
    s.add_argument("--liga", type=int, default=128)
    s.add_argument("--max-pedidos", type=int, default=60)
    s.add_argument("--min-valor", type=float, help="valor mínimo para mostrar (por defecto FUTBOL_MIN_VALOR)")
    s.add_argument("--jugadores", type=int, default=8, help="jugadores a mostrar por partido (0 = ninguno)")
    s.add_argument("--anotar", action="store_true", help="anotar en papel lo que tenga valor")
    s = sub.add_parser("noticias", help="Jev: ¿algún titular dice que un jugador no juega?")
    s.add_argument("--partido", type=int, required=True)
    s.add_argument("--rss", action="append", required=True)
    s.add_argument("--competencias")
    return ap


COMMANDS = {"estado": cmd_estado, "ligas": cmd_ligas, "sync": cmd_sync, "validar": cmd_validar, "remates": cmd_remates,
            "partido": cmd_partido, "minutos": cmd_minutos, "noticias": cmd_noticias, "papel": cmd_papel,
            "proximos": cmd_proximos, "cuotas": cmd_cuotas}


def main(argv: list[str] | None = None, cfg: FutbolConfig | None = None) -> None:
    a = build_parser().parse_args(argv)
    COMMANDS[a.cmd](a, cfg or load_config())


if __name__ == "__main__":
    main()

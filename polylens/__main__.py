"""Línea de comandos de Polylens. Ejemplos:

    python3 -m polylens scan --period month --top 100        # ranking por consistencia
    python3 -m polylens trader 0xABC...                       # perfil de una billetera
    python3 -m polylens flows                                 # dónde están hoy los que pasaron el filtro
    python3 -m polylens study --top 5                         # ¿se los puede copiar con demora?
    python3 -m polylens news --rss https://.../feed.xml       # titulares que tocan esas apuestas (Jev)
    python3 -m polylens report --out reports/polylens.html    # informe HTML con todo lo anterior
    python3 -m polylens ping                                  # prueba la API de Jev

Solo lee datos públicos. No opera ni maneja billeteras.
"""
from __future__ import annotations

import argparse
import sys
import time

from . import store
from .categories import Categorizer
from .config import Settings, load_settings
from .flows import smart_flows
from .http import Http
from .jev_client import JevError, MockJev, make_client, noul
from .news import news_scan
from .polymarket import Polymarket
from .profiles import build_profile, position_result
from .report import render, write
from .scan import scan
from .study import copy_study


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def polymarket(settings: Settings) -> Polymarket:
    http = Http(settings.data_dir / "cache", ttl_s=settings.cache_ttl_s, min_interval_s=settings.min_interval_s)
    return Polymarket(http)


def jev(settings: Settings, wanted: bool = True):
    """Jev real si se pidió y hay API key; si no, la heurística local (avisando)."""
    if not wanted:
        return MockJev()
    client = make_client(settings.jev, settings.data_dir / "jev_cache.jsonl")
    if isinstance(client, MockJev):
        say("Aviso: sin TYPESAFE_API_KEY (o con JEV_MOCK=1) se usa MockJev, una heurística local que NO es Jev.")
    return client


def need(kind: str, ref: str, settings: Settings) -> dict:
    data = store.load(kind, ref, settings.data_dir)
    if data is None:
        hint = {"scans": "scan", "flows": "flows"}.get(kind, kind)
        sys.exit(f"No encontré {kind}/{ref}. Corré primero: python3 -m polylens {hint}")
    return data


def cmd_scan(a, settings: Settings) -> None:
    pm = polymarket(settings)
    cat = Categorizer(jev(settings, a.jev), max_calls=a.jev_max if a.jev else None)
    t = time.time()
    res = scan(pm, a.period, a.category, a.top, a.days, categorizer=cat, min_positions=a.min_positions, progress=say)
    path = store.save("scans", res, settings.data_dir, f"{a.period}-{a.category}")
    say(f"listo en {time.time() - t:.0f} s ({pm.http.requests} pedidos, {pm.http.cache_hits} desde caché) → {path}")
    if a.jev:
        say(f"categorías: {cat.calls} preguntas a {cat.name}, {cat.errors} errores")
    th = res["meta"]["thresholds"]
    print(f"\nUmbrales para {res['meta']['analyzed']} traders: azar t≈{th['azar']:.2f} · sólido t≥{th['solido']:.2f}\n")
    print(f"{'trader':<22} {'veredicto':<30} {'pos':>5} {'acierto':>8} {'ROI':>8} {'t':>6}  alertas")
    for p in res["profiles"][:a.show]:
        print(f"{(p['name'] or p['user'][:10])[:22]:<22} {p['significance']:<30} {p['n']:>5} {p['win_rate']:>8.0%} "
              f"{p['roi']:>+8.1%} {p['t_stat']:>6.2f}  {len(p['flags'])}")


def cmd_trader(a, settings: Settings) -> None:
    pm = polymarket(settings)
    since = int(time.time() - a.days * 86_400)
    positions, floor = pm.resolved_positions(a.wallet, since)
    stats = pm.user_stats(a.wallet)
    cat = Categorizer(jev(settings, a.jev), max_calls=a.jev_max if a.jev else None)
    prof = build_profile(a.wallet, positions, stats, None, cat)
    print(f"Billetera {a.wallet}")
    print(f"  posiciones con resultado: {prof.n}   aciertos: {prof.win_rate:.0%}   ROI: {prof.roi:+.1%}   "
          f"t: {prof.t_stat:.2f}   ganancia: {prof.total_pnl:,.0f} USD")
    print(f"  casi seguros: {prof.share_favorites:.0%}   batacazos: {prof.share_longshots:.0%}   "
          f"operaciones/día: {prof.trades_per_day:.0f}")
    print("  lectura de t (si lo elegiste SIN mirar un ranking): t ≥ 2 es difícil que sea solo suerte; si salió de un "
          "ranking, usá el umbral del escaneo.")
    for f in prof.flags:
        print(f"  ! {f}")
    if prof.categories:
        print("  categorías: " + "; ".join(f"{c} {v['n']} pos. ROI {v['roi']:+.1%}" for c, v in prof.categories.items()))
    rows = sorted((r for r in (position_result(p) for p in positions) if r), key=lambda r: r.pnl)
    for label, chosen in (("mejores", rows[::-1][:5]), ("peores", rows[:5])):
        print(f"  {label}:")
        for r in chosen:
            print(f"    {r.pnl:>+12,.0f} USD  a {r.avg_price:.2f}  {r.title[:70]} → {r.outcome}")
    opened = pm.positions(a.wallet, "OPEN", limit=200, sort_by="CURRENT_VALUE")
    if opened:
        print("  abiertas (por valor):")
        for p in opened[:10]:
            print(f"    {float(p.get('current_value') or 0):>12,.0f} USD  precio {float(p.get('current_price') or 0):.2f}"
                  f"  {(p.get('title') or '')[:70]} → {p.get('outcome')}")


def cmd_flows(a, settings: Settings) -> None:
    sc = need("scans", a.scan, settings)
    res = smart_flows(polymarket(settings), sc["profiles"], a.top, a.include_all, a.min_value, progress=say)
    if not res["traders"]:
        say("Ningún trader pasó el filtro estadístico en ese escaneo; probá con --include-all (sin filtro).")
    path = store.save("flows", res, settings.data_dir)
    say(f"→ {path}")
    for m in res["markets"][:a.show]:
        names = ", ".join(t["name"] for t in m["traders"][:3])
        print(f"{m['n']} trader(s) {m['value']:>12,.0f} USD  precio {m['current_price']:.2f}  "
              f"{'[en disputa] ' if m['disputed'] else ''}{m['title'][:60]} → {m['outcome']}  ({names})")


def cmd_study(a, settings: Settings) -> None:
    sc = need("scans", a.scan, settings)
    res = copy_study(polymarket(settings), sc["profiles"], a.top, a.sample, a.days, a.min_usd,
                     include_all=a.include_all, slippage=a.slippage, progress=say)
    path = store.save("studies", res, settings.data_dir)
    say(f"→ {path}")
    for t in res["traders"] + [{"name": "TODOS JUNTOS", "summary": res["pooled"]}]:
        s = t["summary"]
        cells = "  ".join(f"{d}s:{v['mean']:+.1%}(n={v['n']})" for d, v in s["by_delay"].items())
        print(f"{(t['name'] or '')[:20]:<20} {s['n']:>4} compras  {cells}  → {s['verdict']}")


def cmd_news(a, settings: Settings) -> None:
    fl = store.load("flows", a.flows, settings.data_dir)
    if fl is None:
        sc = need("scans", "latest", settings)
        fl = smart_flows(polymarket(settings), sc["profiles"], progress=say)
    client = jev(settings, not a.no_jev)
    res = news_scan(client, a.rss, fl["markets"], max_pairs=a.max_pairs, min_relevance=a.min_relevance, progress=say)
    path = store.save("news", res, settings.data_dir)
    say(f"→ {path}  (juez: {res['meta']['judge']})")
    for r in res["matches"][:a.show]:
        print(f"[{r['relevance']:.2f} {r['favors']}] {r['headline']['title'][:80]}\n"
              f"      → {r['market']['title'][:70]} → {r['market']['outcome']}")


def cmd_report(a, settings: Settings) -> None:
    d = settings.data_dir
    html_text = render(store.load("scans", a.scan, d), store.load("flows", "latest", d),
                       store.load("studies", "latest", d), store.load("news", "latest", d))
    say(f"informe → {write(a.out, html_text)}")


def cmd_ping(a, settings: Settings) -> None:
    client = jev(settings)
    try:
        r = client.decide("This is a connectivity test.", {"ok": noul("Is this message a test?")})
    except JevError as exc:
        sys.exit(f"Jev respondió con error: {exc}")
    print(f"{r.model}: p(sí)={r.answers['ok'].p:.2f} en {r.latency_ms:.0f} ms")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="polylens", description="Análisis de traders y mercados de Polymarket (solo lectura).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="ranking de Polymarket reordenado por consistencia")
    s.add_argument("--period", default="month", choices=["day", "week", "month", "all"])
    s.add_argument("--category", default="overall", help="overall, politics, sports, crypto, ...")
    s.add_argument("--top", type=int, default=100, help="cuántos del ranking analizar")
    s.add_argument("--days", type=int, default=90, help="ventana de posiciones con resultado")
    s.add_argument("--min-positions", type=int, default=20)
    s.add_argument("--jev", action="store_true", help="categorizar mercados con Jev (si no, palabras clave)")
    s.add_argument("--jev-max", type=int, default=300, help="tope de preguntas a Jev (el resto por palabras clave)")
    s.add_argument("--show", type=int, default=25)

    t = sub.add_parser("trader", help="perfil de una billetera")
    t.add_argument("wallet")
    t.add_argument("--days", type=int, default=90)
    t.add_argument("--jev", action="store_true")
    t.add_argument("--jev-max", type=int, default=100)

    f = sub.add_parser("flows", help="posiciones abiertas de los traders que pasaron el filtro")
    f.add_argument("--scan", default="latest")
    f.add_argument("--top", type=int, default=20)
    f.add_argument("--include-all", action="store_true", help="no filtrar por veredicto")
    f.add_argument("--min-value", type=float, default=50.0)
    f.add_argument("--show", type=int, default=25)

    st = sub.add_parser("study", help="¿se los puede copiar con demora?")
    st.add_argument("--scan", default="latest")
    st.add_argument("--top", type=int, default=10)
    st.add_argument("--sample", type=int, default=60, help="compras por trader")
    st.add_argument("--days", type=int, default=30)
    st.add_argument("--min-usd", type=float, default=100.0)
    st.add_argument("--slippage", type=float, default=0.01)
    st.add_argument("--include-all", action="store_true")

    n = sub.add_parser("news", help="titulares que tocan los mercados de los traders seguidos")
    n.add_argument("--rss", action="append", required=True, help="URL de un feed RSS/Atom (repetible)")
    n.add_argument("--flows", default="latest")
    n.add_argument("--max-pairs", type=int, default=40, help="tope de pares titular–mercado para Jev")
    n.add_argument("--min-relevance", type=float, default=0.5)
    n.add_argument("--no-jev", action="store_true", help="usar la heurística local en vez de Jev")
    n.add_argument("--show", type=int, default=20)

    r = sub.add_parser("report", help="informe HTML con lo último guardado")
    r.add_argument("--scan", default="latest")
    r.add_argument("--out", default="reports/polylens.html")

    sub.add_parser("ping", help="prueba la API de Jev")
    return ap


COMMANDS = {"scan": cmd_scan, "trader": cmd_trader, "flows": cmd_flows, "study": cmd_study, "news": cmd_news,
            "report": cmd_report, "ping": cmd_ping}


def main(argv: list[str] | None = None, settings: Settings | None = None) -> None:
    a = build_parser().parse_args(argv)
    COMMANDS[a.cmd](a, settings or load_settings())


if __name__ == "__main__":
    main()

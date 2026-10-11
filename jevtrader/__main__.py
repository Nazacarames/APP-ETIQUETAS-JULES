"""CLI: python -m jevtrader <comando>

    fetch     descarga velas de Binance a CSV
    backtest  compara comprar-y-mantener vs. estrategia base vs. estrategia + Jev
    paper     opera en papel sobre datos reales (una vela por corrida con --once)
    binance   opera en Binance Spot (Demo Mode por defecto; --check prueba la conexión)
    news      clasifica titulares con Jev
    ping      llamada de prueba a la API de Jev
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .backtest import buy_and_hold, run_backtest, segment, veto_analysis
from .broker import PaperBroker
from .config import load_settings
from .data import BARS_PER_YEAR, fetch_binance, load_csv, save_csv, synthetic
from .jev_client import JevError, MockJev, make_client
from .journal import Journal
from .judge import JevJudge
from .risk import RiskManager

DISCLAIMER = ("Resultados simulados sobre datos históricos. No son asesoramiento financiero ni garantizan "
              "resultados futuros. Con MockJev el filtro es una heurística local, no el modelo Jev.")


def _client(settings, args):
    if getattr(args, "mock", False):
        return MockJev()
    client = make_client(settings.jev, cache_path=settings.data_dir / "jev_cache.jsonl")
    if isinstance(client, MockJev):
        print("⚠ Sin TYPESAFE_API_KEY: usando MockJev (heurística local, NO es Jev).", file=sys.stderr)
    return client


def cmd_fetch(args, settings):
    bars = fetch_binance(args.symbol, args.interval, start=args.start, end=args.end)
    out = args.out or settings.data_dir / f"{args.symbol}_{args.interval}.csv"
    save_csv(bars, out)
    print(f"{len(bars)} velas -> {out} ({bars[0].date} → {bars[-1].date})")


def cmd_backtest(args, settings):
    if args.synthetic:
        bars, symbol = synthetic(args.bars), "SINTETICO"
    elif args.csv:
        bars, symbol = load_csv(args.csv), Path(args.csv).stem
    else:
        bars, symbol = fetch_binance(args.symbol, args.interval, start=args.start, end=args.end), args.symbol
    bpy = BARS_PER_YEAR.get(args.interval, 365)
    if args.equities:
        bpy = 252
    client = _client(settings, args)
    judge = JevJudge(client, settings.gate)
    risk = RiskManager(settings.risk)
    tf = "daily" if args.interval == "1d" else args.interval

    bh = buy_and_hold(bars, settings.costs, bars_per_year=bpy)
    base = run_backtest(bars, name="Estrategia base", risk=risk, costs=settings.costs, bars_per_year=bpy, timeframe=tf)
    jev = run_backtest(bars, name="Base + filtro Jev", risk=risk, costs=settings.costs, judge=judge,
                       bars_per_year=bpy, timeframe=tf, asset=symbol)

    from .features import WARMUP
    start_i = WARMUP
    split_i = start_i + int((len(bars) - start_i) * (1 - args.holdout))
    split_ts = bars[split_i].ts
    ts_of = {k: b.ts for k, b in enumerate(bars)}
    segments = {}
    for label, a, z in (("A (desarrollo)", bars[start_i].ts, split_ts), ("B (holdout)", split_ts, None),
                        ("Total", bars[start_i].ts, None)):
        segments[label] = {r.name: segment(r, a, z, bpy, ts_of) for r in (bh, base, jev)}
    veto = veto_analysis(jev)

    model = getattr(client, "name", "?")
    est_cost = jev.jev_est_tokens / 1e6 * 0.042
    meta = {"symbol": symbol, "interval": args.interval, "start": bars[start_i].date, "end": bars[-1].date,
            "holdout_start": bars[split_i].date, "judge_model": model, "fee_bps": settings.costs.fee_bps,
            "slippage_bps": settings.costs.slippage_bps, "jev_calls": jev.jev_calls,
            "jev_est_tokens": jev.jev_est_tokens, "jev_est_cost_usd": round(est_cost, 6), "disclaimer": DISCLAIMER}

    print(f"\n{symbol} {args.interval}  {meta['start']} → {meta['end']}   juez: {model}")
    print(f"llamadas a Jev: {jev.jev_calls}  (~{jev.jev_est_tokens} tokens, ~US$ {est_cost:.4f} con Jev real)\n")
    hdr = f"{'tramo':<15}{'variante':<22}{'retorno':>9}{'CAGR':>8}{'maxDD':>8}{'sharpe':>8}{'trades':>7}{'win%':>7}"
    print(hdr)
    print("-" * len(hdr))
    for label, rows in segments.items():
        for name, m in rows.items():
            if not m:
                continue
            print(f"{label:<15}{name:<22}{m['total_return']*100:>8.1f}%{m['cagr']*100:>7.1f}%"
                  f"{m['max_drawdown']*100:>7.1f}%{m['sharpe']:>8.2f}{m['trades']:>7}{m['win_rate']*100:>6.0f}%")
    print(f"\nvetos: {veto['vetoed']}/{veto['signals']} señales · ret. medio tomadas {veto['taken_avg_ret']*100:+.2f}% "
          f"vs vetadas {veto['vetoed_avg_ret']*100:+.2f}%")

    if args.report:
        from .report import build_payload, write_report
        payload = build_payload(meta, [bh, base, jev], segments, veto, jev.decisions)
        p = write_report(args.report, payload)
        print(f"\nreporte: {p}  (+ {p.with_suffix('.json')})")


def cmd_paper(args, settings):
    from .live import run_forever, step
    broker = PaperBroker(settings.data_dir / "paper_account.json", settings.costs, args.cash)
    judge = JevJudge(_client(settings, args), settings.gate)
    journal = Journal(settings.data_dir / "journal.jsonl")
    if args.once:
        print(json.dumps(step(args.symbol, args.interval, settings, broker, judge, journal), indent=2,
                         ensure_ascii=False, default=str))
    else:
        run_forever(args.symbol, args.interval, settings, broker, judge, journal)


def cmd_binance(args, settings):
    import os
    from .binance import BinanceError, BinanceSpot, BinanceTrader, run_forever_binance, step_binance
    real = os.environ.get("BINANCE_ENV", "demo").strip().lower() == "live"
    if real and not settings.live_trading:
        sys.exit("BINANCE_ENV=live requiere también LIVE_TRADING=true en .env. No se envió nada.")
    try:
        api = BinanceSpot(os.environ.get("BINANCE_API_KEY", ""), os.environ.get("BINANCE_API_SECRET", ""),
                          live=real, live_trading_enabled=settings.live_trading)
    except ValueError as exc:
        sys.exit(f"{exc}. Crealas en demo.binance.com > API Key Management.")
    env = "REAL (dinero de verdad)" if real else "Demo Mode"
    print(f"Binance {env}: {api.base_url}", file=sys.stderr)
    if args.check:
        try:
            api.ping()
            rules = api.rules(args.symbol)
            bal = api.balances()
            can = api.can_trade()
        except BinanceError as exc:
            hint = " (Binance bloquea esta ubicación: correlo desde tu PC)" if exc.status == 451 else ""
            sys.exit(f"Falló la conexión: {exc}{hint}")
        print(f"conexión OK · permiso de trading: {'sí' if can else 'NO'}")
        print(f"{args.symbol}: base {rules.base}, cotiza en {rules.quote}, paso {rules.step}, "
              f"mínimo por orden {rules.min_notional} {rules.quote}")
        for asset in (rules.base, rules.quote):
            free, locked = bal.get(asset, (0, 0))
            print(f"  {asset}: libre {free} · bloqueado {locked}")
        return
    if args.roundtrip_test:
        from .binance import roundtrip_test
        if real:
            sys.exit("La prueba de ida y vuelta solo corre en Demo Mode.")
        res = roundtrip_test(api, args.symbol, api.price(args.symbol), settings.data_dir / "binance_roundtrip_state.json")
        Journal(settings.data_dir / "journal.jsonl").log("prueba_ida_y_vuelta", symbol=args.symbol, **res)
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        print("OK: compra, stop en Binance, cancelación y venta funcionan." if res["ok"]
              else "FALLÓ: revisá los pasos de arriba antes de seguir.")
        return
    state_file = settings.data_dir / f"binance_{'live' if real else 'demo'}_state.json"
    trader = BinanceTrader(api, state_file, args.capital)
    judge = JevJudge(_client(settings, args), settings.gate)
    journal = Journal(settings.data_dir / "journal.jsonl")
    if args.once:
        print(json.dumps(step_binance(args.symbol, args.interval, settings, trader, judge, journal),
                         indent=2, ensure_ascii=False, default=str))
    else:
        run_forever_binance(args.symbol, args.interval, settings, trader, judge, journal)


def cmd_news(args, settings):
    from .news import fetch_rss, relevant_alerts, triage
    if args.file:
        headlines = [ln.strip() for ln in Path(args.file).read_text().splitlines() if ln.strip()]
    else:
        headlines = fetch_rss(args.rss, args.limit)
    rows = triage(_client(settings, args), args.asset, headlines)
    for r in rows:
        if "error" in r:
            print(f"ERROR  {r['headline'][:80]}  {r['error']}")
            continue
        print(f"{r['sentiment']:<9}{r['sentiment_conf']:>5.2f}  sobre={r['about_asset']:.2f} material={r['material']:.2f} "
              f"{r['event']:<17}{r['headline'][:90]}")
    alerts = relevant_alerts(rows)
    print(f"\nalertas accionables: {len(alerts)}")
    for a in alerts:
        print(f"  [{a['sentiment'].upper()}] {a['headline']}")


def cmd_ping(args, settings):
    client = _client(settings, args)
    from .jev_client import choice, noul
    try:
        r = client.decide("BTC exchange reports a hot-wallet exploit; withdrawals halted.", {
            "risk": noul("This is negative news for crypto holders"),
            "kind": choice("Event type", {"other": None, "security": "Hack or exploit", "macro": "Macro news"}),
        })
    except JevError as exc:
        sys.exit(f"Jev respondió con error: {exc}")
    print(f"modelo={r.model} latencia={r.latency_ms:.0f} ms uso={r.usage}")
    for k, a in r.answers.items():
        print(f"  {k}: {a.to_dict()}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="jevtrader", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1d")
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end")
    p.add_argument("--out")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("backtest")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1d")
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end")
    p.add_argument("--csv", help="usar un CSV propio en vez de Binance")
    p.add_argument("--equities", action="store_true", help="252 velas/año (acciones) en vez de 365")
    p.add_argument("--synthetic", action="store_true", help="datos sintéticos (sin red)")
    p.add_argument("--bars", type=int, default=1500)
    p.add_argument("--holdout", type=float, default=0.3, help="fracción final reservada (no optimizar ahí)")
    p.add_argument("--mock", action="store_true", help="forzar MockJev aunque haya API key")
    p.add_argument("--report", help="ruta del reporte HTML")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("paper")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1d")
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--once", action="store_true", help="procesar la última vela y salir (para cron)")
    p.add_argument("--mock", action="store_true")
    p.set_defaults(func=cmd_paper)

    p = sub.add_parser("binance", help="Binance Spot (Demo Mode por defecto)")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1d")
    p.add_argument("--capital", type=float, default=1_000.0,
                   help="capital que el bot puede usar, en la moneda de cotización (p. ej. USDT)")
    p.add_argument("--check", action="store_true", help="probar claves, permisos y saldos sin operar")
    p.add_argument("--roundtrip-test", action="store_true",
                   help="solo Demo: compra el mínimo, verifica el stop en Binance y vende")
    p.add_argument("--once", action="store_true", help="procesar la última vela y salir")
    p.add_argument("--mock", action="store_true", help="usar MockJev como juez")
    p.set_defaults(func=cmd_binance)

    p = sub.add_parser("news")
    p.add_argument("--asset", required=True, help='p. ej. "Bitcoin (BTC)" o "Apple Inc. (AAPL)"')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--rss")
    g.add_argument("--file")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--mock", action="store_true")
    p.set_defaults(func=cmd_news)

    p = sub.add_parser("ping")
    p.add_argument("--mock", action="store_true")
    p.set_defaults(func=cmd_ping)

    args = ap.parse_args(argv)
    settings = load_settings()
    args.func(args, settings)


if __name__ == "__main__":
    main()

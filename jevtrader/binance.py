"""Conector Binance Spot. Demo Mode por defecto.

Demo Mode (demo.binance.com) usa la MISMA API que la cuenta real, con las
mismas reglas de órdenes; solo cambia el host. Las claves se crean en
demo.binance.com > API Key Management y van en .env:

    BINANCE_API_KEY=...
    BINANCE_API_SECRET=...

Para dinero real hacen falta DOS variables puestas a mano por una persona:
LIVE_TRADING=true y BINANCE_ENV=live. El agente (Claude) tiene bloqueado ese paso.

Seguridad:
- El bot solo opera la cantidad que él mismo compró (se guarda en
  data/binance_state.json). Si tenés BTC de antes, no lo toca.
- Cada compra deja un STOP_LOSS_LIMIT guardado en Binance: si tu PC se apaga,
  el stop sigue vivo en el exchange.
- Si no puede poner el stop, vende enseguida: nunca queda una posición sin stop.
- Creá la API key SOLO con permiso de trading spot. Nunca retiros.

Binance bloquea por ubicación algunas regiones (error 451). Corrélo desde tu PC.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Callable

from .broker import LiveTradingDisabled
from .config import Settings
from .data import fetch_binance
from .features import Indicators, describe, snapshot
from .journal import Journal
from .judge import JevJudge
from .risk import AccountState, RiskManager
from .strategy import DonchianTrend

DEMO_URL = "https://demo-api.binance.com"
LIVE_URL = "https://api.binance.com"
STOP_LIMIT_BUFFER = Decimal("0.005")  # el límite del stop queda 0,5 % debajo del disparo para que se ejecute


class BinanceError(RuntimeError):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        self.code = body.get("code") if isinstance(body, dict) else None
        super().__init__(f"Binance HTTP {status}: {body}")


Transport = Callable[[str, str, dict], tuple[int, Any]]


def _urllib(method: str, url: str, headers: dict) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode(errors="replace")


def _dec(x: Any) -> Decimal:
    return Decimal(str(x))


def floor_to(value: Decimal, step: Decimal) -> Decimal:
    """Redondea hacia abajo al múltiplo de step (LOT_SIZE / PRICE_FILTER)."""
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def fmt(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s if "." not in s else s.rstrip("0").rstrip(".") or "0"


@dataclass(frozen=True)
class SymbolRules:
    base: str
    quote: str
    step: Decimal
    min_qty: Decimal
    tick: Decimal
    min_notional: Decimal


class BinanceSpot:
    """Cliente REST mínimo de Binance Spot (API v3) con firma HMAC-SHA256."""

    def __init__(self, api_key: str, secret: str, *, live: bool = False, live_trading_enabled: bool = False,
                 transport: Transport = _urllib, clock: Callable[[], float] = time.time,
                 recv_window: int = 5000):
        if not api_key or not secret:
            raise ValueError("Faltan BINANCE_API_KEY / BINANCE_API_SECRET en .env")
        if live and not live_trading_enabled:
            raise LiveTradingDisabled("Dinero real bloqueado: falta LIVE_TRADING=true.")
        self.base_url = LIVE_URL if live else DEMO_URL
        self.live = live
        self.api_key = api_key
        self.secret = secret.encode()
        self.transport = transport
        self.clock = clock
        self.recv_window = recv_window
        self.time_offset_ms = 0
        self._rules: dict[str, SymbolRules] = {}

    def _call(self, method: str, path: str, params: dict | None = None, signed: bool = False,
              _retried: bool = False) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"X-MBX-APIKEY": self.api_key}
        if signed:
            clean["recvWindow"] = self.recv_window
            clean["timestamp"] = int(self.clock() * 1000) + self.time_offset_ms
        query = urllib.parse.urlencode(clean)
        if signed:
            sig = hmac.new(self.secret, query.encode(), hashlib.sha256).hexdigest()
            query = f"{query}&signature={sig}"
        url = self.base_url + path + (f"?{query}" if query else "")
        status, body = self.transport(method, url, headers)
        if status >= 300:
            err = BinanceError(status, body)
            if signed and err.code == -1021 and not _retried:
                # Reloj de la PC desfasado: se ajusta con la hora de Binance y se reintenta una vez.
                server = self._call("GET", "/api/v3/time")["serverTime"]
                self.time_offset_ms = int(server - self.clock() * 1000)
                return self._call(method, path, params, signed, _retried=True)
            raise err
        return body

    # -- lectura ---------------------------------------------------------
    def ping(self) -> None:
        self._call("GET", "/api/v3/ping")

    def rules(self, symbol: str) -> SymbolRules:
        if symbol not in self._rules:
            info = self._call("GET", "/api/v3/exchangeInfo", {"symbol": symbol})["symbols"][0]
            f = {x["filterType"]: x for x in info["filters"]}
            notional = f.get("NOTIONAL", f.get("MIN_NOTIONAL", {})).get("minNotional", "0")
            self._rules[symbol] = SymbolRules(
                base=info["baseAsset"], quote=info["quoteAsset"],
                step=_dec(f["LOT_SIZE"]["stepSize"]), min_qty=_dec(f["LOT_SIZE"]["minQty"]),
                tick=_dec(f["PRICE_FILTER"]["tickSize"]), min_notional=_dec(notional))
        return self._rules[symbol]

    def price(self, symbol: str) -> float:
        return float(self._call("GET", "/api/v3/ticker/price", {"symbol": symbol})["price"])

    def balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        acct = self._call("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)
        return {b["asset"]: (_dec(b["free"]), _dec(b["locked"])) for b in acct["balances"]}

    def can_trade(self) -> bool:
        return bool(self._call("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True).get("canTrade"))

    def order(self, symbol: str, order_id: int) -> dict:
        return self._call("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    # -- órdenes ---------------------------------------------------------
    def market_buy(self, symbol: str, qty: Decimal) -> dict:
        return self._call("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET", "quantity": fmt(qty),
            "newOrderRespType": "FULL"}, signed=True)

    def market_sell(self, symbol: str, qty: Decimal) -> dict:
        return self._call("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": fmt(qty),
            "newOrderRespType": "FULL"}, signed=True)

    def stop_loss(self, symbol: str, qty: Decimal, stop: Decimal) -> dict:
        r = self.rules(symbol)
        stop_px = floor_to(stop, r.tick)
        limit_px = floor_to(stop * (1 - STOP_LIMIT_BUFFER), r.tick)
        return self._call("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "STOP_LOSS_LIMIT", "timeInForce": "GTC",
            "quantity": fmt(qty), "stopPrice": fmt(stop_px), "price": fmt(limit_px)}, signed=True)

    def cancel(self, symbol: str, order_id: int) -> None:
        try:
            self._call("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)
        except BinanceError as exc:
            if exc.code != -2011:  # -2011: la orden ya no existe (se ejecutó o se canceló)
                raise


def _avg_price(resp: dict) -> Decimal:
    qty = _dec(resp.get("executedQty", "0"))
    return _dec(resp.get("cummulativeQuoteQty", "0")) / qty if qty > 0 else Decimal(0)


def _base_fee(resp: dict, base: str) -> Decimal:
    return sum((_dec(f["commission"]) for f in resp.get("fills", []) if f.get("commissionAsset") == base), Decimal(0))


class StateLocked(RuntimeError):
    pass


class state_lock:
    """Evita que dos procesos (p. ej. un cron que se pisa) usen el mismo archivo de estado a la vez.

    Usa un archivo .lock creado de forma exclusiva; funciona igual en Windows y Linux.
    Un lock de más de 2 horas se considera abandonado y se reemplaza.
    """

    def __init__(self, state_path: str | Path, stale_s: float = 7200):
        self.path = Path(str(state_path) + ".lock")
        self.stale_s = stale_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > self.stale_s:
            self.path.unlink(missing_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise StateLocked(f"Otro proceso del bot está usando {self.path.name}. Si no es así, borrá ese archivo.")
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


class BinanceTrader:
    """Una posición como máximo por moneda, cada una con su stop guardado en Binance.

    Con varias monedas, el capital se reparte en partes iguales ("una bolsa por moneda"),
    igual que la cartera de research/evaluate.py: cada moneda arriesga 1 % de SU parte por trade.
    Los cortes por caída y pérdida diaria miran el total. Estado local en JSON.
    """

    def __init__(self, api: BinanceSpot, state_path: str | Path, capital: float, symbols: list[str] | None = None):
        self.api = api
        self.path = Path(state_path)
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if "realized" not in self.state:  # estado de la versión de una sola moneda
                legacy = self.state.pop("realized_pnl", 0.0)
                self.state["realized"] = {"__anterior__": legacy} if legacy else {}
                self.state.setdefault("symbols", [])
            saved = self.state.get("symbols") or []
            if symbols and saved and sorted(saved) != sorted(symbols):
                raise ValueError(
                    f"El estado {self.path.name} es de las monedas {saved} y pediste {symbols}. Cambiar la lista "
                    "cambia las reglas de la prueba: usá otro archivo (--state-file) o borrá este si querés empezar de cero.")
            if symbols and not saved:
                self.state["symbols"] = list(symbols)
        else:
            self.state = {"capital": capital, "symbols": list(symbols or []), "realized": {}, "positions": {},
                          "last_bar_ts": {}, "peak_equity": capital, "halted": False}
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        tmp.replace(self.path)  # escritura atómica: un corte de luz no deja el JSON a medias

    def sleeve_capital(self) -> float:
        return self.state["capital"] / max(1, len(self.state.get("symbols") or []))

    def equity(self, symbol: str, price: float) -> float:
        """Capital de la bolsa de esta moneda + su P&L realizado + su P&L abierto."""
        eq = self.sleeve_capital() + self.state["realized"].get(symbol, 0.0)
        pos = self.state["positions"].get(symbol)
        if pos:
            eq += (price - pos["entry"]) * pos["qty"]
        return eq

    def total_equity(self, prices: dict[str, float]) -> float:
        """Capital total del bot. No mira el resto de tu cuenta de Binance."""
        eq = self.state["capital"] + sum(self.state["realized"].values())
        for sym, pos in self.state["positions"].items():
            eq += (prices.get(sym, pos["entry"]) - pos["entry"]) * pos["qty"]
        return eq

    def open(self, symbol: str, qty: float, stop: float, reason: str, ref_price: float | None = None) -> dict:
        r = self.api.rules(symbol)
        q = floor_to(_dec(qty), r.step)
        if q < r.min_qty:
            raise ValueError(f"cantidad {fmt(q)} menor al mínimo {fmt(r.min_qty)} de {symbol}")
        if ref_price and q * _dec(ref_price) < r.min_notional:
            raise ValueError(f"orden de {float(q * _dec(ref_price)):.2f} {r.quote} menor al mínimo de {symbol} "
                             f"({fmt(r.min_notional)}): el capital por moneda es demasiado chico")
        buy = self.api.market_buy(symbol, q)
        filled = _dec(buy["executedQty"]) - _base_fee(buy, r.base)
        held = floor_to(filled, r.step)
        entry = _avg_price(buy)
        try:
            so = self.api.stop_loss(symbol, held, _dec(stop))
        except BinanceError as exc:
            # Nunca dejar una posición sin stop: se vende de inmediato.
            sell = self.api.market_sell(symbol, held)
            return {"event": "abortada_sin_stop", "error": str(exc), "buy": buy, "sell": sell}
        risk_amount = float((entry - _dec(stop)) * held)
        self.state["positions"][symbol] = {"qty": float(held), "entry": float(entry), "stop": stop,
                                           "risk": risk_amount, "stop_order_id": so["orderId"], "reason": reason,
                                           "opened": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._save()
        return {"event": "entrada", "qty": float(held), "entry": float(entry), "stop": stop,
                "risk": round(risk_amount, 4), "order_id": buy.get("orderId"), "stop_order_id": so["orderId"]}

    def sync_stop(self, symbol: str) -> dict | None:
        """Si el stop se ejecutó en Binance, cierra la posición en el estado local."""
        pos = self.state["positions"].get(symbol)
        if not pos:
            return None
        o = self.api.order(symbol, pos["stop_order_id"])
        if o["status"] == "FILLED":
            px = float(_avg_price(o)) or pos["stop"]
            return self._book_exit(symbol, px, "stop (ejecutado en Binance)")
        if o["status"] in ("CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"):
            # Alguien canceló el stop a mano: se repone para no quedar sin protección.
            so = self.api.stop_loss(symbol, _dec(pos["qty"]), _dec(pos["stop"]))
            pos["stop_order_id"] = so["orderId"]
            self._save()
            return {"event": "stop_repuesto", "stop_order_id": so["orderId"]}
        return None

    def close(self, symbol: str, reason: str) -> dict:
        synced = self.sync_stop(symbol)  # el stop pudo haberse ejecutado justo antes
        if symbol not in self.state["positions"]:
            return synced
        pos = self.state["positions"][symbol]
        self.api.cancel(symbol, pos["stop_order_id"])
        r = self.api.rules(symbol)
        free = self.api.balances().get(r.base, (Decimal(0), Decimal(0)))[0]
        qty = floor_to(min(_dec(pos["qty"]), free), r.step)  # solo lo que compró el bot
        sell = self.api.market_sell(symbol, qty)
        return {**self._book_exit(symbol, float(_avg_price(sell)), reason), "order_id": sell.get("orderId")}

    def _book_exit(self, symbol: str, price: float, reason: str) -> dict:
        pos = self.state["positions"].pop(symbol)
        pnl = (price - pos["entry"]) * pos["qty"]
        self.state["realized"][symbol] = self.state["realized"].get(symbol, 0.0) + pnl
        self._save()
        out = {"event": "salida", "reason": reason, "exit": price, "pnl": round(pnl, 4)}
        if pos.get("risk"):
            out["r"] = round(pnl / pos["risk"], 3)  # resultado en R (lo usa el protocolo de Demo Mode)
        return out


def roundtrip_test(api: BinanceSpot, symbol: str, price: float, state_path: str | Path) -> dict:
    """Prueba de ejecución SOLO en Demo Mode: compra el mínimo, verifica el stop en Binance y vende.

    BTC da ~4 señales por año: esperar una para validar órdenes lleva meses. Esto prueba la
    mecánica completa (compra, stop guardado, cancelación, venta) en un minuto.
    """
    if api.live:
        raise LiveTradingDisabled("La prueba de ida y vuelta solo corre en Demo Mode.")
    r = api.rules(symbol)
    notional = max(r.min_notional * 2, Decimal("10"))
    qty = floor_to(notional / _dec(price), r.step) + r.step
    trader = BinanceTrader(api, state_path, capital=float(notional) * 4)
    steps: dict[str, Any] = {}
    for leftover in list(trader.state["positions"]):  # una prueba anterior que quedó a medias
        steps.setdefault("limpieza", []).append(trader.close(leftover, "limpieza de prueba anterior"))
    opened = trader.open(symbol, float(qty), stop=price * 0.9, reason="prueba de ida y vuelta")
    steps["compra"] = opened
    if opened["event"] != "entrada":
        return {"ok": False, "steps": steps}
    o = api.order(symbol, opened["stop_order_id"])
    steps["stop_en_binance"] = {"status": o.get("status"), "stopPrice": o.get("stopPrice")}
    closed = trader.close(symbol, "fin de la prueba")
    steps["venta"] = closed
    after = api.order(symbol, opened["stop_order_id"]).get("status")
    steps["stop_despues"] = after
    ok = (steps["stop_en_binance"]["status"] == "NEW" and closed.get("event") == "salida"
          and after in ("CANCELED", "EXPIRED") and symbol not in trader.state["positions"])
    return {"ok": ok, "steps": steps}


def step_binance_many(symbols: list[str], interval: str, settings: Settings, trader: BinanceTrader,
                      judge: JevJudge, journal: Journal, strategy: DonchianTrend | None = None,
                      bars_by_symbol: dict | None = None, fetch: Callable = fetch_binance) -> list[dict]:
    """Una vela para cada moneda. Un error en una moneda queda en el diario y no frena a las demás."""
    strategy = strategy or DonchianTrend()
    st = trader.state
    env = "live" if trader.api.live else "demo"
    results: list[dict] = []

    bars_by_symbol = dict(bars_by_symbol or {})
    for sym in symbols:
        try:
            synced = trader.sync_stop(sym)
            if synced:
                journal.log(synced["event"], symbol=sym, env=env, **{k: v for k, v in synced.items() if k != "event"})
            if sym not in bars_by_symbol:
                bars_by_symbol[sym] = fetch(sym, interval, limit=400)
        except Exception as exc:  # red, Binance o datos: se anota y se sigue con la próxima moneda
            results.append(journal.log("error", symbol=sym, env=env, error=repr(exc)))
            bars_by_symbol.pop(sym, None)

    prices = {s: b[-1].close for s, b in bars_by_symbol.items()}
    total = trader.total_equity(prices)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if st.get("day") != today:  # el límite de pérdida diaria se mide desde acá
        st["day"] = today
        st["day_start_equity"] = total
    st["peak_equity"] = max(st.get("peak_equity", total), total)

    for sym in symbols:
        if sym not in bars_by_symbol:
            continue
        try:
            out = _step_one(sym, bars_by_symbol[sym], interval, settings, trader, judge, journal, strategy, env, total)
        except Exception as exc:
            out = journal.log("error", symbol=sym, env=env, error=repr(exc))
        results.append(out)

    total = trader.total_equity({s: b[-1].close for s, b in bars_by_symbol.items()})
    st["peak_equity"] = max(st.get("peak_equity", total), total)
    trader._save()
    for out in results:
        out["equity_total"] = round(total, 2)
    return results


def _step_one(symbol, bars, interval, settings, trader, judge, journal, strategy, env, total_equity) -> dict:
    st = trader.state
    risk = RiskManager(settings.risk)
    ind = Indicators(bars)
    i = len(bars) - 1
    b = bars[i]
    if st["last_bar_ts"].get(symbol) == b.ts:
        return {"event": "sin_cambios", "symbol": symbol, "bar": b.date}
    base = {"symbol": symbol, "env": env, "bar": b.date, "close": b.close}

    if symbol in st["positions"]:
        reason = strategy.exit(ind, i)
        if reason:
            res = trader.close(symbol, reason)
            out = journal.log(res.pop("event"), **base, **res)
        else:
            out = journal.log("mantener", **base, stop=st["positions"][symbol]["stop"])
    else:
        sig = strategy.entry(ind, i)
        if not sig:
            out = journal.log("sin_senal", **base)
        else:
            # Cortes globales (caída y pérdida diaria) sobre el total; una posición por moneda.
            acct = AccountState(total_equity, max(st.get("peak_equity", total_equity), total_equity),
                                st.get("day_start_equity", total_equity), open_positions=0,
                                halted=st.get("halted", False))
            ok, why = risk.can_open(acct)
            st["halted"] = acct.halted
            if not ok:
                out = journal.log("bloqueado_por_riesgo", **base, reason=why)
            else:
                state = describe(snapshot(ind, i), "daily" if interval == "1d" else interval)
                verdict = judge.review_entry(state, asset=symbol)
                if not verdict.allow:
                    out = journal.log("vetada", **base, signal=sig.reason, state=state, **verdict.summary())
                else:
                    sleeve = trader.equity(symbol, b.close)  # el tamaño sale de la bolsa de esta moneda
                    qty = risk.position_size(sleeve, b.close, sig.stop, verdict.size_mult)
                    try:
                        res = trader.open(symbol, qty, sig.stop, sig.reason, ref_price=b.close)
                    except (BinanceError, ValueError) as exc:
                        res = {"event": "error_orden", "error": str(exc)}
                    out = journal.log(res.pop("event"), **base, signal=sig.reason, state=state,
                                      **res, **verdict.summary())

    st["last_bar_ts"][symbol] = b.ts
    out["equity_moneda"] = round(trader.equity(symbol, b.close), 2)
    return out


def step_binance(symbol: str, interval: str, settings: Settings, trader: BinanceTrader, judge: JevJudge,
                 journal: Journal, strategy: DonchianTrend | None = None, bars=None) -> dict:
    """Una vela para una sola moneda (atajo de step_binance_many)."""
    res = step_binance_many([symbol], interval, settings, trader, judge, journal, strategy,
                            bars_by_symbol={symbol: bars} if bars is not None else None)
    return res[0]


def run_forever_binance(symbols: list[str], interval: str, settings: Settings, trader: BinanceTrader,
                        judge: JevJudge, journal: Journal) -> None:
    """Corre todas las monedas 5 s después del cierre de cada vela. Ctrl+C para frenar (los stops quedan en Binance)."""
    from .data import INTERVAL_MS
    step_ms = INTERVAL_MS[interval]
    while True:
        try:
            with state_lock(trader.path):
                for out in step_binance_many(symbols, interval, settings, trader, judge, journal):
                    print(json.dumps(out, ensure_ascii=False, default=str))
        except Exception as exc:  # un error de red no tira el loop; queda en el diario
            journal.log("error", symbol=",".join(symbols), error=repr(exc))
            print("error:", exc)
        now = int(time.time() * 1000)
        wait = (step_ms - now % step_ms) / 1000 + 5
        print(f"próxima revisión: {datetime.fromtimestamp(time.time() + wait, tz=timezone.utc):%Y-%m-%d %H:%M} UTC")
        time.sleep(wait)

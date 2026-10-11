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


class BinanceTrader:
    """Opera UNA posición por símbolo con su stop en el exchange. Estado local en JSON."""

    def __init__(self, api: BinanceSpot, state_path: str | Path, capital: float):
        self.api = api
        self.path = Path(state_path)
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {"capital": capital, "realized_pnl": 0.0, "positions": {}, "last_bar_ts": {},
                          "peak_equity": capital, "halted": False}
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2))

    def equity(self, symbol: str, price: float) -> float:
        """Capital asignado al bot + P&L realizado + P&L abierto. No mira el resto de tu cuenta."""
        eq = self.state["capital"] + self.state["realized_pnl"]
        pos = self.state["positions"].get(symbol)
        if pos:
            eq += (price - pos["entry"]) * pos["qty"]
        return eq

    def open(self, symbol: str, qty: float, stop: float, reason: str) -> dict:
        r = self.api.rules(symbol)
        q = floor_to(_dec(qty), r.step)
        if q < r.min_qty:
            raise ValueError(f"cantidad {fmt(q)} menor al mínimo {fmt(r.min_qty)} de {symbol}")
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
        self.state["positions"][symbol] = {"qty": float(held), "entry": float(entry), "stop": stop,
                                           "stop_order_id": so["orderId"], "reason": reason,
                                           "opened": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._save()
        return {"event": "entrada", "qty": float(held), "entry": float(entry), "stop": stop,
                "order_id": buy.get("orderId"), "stop_order_id": so["orderId"]}

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
        self.state["realized_pnl"] += pnl
        self._save()
        return {"event": "salida", "reason": reason, "exit": price, "pnl": round(pnl, 4)}


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


def step_binance(symbol: str, interval: str, settings: Settings, trader: BinanceTrader, judge: JevJudge,
                 journal: Journal, strategy: DonchianTrend | None = None, bars=None) -> dict:
    """Una vela: sincroniza el stop, decide salida o entrada y deja todo en el diario."""
    strategy = strategy or DonchianTrend()
    risk = RiskManager(settings.risk)
    st = trader.state
    env = "live" if trader.api.live else "demo"

    synced = trader.sync_stop(symbol)
    if synced:
        journal.log(synced["event"], symbol=symbol, env=env, **{k: v for k, v in synced.items() if k != "event"})

    bars = bars if bars is not None else fetch_binance(symbol, interval, limit=400)
    ind = Indicators(bars)
    i = len(bars) - 1
    b = bars[i]
    if st["last_bar_ts"].get(symbol) == b.ts:
        return {"event": "sin_cambios", "bar": b.date, **({"sync": synced} if synced else {})}
    base = {"symbol": symbol, "env": env, "bar": b.date, "close": b.close}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if st.get("day") != today:
        st["day"] = today
        st["day_start_equity"] = trader.equity(symbol, b.close)

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
            equity = trader.equity(symbol, b.close)
            acct = AccountState(equity, max(st.get("peak_equity", equity), equity),
                                st.get("day_start_equity", equity), open_positions=len(st["positions"]),
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
                    qty = risk.position_size(equity, b.close, sig.stop, verdict.size_mult)
                    try:
                        res = trader.open(symbol, qty, sig.stop, sig.reason)
                    except (BinanceError, ValueError) as exc:
                        res = {"event": "error_orden", "error": str(exc)}
                    out = journal.log(res.pop("event"), **base, signal=sig.reason, state=state,
                                      **res, **verdict.summary())

    eq = trader.equity(symbol, b.close)
    st["peak_equity"] = max(st.get("peak_equity", eq), eq)
    st["last_bar_ts"][symbol] = b.ts
    trader._save()
    out["equity"] = round(eq, 2)
    return out


def run_forever_binance(symbol: str, interval: str, settings: Settings, trader: BinanceTrader, judge: JevJudge,
                        journal: Journal) -> None:
    """Corre step_binance 5 s después del cierre de cada vela. Ctrl+C para frenar (el stop queda en Binance)."""
    from .data import INTERVAL_MS
    step_ms = INTERVAL_MS[interval]
    while True:
        try:
            print(json.dumps(step_binance(symbol, interval, settings, trader, judge, journal),
                             ensure_ascii=False, default=str))
        except Exception as exc:  # un error de red no tira el loop; queda en el diario
            journal.log("error", symbol=symbol, error=repr(exc))
            print("error:", exc)
        now = int(time.time() * 1000)
        wait = (step_ms - now % step_ms) / 1000 + 5
        print(f"próxima revisión: {datetime.fromtimestamp(time.time() + wait, tz=timezone.utc):%Y-%m-%d %H:%M} UTC")
        time.sleep(wait)

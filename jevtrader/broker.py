"""Brokers.

- PaperBroker: simulado, persistente en un JSON local. Es el modo por defecto.
- AlpacaBroker: adaptador REST para Alpaca (acciones/cripto). Por defecto
  apunta a la cuenta PAPER. Para apuntar a dinero real hacen falta dos llaves
  a la vez: LIVE_TRADING=true en el entorno y live=True en el código. La CLI
  no expone el modo real a propósito: pasar a real es una decisión humana.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import CostConfig


class LiveTradingDisabled(RuntimeError):
    pass


@dataclass
class Fill:
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    reason: str


class PaperBroker:
    def __init__(self, path: str | Path, costs: CostConfig, initial_cash: float = 10_000.0):
        self.path = Path(path)
        self.costs = costs
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {"cash": initial_cash, "positions": {}, "fills": [], "peak_equity": initial_cash,
                          "halted": False, "last_bar_ts": {}}
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2))

    @property
    def cash(self) -> float:
        return self.state["cash"]

    def position(self, symbol: str) -> dict | None:
        return self.state["positions"].get(symbol)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(p["qty"] * prices.get(s, p["entry"]) for s, p in self.state["positions"].items())

    def buy(self, symbol: str, qty: float, price: float, stop: float, reason: str) -> Fill:
        px = price * (1 + self.costs.slippage_bps / 10_000)
        fee = qty * px * self.costs.fee_bps / 10_000
        if qty <= 0 or qty * px + fee > self.cash:
            raise ValueError("saldo insuficiente o cantidad inválida")
        self.state["cash"] -= qty * px + fee
        self.state["positions"][symbol] = {"qty": qty, "entry": px, "stop": stop}
        fill = Fill(symbol, "buy", qty, px, fee, reason)
        self.state["fills"].append(fill.__dict__)
        self._save()
        return fill

    def sell(self, symbol: str, price: float, reason: str) -> Fill:
        pos = self.state["positions"].pop(symbol)
        px = price * (1 - self.costs.slippage_bps / 10_000)
        fee = pos["qty"] * px * self.costs.fee_bps / 10_000
        self.state["cash"] += pos["qty"] * px - fee
        fill = Fill(symbol, "sell", pos["qty"], px, fee, reason)
        self.state["fills"].append(fill.__dict__)
        self._save()
        return fill

    def mark(self, key: str, value: Any) -> None:
        self.state[key] = value
        self._save()


Transport = Callable[[str, str, dict, dict | None], tuple[int, Any]]


def _urllib(method: str, url: str, headers: dict, body: dict | None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


class AlpacaBroker:
    """Adaptador REST de Alpaca (API v2). Sin probar contra una cuenta real en este repo."""

    PAPER_URL = "https://paper-api.alpaca.markets/v2"
    LIVE_URL = "https://api.alpaca.markets/v2"

    def __init__(self, key_id: str, secret: str, *, live: bool = False, live_trading_enabled: bool = False,
                 transport: Transport = _urllib):
        if live and not live_trading_enabled:
            raise LiveTradingDisabled("Dinero real bloqueado: falta LIVE_TRADING=true.")
        self.base = self.LIVE_URL if live else self.PAPER_URL
        self.headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret,
                        "Content-Type": "application/json"}
        self.transport = transport

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        status, data = self.transport(method, self.base + path, self.headers, body)
        if status >= 300:
            raise RuntimeError(f"Alpaca {method} {path} -> HTTP {status}: {data}")
        return data

    def account(self) -> dict:
        return self._call("GET", "/account")

    def position(self, symbol: str) -> dict | None:
        try:
            return self._call("GET", f"/positions/{symbol}")
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def buy_with_stop(self, symbol: str, qty: float, stop: float) -> dict:
        """Compra a mercado con un stop-loss adjunto (orden OTO)."""
        return self._call("POST", "/orders", {
            "symbol": symbol, "qty": f"{qty:.6f}", "side": "buy", "type": "market",
            "time_in_force": "day", "order_class": "oto",
            "stop_loss": {"stop_price": f"{stop:.2f}"},
        })

    def close(self, symbol: str) -> dict:
        return self._call("DELETE", f"/positions/{symbol}")

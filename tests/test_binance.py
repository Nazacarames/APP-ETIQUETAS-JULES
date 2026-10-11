import hashlib
import hmac
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from decimal import Decimal
from pathlib import Path

from jevtrader.binance import DEMO_URL, LIVE_URL, BinanceSpot, BinanceTrader, step_binance
from jevtrader.broker import LiveTradingDisabled
from jevtrader.config import GateConfig, Settings
from jevtrader.data import synthetic
from jevtrader.features import Indicators
from jevtrader.journal import Journal
from jevtrader.judge import JevJudge
from jevtrader.strategy import DonchianTrend
from tests.test_backtest import FixedJudgeClient

SECRET = "s3cr3t"


class FakeBinance:
    """Exchange simulado: valida firmas, aplica LOT_SIZE y lleva saldos y órdenes."""

    def __init__(self, price=50_000.0, btc=0.0, usdt=10_000.0, fail_stop=False):
        self.price = Decimal(str(price))
        self.bal = {"BTC": [Decimal(str(btc)), Decimal(0)], "USDT": [Decimal(str(usdt)), Decimal(0)]}
        self.orders = {}
        self.next_id = 1
        self.fail_stop = fail_stop
        self.calls = []

    def __call__(self, method, url, headers):
        parsed = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parsed.query))
        self.calls.append((method, parsed.path, q))
        if "signature" in q:
            unsigned = parsed.query.rsplit("&signature=", 1)[0]
            good = hmac.new(SECRET.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
            if q["signature"] != good or headers.get("X-MBX-APIKEY") != "key":
                return 401, {"code": -1022, "msg": "Signature for this request is not valid."}
        path = parsed.path
        if path == "/api/v3/exchangeInfo":
            return 200, {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                {"filterType": "LOT_SIZE", "minQty": "0.00001000", "stepSize": "0.00001000"},
                {"filterType": "NOTIONAL", "minNotional": "5.00000000"}]}]}
        if path == "/api/v3/ticker/price":
            return 200, {"symbol": q["symbol"], "price": str(self.price)}
        if path == "/api/v3/account":
            return 200, {"canTrade": True, "balances": [
                {"asset": a, "free": str(f), "locked": str(l)} for a, (f, l) in self.bal.items()]}
        if path == "/api/v3/order" and method == "POST":
            return self._new_order(q)
        if path == "/api/v3/order" and method == "GET":
            return 200, self.orders[int(q["orderId"])]
        if path == "/api/v3/order" and method == "DELETE":
            o = self.orders.get(int(q["orderId"]))
            if not o or o["status"] != "NEW":
                return 400, {"code": -2011, "msg": "Unknown order sent."}
            o["status"] = "CANCELED"
            qty = Decimal(o["origQty"])
            self.bal["BTC"][0] += qty
            self.bal["BTC"][1] -= qty
            return 200, o
        return 404, {"msg": "?"}

    def _new_order(self, q):
        qty = Decimal(q["quantity"])
        if (qty / Decimal("0.00001")) % 1 != 0:
            return 400, {"code": -1013, "msg": "Filter failure: LOT_SIZE"}
        oid = self.next_id
        self.next_id += 1
        if q["type"] == "STOP_LOSS_LIMIT":
            if self.fail_stop:
                return 400, {"code": -2010, "msg": "Stop price would trigger immediately."}
            self.bal["BTC"][0] -= qty
            self.bal["BTC"][1] += qty
            o = {"orderId": oid, "status": "NEW", "origQty": q["quantity"], "stopPrice": q["stopPrice"],
                 "price": q["price"], "executedQty": "0", "cummulativeQuoteQty": "0"}
            self.orders[oid] = o
            return 200, o
        notional = qty * self.price
        if q["side"] == "BUY":
            fee = qty * Decimal("0.001")
            self.bal["USDT"][0] -= notional
            self.bal["BTC"][0] += qty - fee
            fills = [{"price": str(self.price), "qty": str(qty), "commission": str(fee), "commissionAsset": "BTC"}]
        else:
            if qty > self.bal["BTC"][0]:
                return 400, {"code": -2010, "msg": "Account has insufficient balance"}
            self.bal["BTC"][0] -= qty
            self.bal["USDT"][0] += notional
            fills = []
        o = {"orderId": oid, "status": "FILLED", "executedQty": str(qty), "cummulativeQuoteQty": str(notional),
             "fills": fills}
        self.orders[oid] = o
        return 200, o

    def fill_stop(self, oid):
        o = self.orders[oid]
        qty = Decimal(o["origQty"])
        o.update(status="FILLED", executedQty=o["origQty"], cummulativeQuoteQty=str(qty * Decimal(o["price"])))
        self.bal["BTC"][1] -= qty
        self.bal["USDT"][0] += qty * Decimal(o["price"])


def api(fake):
    return BinanceSpot("key", SECRET, transport=fake, clock=lambda: 1_700_000_000.0)


class TestSpotClient(unittest.TestCase):
    def test_demo_by_default_and_live_needs_flag(self):
        self.assertEqual(api(FakeBinance()).base_url, DEMO_URL)
        with self.assertRaises(LiveTradingDisabled):
            BinanceSpot("key", SECRET, live=True)
        self.assertEqual(BinanceSpot("key", SECRET, live=True, live_trading_enabled=True).base_url, LIVE_URL)

    def test_signed_request(self):
        fake = FakeBinance()
        bal = api(fake).balances()
        self.assertEqual(bal["USDT"][0], Decimal("10000.0"))
        _, path, q = fake.calls[-1]
        self.assertEqual(q["timestamp"], "1700000000000")
        self.assertIn("signature", q)

    def test_resyncs_clock_once_on_1021(self):
        fake = FakeBinance()
        calls = {"n": 0}

        def skewed(method, url, headers):
            if "/api/v3/time" in url:
                return 200, {"serverTime": 1_700_000_003_000}
            if "signature" in url and calls["n"] == 0:
                calls["n"] += 1
                return 400, {"code": -1021, "msg": "Timestamp for this request is outside of the recvWindow."}
            return fake(method, url, headers)

        client = BinanceSpot("key", SECRET, transport=skewed, clock=lambda: 1_700_000_000.0)
        self.assertIn("USDT", client.balances())
        self.assertEqual(client.time_offset_ms, 3_000)
        self.assertEqual(fake.calls[-1][2]["timestamp"], "1700000003000")

    def test_bad_secret_is_rejected(self):
        with self.assertRaises(Exception):
            BinanceSpot("key", "wrong", transport=FakeBinance()).balances()


class TestTrader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_places_exchange_stop_on_filled_qty(self):
        fake = FakeBinance()
        t = BinanceTrader(api(fake), self.state, capital=1_000)
        res = t.open("BTCUSDT", 0.0123456, stop=48_123.456, reason="test")
        self.assertEqual(res["event"], "entrada")
        stop_order = fake.orders[res["stop_order_id"]]
        self.assertEqual(stop_order["stopPrice"], "48123.45")             # redondeado al tick
        self.assertEqual(stop_order["price"], "47882.83")                 # 0,5 % debajo
        self.assertEqual(stop_order["origQty"], "0.01232")                # 0.01234 - comisión, al step
        self.assertIn("BTCUSDT", json.loads(self.state.read_text())["positions"])

    def test_never_left_without_stop(self):
        fake = FakeBinance(fail_stop=True)
        t = BinanceTrader(api(fake), self.state, capital=1_000)
        res = t.open("BTCUSDT", 0.01, stop=49_000, reason="test")
        self.assertEqual(res["event"], "abortada_sin_stop")
        self.assertEqual(t.state["positions"], {})
        self.assertEqual(fake.orders[max(fake.orders)]["fills"], [])     # la última orden fue la venta
        self.assertLess(fake.bal["BTC"][0], Decimal("0.0001"))

    def test_close_only_sells_what_the_bot_bought(self):
        fake = FakeBinance(btc=1.0)  # BTC previo del usuario
        t = BinanceTrader(api(fake), self.state, capital=1_000)
        t.open("BTCUSDT", 0.01, stop=49_000, reason="test")
        fake.price = Decimal("55000")
        res = t.close("BTCUSDT", "salida de canal")
        self.assertEqual(res["event"], "salida")
        self.assertGreater(res["pnl"], 0)
        self.assertGreaterEqual(fake.bal["BTC"][0], Decimal("1.0"))       # el BTC del usuario sigue ahí
        self.assertEqual(fake.bal["BTC"][1], Decimal(0))                  # el stop se canceló
        self.assertEqual(t.state["positions"], {})

    def test_sync_books_filled_stop(self):
        fake = FakeBinance()
        t = BinanceTrader(api(fake), self.state, capital=1_000)
        res = t.open("BTCUSDT", 0.01, stop=49_000, reason="test")
        fake.fill_stop(res["stop_order_id"])
        out = t.sync_stop("BTCUSDT")
        self.assertEqual(out["event"], "salida")
        self.assertLess(out["pnl"], 0)
        self.assertLess(t.state["realized_pnl"], 0)

    def test_sync_replaces_cancelled_stop(self):
        fake = FakeBinance()
        t = BinanceTrader(api(fake), self.state, capital=1_000)
        res = t.open("BTCUSDT", 0.01, stop=49_000, reason="test")
        api(fake).cancel("BTCUSDT", res["stop_order_id"])  # alguien lo cancela a mano
        out = t.sync_stop("BTCUSDT")
        self.assertEqual(out["event"], "stop_repuesto")
        self.assertEqual(fake.orders[out["stop_order_id"]]["status"], "NEW")

    def test_close_after_stop_already_filled(self):
        fake = FakeBinance()
        t = BinanceTrader(api(fake), self.state, capital=1_000)
        res = t.open("BTCUSDT", 0.01, stop=49_000, reason="test")
        fake.fill_stop(res["stop_order_id"])
        out = t.close("BTCUSDT", "salida de canal")
        self.assertEqual(out["reason"], "stop (ejecutado en Binance)")


class TestRoundtrip(unittest.TestCase):
    def test_roundtrip_ok_and_leaves_no_position(self):
        from jevtrader.binance import roundtrip_test
        fake = FakeBinance(btc=0.5)  # BTC previo del usuario: no se toca
        with tempfile.TemporaryDirectory() as d:
            client = api(fake)
            res = roundtrip_test(client, "BTCUSDT", client.price("BTCUSDT"), Path(d) / "rt.json")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["steps"]["stop_despues"], "CANCELED")
        self.assertGreaterEqual(fake.bal["BTC"][0], Decimal("0.5"))
        self.assertEqual(fake.bal["BTC"][1], Decimal(0))

    def test_roundtrip_refuses_live(self):
        from jevtrader.binance import roundtrip_test
        live = BinanceSpot("key", SECRET, live=True, live_trading_enabled=True, transport=FakeBinance())
        with self.assertRaises(LiveTradingDisabled):
            roundtrip_test(live, "BTCUSDT", 50_000, "/tmp/nope.json")


class TestStep(unittest.TestCase):
    def test_entry_then_idempotent(self):
        bars = synthetic(900, seed=11)
        ind = Indicators(bars)
        k = next(i for i in range(len(bars) - 1, 300, -1) if DonchianTrend().entry(ind, i))
        bars = bars[:k + 1]
        price = bars[-1].close
        with tempfile.TemporaryDirectory() as d:
            fake = FakeBinance(price=price, usdt=100_000)
            trader = BinanceTrader(api(fake), Path(d) / "s.json", capital=10_000)
            journal = Journal(Path(d) / "j.jsonl")
            judge = JevJudge(FixedJudgeClient(True), GateConfig())
            out = step_binance("BTCUSDT", "1d", Settings(), trader, judge, journal, bars=bars)
            self.assertEqual(out["event"], "entrada", out)
            self.assertEqual(out["env"], "demo")
            again = step_binance("BTCUSDT", "1d", Settings(), trader, judge, journal, bars=bars)
            self.assertEqual(again["event"], "sin_cambios")
            # riesgo: si salta el stop se pierde ~1 % del capital del bot (sin contar comisiones)
            pos = trader.state["positions"]["BTCUSDT"]
            self.assertAlmostEqual((pos["entry"] - pos["stop"]) * pos["qty"], 100, delta=2)


class TestGuardHook(unittest.TestCase):
    def run_hook(self, command):
        hook = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "guard_live.py"
        p = subprocess.run([sys.executable, str(hook)], input=json.dumps({"tool_input": {"command": command}}),
                           capture_output=True, text=True)
        return p.returncode

    def test_blocks_live_switches(self):
        self.assertEqual(self.run_hook("LIVE_TRADING=true python3 -m jevtrader binance"), 2)
        self.assertEqual(self.run_hook("BINANCE_ENV=live python3 -m jevtrader binance --once"), 2)
        self.assertEqual(self.run_hook("curl https://api.binance.com/api/v3/order"), 2)
        self.assertEqual(self.run_hook("cat .env"), 2)

    def test_allows_demo_and_data(self):
        self.assertEqual(self.run_hook("curl https://demo-api.binance.com/api/v3/ping"), 0)
        self.assertEqual(self.run_hook("python3 -m jevtrader binance --check"), 0)
        self.assertEqual(self.run_hook("cat .env.example"), 0)


if __name__ == "__main__":
    unittest.main()

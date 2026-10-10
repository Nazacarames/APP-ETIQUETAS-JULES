import tempfile
import unittest
from pathlib import Path

from jevtrader.broker import AlpacaBroker, LiveTradingDisabled, PaperBroker
from jevtrader.config import CostConfig, RiskConfig
from jevtrader.risk import AccountState, RiskManager


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(RiskConfig(risk_per_trade=0.01, max_position_pct=0.5))

    def test_size_risks_one_percent(self):
        qty = self.rm.position_size(10_000, entry=100, stop=95)
        self.assertAlmostEqual(qty * 5, 100)  # pierde 1 % si salta el stop

    def test_size_capped(self):
        qty = self.rm.position_size(10_000, entry=100, stop=99.9)
        self.assertAlmostEqual(qty * 100, 5_000)

    def test_size_mult_and_invalid_stop(self):
        self.assertAlmostEqual(self.rm.position_size(10_000, 100, 95, 0.5) * 5, 50)
        self.assertEqual(self.rm.position_size(10_000, 100, 101), 0.0)

    def test_drawdown_kill_switch_latches(self):
        acct = AccountState(equity=7_400, peak_equity=10_000, day_start_equity=7_400)
        ok, why = self.rm.can_open(acct)
        self.assertFalse(ok)
        self.assertTrue(acct.halted)
        acct.equity = 9_000  # se recupera, pero el bot sigue apagado hasta que un humano lo reactive
        self.assertFalse(self.rm.can_open(acct)[0])

    def test_daily_loss_and_max_positions(self):
        self.assertFalse(self.rm.can_open(AccountState(9_600, 10_000, 10_000))[0])
        self.assertFalse(self.rm.can_open(AccountState(10_000, 10_000, 10_000, open_positions=3))[0])
        self.assertTrue(self.rm.can_open(AccountState(10_000, 10_000, 10_000))[0])


class TestPaperBroker(unittest.TestCase):
    def test_round_trip_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            costs = CostConfig(fee_bps=10, slippage_bps=0)
            b = PaperBroker(Path(d) / "acct.json", costs, 1_000)
            b.buy("X", 5, 100, stop=90, reason="t")
            self.assertAlmostEqual(b.cash, 1_000 - 500 - 0.5)
            b.sell("X", 110, "t")
            self.assertAlmostEqual(b.cash, 1_000 - 500.5 + 550 - 0.55)
            again = PaperBroker(Path(d) / "acct.json", costs)  # persiste
            self.assertAlmostEqual(again.cash, b.cash)

    def test_rejects_overspend(self):
        with tempfile.TemporaryDirectory() as d:
            b = PaperBroker(Path(d) / "a.json", CostConfig(), 100)
            with self.assertRaises(ValueError):
                b.buy("X", 2, 100, 90, "t")


class TestAlpaca(unittest.TestCase):
    def test_live_requires_flag(self):
        with self.assertRaises(LiveTradingDisabled):
            AlpacaBroker("k", "s", live=True)

    def test_paper_order_payload(self):
        calls = []

        def transport(method, url, headers, body):
            calls.append((method, url, headers, body))
            return 200, {"id": "1"}

        AlpacaBroker("k", "s", transport=transport).buy_with_stop("AAPL", 3, 180.5)
        method, url, headers, body = calls[0]
        self.assertEqual(url, "https://paper-api.alpaca.markets/v2/orders")
        self.assertEqual(body["order_class"], "oto")
        self.assertEqual(body["stop_loss"]["stop_price"], "180.50")
        self.assertEqual(headers["APCA-API-KEY-ID"], "k")


if __name__ == "__main__":
    unittest.main()

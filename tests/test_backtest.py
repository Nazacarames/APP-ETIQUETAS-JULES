import tempfile
import unittest
from pathlib import Path

from jevtrader.backtest import buy_and_hold, run_backtest
from jevtrader.config import CostConfig, GateConfig, RiskConfig, Settings
from jevtrader.data import Bar, synthetic
from jevtrader.features import WARMUP
from jevtrader.jev_client import Answer, JevResponse, MockJev
from jevtrader.journal import Journal
from jevtrader.judge import JevJudge
from jevtrader.risk import RiskManager


class FixedJudgeClient:
    """Cliente falso que siempre responde lo mismo."""

    def __init__(self, allow: bool):
        self.allow = allow
        self.name = "fixed"

    def decide(self, state, questions):
        regime = "trending_up" if self.allow else "range_bound"
        probs = {"disorderly": 0.0, "range_bound": 0.0, "trending_down": 0.0, "trending_up": 0.0, regime: 1.0}
        return JevResponse("fixed", {
            "regime": Answer("choice", regime, probs, 1.0),
            "setup_quality": Answer("score", 2.0, {"0": 0, "1": 0, "2": 1}, 1.0),
            "overextended": Answer("noul", 0.0, {"true": 0, "false": 1}, 1.0),
        })


class TestBacktest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = synthetic(1200, seed=11)
        cls.costs = CostConfig(fee_bps=10, slippage_bps=5)
        cls.risk = RiskManager(RiskConfig())

    def run_bt(self, judge=None, name="t"):
        return run_backtest(self.bars, name=name, risk=self.risk, costs=self.costs, judge=judge)

    def test_accounting_invariant(self):
        res = self.run_bt()
        self.assertGreater(len(res.trades), 3)
        final = res.equity[-1][1]
        self.assertAlmostEqual(final, 10_000 + sum(t.pnl for t in res.trades), places=6)

    def test_fills_happen_on_next_bar(self):
        res = self.run_bt()
        signal_bars = {d["i"] for d in res.decisions if d["action"] == "entrada"}
        for t in res.trades:
            self.assertIn(t.entry_i - 1, signal_bars)
            self.assertGreaterEqual(t.entry_price, self.bars[t.entry_i].open)  # slippage en contra

    def test_allow_all_judge_equals_baseline(self):
        base = self.run_bt()
        allow = self.run_bt(JevJudge(FixedJudgeClient(True), GateConfig()))
        self.assertEqual([(t.entry_i, t.exit_i) for t in base.trades], [(t.entry_i, t.exit_i) for t in allow.trades])
        self.assertAlmostEqual(base.equity[-1][1], allow.equity[-1][1])

    def test_veto_all_judge_never_trades(self):
        res = self.run_bt(JevJudge(FixedJudgeClient(False), GateConfig()))
        self.assertEqual(res.trades, [])
        self.assertTrue(all(d["action"] == "vetada" for d in res.decisions))
        self.assertAlmostEqual(res.equity[-1][1], 10_000)

    def test_stop_gap_exits_at_open(self):
        # 220 velas subiendo suave, ruptura, y después un gap brutal hacia abajo.
        bars = []
        p = 100.0
        for i in range(WARMUP + 5):
            p *= 1.001
            bars.append(Bar(i, p, p * 1.002, p * 0.998, p, 100))
        last = bars[-1].close
        bars.append(Bar(len(bars), last, last * 1.05, last, last * 1.05, 500))   # ruptura (señal)
        nxt = last * 1.05
        bars.append(Bar(len(bars), nxt, nxt * 1.01, nxt * 0.99, nxt, 100))      # entrada en la apertura
        bars.append(Bar(len(bars), nxt * 0.5, nxt * 0.5, nxt * 0.45, nxt * 0.48, 100))  # gap bajo el stop
        bars.append(Bar(len(bars), nxt * 0.48, nxt * 0.5, nxt * 0.47, nxt * 0.49, 100))
        res = run_backtest(bars, name="gap", risk=self.risk, costs=CostConfig(0, 0))
        self.assertEqual(len(res.trades), 1)
        t = res.trades[0]
        self.assertEqual(t.exit_reason, "stop (gap)")
        self.assertAlmostEqual(t.exit_price, nxt * 0.5)

    def test_buy_and_hold(self):
        bh = buy_and_hold(self.bars, CostConfig(0, 0))
        expected = self.bars[-1].close / self.bars[WARMUP].open - 1
        self.assertAlmostEqual(bh.metrics["total_return"], expected, places=9)


class TestPaperLoop(unittest.TestCase):
    def test_step_is_idempotent(self):
        from jevtrader.broker import PaperBroker
        from jevtrader.live import step
        with tempfile.TemporaryDirectory() as d:
            settings = Settings(data_dir=Path(d))
            broker = PaperBroker(Path(d) / "acct.json", settings.costs)
            journal = Journal(Path(d) / "j.jsonl")
            judge = JevJudge(MockJev(), settings.gate)
            bars = synthetic(400, seed=2)
            first = step("SYN", "1d", settings, broker, judge, journal, bars=bars)
            self.assertIn(first["event"], {"entrada", "vetada", "sin_senal", "mantener", "salida", "bloqueado_por_riesgo"})
            second = step("SYN", "1d", settings, broker, judge, journal, bars=bars)
            self.assertEqual(second["event"], "sin_cambios")
            self.assertEqual(len(journal.read()), 1)


if __name__ == "__main__":
    unittest.main()

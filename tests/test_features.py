import re
import unittest

from jevtrader.data import Bar, synthetic
from jevtrader.features import (PHRASE_INDEX, WARMUP, Indicators, atr_series, describe, rsi_series,
                                sma_series, snapshot)


class TestSeries(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(sma_series([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_atr_constant_range(self):
        bars = [Bar(i, 10, 11, 9, 10, 1) for i in range(30)]
        atr = atr_series(bars, 14)
        self.assertIsNone(atr[12])
        self.assertAlmostEqual(atr[-1], 2.0)

    def test_rsi_only_up_is_100(self):
        self.assertEqual(rsi_series([float(i) for i in range(30)], 14)[-1], 100.0)


class TestNoLookahead(unittest.TestCase):
    def test_snapshot_ignores_future_bars(self):
        bars = synthetic(600, seed=3)
        k = 450
        full = snapshot(Indicators(bars), k)
        cut = snapshot(Indicators(bars[:k + 1]), k)
        self.assertEqual(full, cut)

    def test_warmup(self):
        bars = synthetic(400, seed=1)
        self.assertIsNone(snapshot(Indicators(bars), WARMUP - 1))
        self.assertIsNotNone(snapshot(Indicators(bars), WARMUP))


class TestDescribe(unittest.TestCase):
    def test_state_is_semantic_and_anonymous(self):
        bars = synthetic(600, seed=5)
        ind = Indicators(bars)
        for i in range(WARMUP, len(bars), 37):
            state = describe(snapshot(ind, i))
            for key, sentence in state.items():
                if key == "context":
                    continue
                self.assertIn(sentence, PHRASE_INDEX)
            text = " ".join(state.values())
            # Ni precios ni fechas: solo números de ventanas (5, 20, 50, 200 velas).
            numbers = set(re.findall(r"\d+(?:\.\d+)?", text))
            self.assertTrue(numbers <= {"5", "20", "50", "200"}, numbers)


if __name__ == "__main__":
    unittest.main()

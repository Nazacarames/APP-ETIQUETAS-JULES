import unittest

from polylens.study import (copier_return, copy_study, end_ts, group_entries, parse_ts, price_at, study_entry,
                            summarize, verdict, Entry)

H = 3600
T0 = 1_790_000_000


def fill(token, ts, price, size, side="BUY", cid="c1"):
    return {"token_id": token, "timestamp": ts, "price": price, "size": size, "side": side, "condition_id": cid,
            "title": "Market " + cid, "outcome": "Yes"}


def market(token="tok", final="1", closed_at=None, closed=True):
    m = {"closed": closed, "clobTokenIds": f'["{token}", "other"]',
         "outcomePrices": f'["{final}", "{1 - float(final)}"]'}
    if closed_at:
        m["closedTime"] = closed_at
    return m


class FakePM:
    def __init__(self, series=None, fills=None, markets=None):
        self.series = series or {}
        self.fills = fills or {}
        self.mk = markets or {}
        self.price_calls = []

    def prices_history(self, token_id, start, end, ttl=None):
        self.price_calls.append((token_id, start, end))
        return [(t, p) for t, p in self.series.get(token_id, []) if start <= t <= end]

    def trades(self, user, start=None, side=None, taker_only=True, limit=1000):
        assert taker_only is False and side == "BUY"  # hay que ver también las órdenes límite
        return self.fills.get(user, [])

    def markets(self, condition_ids):
        return {c: self.mk[c] for c in condition_ids if c in self.mk}


class TestGroupEntries(unittest.TestCase):
    def test_fills_within_an_hour_are_one_entry(self):
        fills = [fill("a", T0, 0.40, 100), fill("a", T0 + 1000, 0.50, 100), fill("a", T0 + 3000, 0.60, 200),
                 fill("a", T0 + 4000, 0.70, 10),  # más de 1 h desde el primero: entrada nueva
                 fill("b", T0 + 10, 0.20, 50), fill("a", T0 + 20, 0.99, 999, side="SELL")]
        entries = group_entries(fills)
        self.assertEqual(len(entries), 3)
        a1 = entries[0]
        self.assertEqual((a1.token_id, a1.ts, a1.fills), ("a", T0, 3))
        self.assertAlmostEqual(a1.usd, 40 + 50 + 120)
        self.assertAlmostEqual(a1.price, 210 / 400)
        self.assertEqual([e.token_id for e in entries], ["a", "b", "a"])

    def test_bad_rows_are_skipped(self):
        self.assertEqual(group_entries([{"side": "BUY", "token_id": "a", "timestamp": 1, "price": "x", "size": 1}]), [])


class TestHelpers(unittest.TestCase):
    def test_price_at_with_tolerance(self):
        s = [(100, 0.4), (200, 0.5), (5000, 0.9)]
        self.assertEqual(price_at(s, 150), 0.5)
        self.assertEqual(price_at(s, 200), 0.5)
        self.assertIsNone(price_at(s, 300, tolerance=1000))
        self.assertEqual(price_at(s, 300), 0.9)
        self.assertIsNone(price_at(s, 6000))

    def test_parse_ts_formats(self):
        self.assertEqual(parse_ts("2025-10-05T12:00:00Z"), 1759665600)
        self.assertEqual(parse_ts("2025-10-05 12:00:00+00"), 1759665600)
        self.assertEqual(parse_ts("2025-10-05T09:00:00-03:00"), 1759665600)
        self.assertEqual(parse_ts("2025-10-05"), 1759622400)
        self.assertIsNone(parse_ts("mañana"))
        self.assertIsNone(parse_ts(None))

    def test_end_ts_prefers_real_close(self):
        self.assertEqual(end_ts({"closedTime": "2025-10-05 12:00:00+00", "endDate": "2025-12-31"}), 1759665600)
        self.assertIsNone(end_ts({}))

    def test_copier_return(self):
        self.assertAlmostEqual(copier_return(0.5, 1.0, 0.01), 1 / 0.51 - 1)
        self.assertAlmostEqual(copier_return(0.5, 0.0, 0.01), -1.0)
        self.assertAlmostEqual(copier_return(0.995, 1.0, 0.01), 1 / 0.999 - 1)  # nunca paga más de 0,999


class TestStudyEntry(unittest.TestCase):
    def test_delays_after_resolution_are_not_copyable(self):
        e = Entry("tok", "c1", "M", "Yes", T0, 0.40, 400, 3)
        series = [(T0 + 60, 0.42), (T0 + H + 60, 0.50), (T0 + 6 * H + 60, 0.70)]
        closed = "2026-09-22 10:00:00+00"  # resolvió antes de las 24 h
        self.assertGreater(parse_ts(closed), T0 + 6 * H)
        self.assertLess(parse_ts(closed), T0 + 24 * H)
        pm = FakePM(series={"tok": series})
        row = study_entry(pm, e, market("tok", "1", closed), slippage=0.0)
        self.assertAlmostEqual(row["trader_ret"], 1 / 0.40 - 1)
        self.assertEqual(set(row["copier"]), {"0", "3600", "21600"})
        self.assertAlmostEqual(row["copier"]["3600"], 1 / 0.50 - 1)
        self.assertAlmostEqual(row["gap"]["21600"], 0.30)

    def test_unresolved_market_is_skipped(self):
        e = Entry("tok", "c1", "M", "Yes", T0, 0.4, 400, 1)
        self.assertIsNone(study_entry(FakePM(), e, market(closed=False)))


class TestSummary(unittest.TestCase):
    def rows(self, value, n):
        return [{"trader_ret": value, "copier": {"0": value, "3600": value}, "gap": {"0": 0.0, "3600": 0.01}}
                for _ in range(n)]

    def test_verdicts(self):
        self.assertEqual(summarize(self.rows(0.1, 25))["verdict"], "copiable (con demora de 1 h sigue ganando)")
        self.assertEqual(summarize(self.rows(-0.1, 25))["verdict"], "no copiable (con demora pierde)")
        self.assertEqual(summarize(self.rows(0.1, 5))["verdict"], "muestra chica")
        mixed = self.rows(0.5, 15) + self.rows(-0.5, 15)
        self.assertEqual(summarize(mixed)["verdict"], "no concluyente")
        self.assertEqual(verdict({}), "muestra chica")

    def test_summary_fields(self):
        s = summarize(self.rows(0.2, 10))
        self.assertEqual(s["n"], 10)
        self.assertAlmostEqual(s["by_delay"]["3600"]["gap_mean"], 0.01)
        self.assertEqual(s["by_delay"]["3600"]["win_rate"], 1.0)
        self.assertIsNone(summarize([])["trader"])


class TestCopyStudy(unittest.TestCase):
    def test_end_to_end_with_fake_data(self):
        fills = [fill("tok", T0 + i * 2 * H, 0.40, 500, cid="c1") for i in range(3)]
        fills += [fill("open", T0, 0.40, 500, cid="c2")]          # mercado sin resolver: no entra
        fills += [fill("tiny", T0, 0.40, 10, cid="c1")]           # menos de 100 USD: no entra
        series = {"tok": [(T0 + k * 60, 0.45) for k in range(0, 60 * 30, 5)]}
        pm = FakePM(series=series, fills={"a": fills},
                    markets={"c1": market("tok", "1"), "c2": market("open", "1", closed=False)})
        res = copy_study(pm, [{"user": "a", "name": "Ana", "significance": "sólido"},
                              {"user": "z", "name": "Zoe", "significance": "negativo"}], now=T0 + 10 * 86_400)
        self.assertEqual(len(res["traders"]), 1)
        s = res["traders"][0]["summary"]
        self.assertEqual((s["entries"], s["resolved"], s["n"]), (4, 3, 3))
        self.assertAlmostEqual(s["by_delay"]["0"]["mean"], 1 / 0.46 - 1)
        self.assertEqual(res["pooled"]["n"], 3)


if __name__ == "__main__":
    unittest.main()

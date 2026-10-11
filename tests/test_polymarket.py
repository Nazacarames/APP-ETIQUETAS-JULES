import unittest
from urllib.parse import parse_qs, urlparse

from polylens.http import Http
from polylens.polymarket import DAY, Polymarket, parse_list, token_outcome_price


class Router:
    """Transporte falso: responde según la ruta y guarda cada pedido (ruta, parámetros)."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, url, timeout):
        u = urlparse(url)
        q = parse_qs(u.query)
        self.calls.append((u.path, q))
        return 200, self.handler(u.path, q), {}


def pm_with(handler):
    r = Router(handler)
    return Polymarket(Http(transport=r, min_interval_s=0, sleep=lambda s: None)), r


def page(rows):
    return {"data": rows, "pagination": {"has_more": False}}


class TestResolvedPositions(unittest.TestCase):
    def test_sorted_by_time_trimmed_to_common_window_and_deduped(self):
        data = {
            "CLOSED": [{"token_id": "c1", "last_event_at": 500}, {"token_id": "c2", "last_event_at": 400},
                       {"token_id": "c3", "last_event_at": 300}],
            "REDEEMABLE": [{"token_id": "r1", "last_event_at": 450}, {"token_id": "r2", "last_event_at": 250}],
            "REDEEMABLE_LOST": [{"token_id": "c1", "last_event_at": 500}, {"token_id": "l1", "last_event_at": 350}],
        }
        pm, router = pm_with(lambda path, q: page(data[q["status"][0]]))
        rows, floor = pm.resolved_positions("0xabc", since=100, cap_per_status=3)
        self.assertEqual(floor, 300)  # CLOSED llegó al tope: todo se recorta a su fecha más vieja
        self.assertEqual(sorted(r["token_id"] for r in rows), ["c1", "c2", "c3", "l1", "r1"])
        for path, q in router.calls:
            self.assertEqual(path, "/v2/positions")
            self.assertEqual(q["sort_by"], ["TIMESTAMP"])  # nunca el orden por ganancia
            self.assertEqual(q["start"], ["100"])

    def test_no_cap_keeps_requested_window(self):
        pm, _ = pm_with(lambda path, q: page([{"token_id": q["status"][0], "last_event_at": 150}]))
        rows, floor = pm.resolved_positions("0xabc", since=100, cap_per_status=10)
        self.assertEqual((len(rows), floor), (3, 100))


class TestPrices(unittest.TestCase):
    def test_long_windows_are_split_in_15_day_chunks(self):
        def handler(path, q):
            s, e = int(q["start"][0]), int(q["end"][0])
            return page([{"timestamp": s, "price": 0.4}, {"timestamp": e, "price": 0.6}])

        pm, router = pm_with(handler)
        series = pm.prices_history("tok", 0, 40 * DAY)
        spans = [(int(q["start"][0]), int(q["end"][0])) for _, q in router.calls]
        self.assertEqual(len(spans), 3)
        self.assertTrue(all(e - s <= 15 * DAY for s, e in spans))
        self.assertNotIn("bucket_seconds", router.calls[0][1])  # forzarlo puede devolver vacío
        self.assertEqual([t for t, _ in series], sorted({0, 15 * DAY, 30 * DAY, 40 * DAY}))


class TestMarkets(unittest.TestCase):
    def test_chunks_of_20_open_and_closed(self):
        ids = [f"0x{i:02d}" for i in range(25)]

        def handler(path, q):
            closed = q["closed"][0] == "true"
            return [{"conditionId": c, "closed": closed} for c in q["condition_ids"] if (int(c, 16) % 2 == 0) == closed]

        pm, router = pm_with(handler)
        out = pm.markets(ids + [ids[0], ""])
        self.assertEqual(len(router.calls), 4)
        self.assertEqual(len(router.calls[0][1]["condition_ids"]), 20)
        self.assertEqual(set(out), set(ids))
        self.assertTrue(out["0x00"]["closed"])
        self.assertFalse(out["0x01"]["closed"])


class TestHelpers(unittest.TestCase):
    def test_parse_list(self):
        self.assertEqual(parse_list('["Yes", "No"]'), ["Yes", "No"])
        self.assertEqual(parse_list(["a"]), ["a"])
        self.assertEqual(parse_list("not json"), [])
        self.assertEqual(parse_list(None), [])

    def test_token_outcome_price(self):
        m = {"closed": True, "clobTokenIds": '["111", "222"]', "outcomePrices": '["1", "0"]'}
        self.assertEqual(token_outcome_price(m, "111"), 1.0)
        self.assertEqual(token_outcome_price(m, "222"), 0.0)
        self.assertIsNone(token_outcome_price(m, "333"))
        self.assertIsNone(token_outcome_price({**m, "closed": False}, "111"))  # sin resolver
        self.assertIsNone(token_outcome_price({}, "111"))


if __name__ == "__main__":
    unittest.main()

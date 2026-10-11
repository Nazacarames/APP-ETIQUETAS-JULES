import unittest

from polylens.flows import select_traders, smart_flows


def op(cid, outcome, price, value, avg=0.4, size=None, redeemable=False, title=None):
    return {"condition_id": cid, "outcome": outcome, "current_price": price, "current_value": value,
            "avg_price": avg, "current_size": size if size is not None else value / price, "redeemable": redeemable,
            "title": title or cid, "event_slug": "ev-" + cid, "end_date": "2026-12-31"}


class FakePM:
    def __init__(self, by_user):
        self.by_user = by_user
        self.asked = []

    def positions(self, user, status, limit=500, sort_by=None):
        self.asked.append((user, status, sort_by))
        if user == "boom":
            raise RuntimeError("caído")
        return self.by_user.get(user, [])


PROFILES = [
    {"user": "a", "name": "Ana", "significance": "sólido"},
    {"user": "b", "name": "Beto", "significance": "prometedor"},
    {"user": "boom", "name": "Roto", "significance": "sólido"},
    {"user": "c", "name": "Caro", "significance": "no se distingue de la suerte"},
]


class TestSelect(unittest.TestCase):
    def test_only_good_unless_asked(self):
        self.assertEqual([p["user"] for p in select_traders(PROFILES)], ["a", "b", "boom"])
        self.assertEqual(len(select_traders(PROFILES, include_all=True)), 4)
        self.assertEqual(len(select_traders(PROFILES, top=1)), 1)


class TestSmartFlows(unittest.TestCase):
    def test_aggregates_filters_and_marks_disputes(self):
        pm = FakePM({
            "a": [op("m1", "Yes", 0.5, 1000, avg=0.4), op("m2", "No", 0.2, 300),
                  op("m3", "Yes", 0.995, 5000), op("m4", "Yes", 0.5, 10), op("m5", "Yes", 0.5, 900, redeemable=True)],
            "b": [op("m1", "Yes", 0.5, 500, avg=0.3), op("m2", "Yes", 0.8, 200)],
            "c": [op("m9", "Yes", 0.5, 99999)],  # no pasó el filtro: no se lee
        })
        res = smart_flows(pm, PROFILES)
        self.assertNotIn("c", [u for u, _, _ in pm.asked])
        self.assertTrue(all(s == "OPEN" for _, s, _ in pm.asked))
        rows = {(m["condition_id"], m["outcome"]): m for m in res["markets"]}
        self.assertEqual(set(rows), {("m1", "Yes"), ("m2", "No"), ("m2", "Yes")})  # sin resueltos, polvo ni ~1,00
        m1 = rows[("m1", "Yes")]
        self.assertEqual((m1["n"], m1["value"]), (2, 1500))
        self.assertAlmostEqual(m1["avg_entry"], (0.4 * 2000 + 0.3 * 1000) / 3000, places=4)
        self.assertAlmostEqual(m1["upside_if_wins"], 1.0)
        self.assertFalse(m1["disputed"])
        self.assertTrue(rows[("m2", "No")]["disputed"])
        self.assertEqual(res["markets"][0]["condition_id"], "m1")  # más traders primero
        self.assertEqual([t["user"] for t in res["traders"]], ["a", "b", "boom"])


if __name__ == "__main__":
    unittest.main()

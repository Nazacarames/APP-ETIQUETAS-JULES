import statistics
import unittest

from polylens.profiles import TraderProfile, build_profile, flags_for, position_result, rank, thresholds

DAY = 86_400


def pos(avg, size, pnl, first=0, last=DAY, status="CLOSED", end_date="2026-01-10", title="m", slug="e", token=None):
    return {"avg_price": avg, "total_size": size, "total_pnl": pnl, "first_entry_at": first, "last_event_at": last,
            "status": status, "end_date": end_date, "title": title, "event_slug": slug, "token_id": token or title,
            "condition_id": "c-" + title, "outcome": "Yes"}


class TestPositionResult(unittest.TestCase):
    def test_cost_and_return(self):
        r = position_result(pos(0.25, 400, 50))
        self.assertAlmostEqual(r.cost, 100)
        self.assertAlmostEqual(r.ret, 0.5)

    def test_dust_and_garbage_are_ignored(self):
        self.assertIsNone(position_result(pos(0.5, 10, 1)))      # 5 USD < mínimo
        self.assertIsNone(position_result(pos("x", 10, 1)))
        self.assertIsNone(position_result(pos(0, 1000, 1)))

    def test_falls_back_to_realized_pnl(self):
        p = pos(0.5, 100, None)
        p["realized_pnl"] = -10
        self.assertAlmostEqual(position_result(p).pnl, -10)


class TestBuildProfile(unittest.TestCase):
    def test_metrics(self):
        positions = [pos(0.5, 200, 20 if i % 4 else -100, first=i * DAY, title=f"m{i}") for i in range(40)]
        p = build_profile("0xu", positions, {"trades": 80, "join_date": DAY}, {"user_name": "ana", "pnl": 5}, now=41 * DAY)
        self.assertEqual((p.n, p.name, p.board_pnl), (40, "ana", 5.0))
        self.assertAlmostEqual(p.win_rate, 0.75)
        self.assertAlmostEqual(p.total_cost, 4000)
        self.assertAlmostEqual(p.roi, (30 * 20 - 10 * 100) / 4000)
        rets = [0.2 if i % 4 else -1.0 for i in range(40)]
        self.assertAlmostEqual(p.t_stat, statistics.fmean(rets) / statistics.pstdev(rets) * 40 ** 0.5)
        self.assertAlmostEqual(p.trades_per_day, 2.0)
        self.assertAlmostEqual(p.share_favorites, 0.0)

    def test_huge_wins_are_clipped_for_consistency(self):
        base = [pos(0.5, 200, 10, title=f"m{i}") for i in range(30)]
        lucky = base + [pos(0.01, 10_000, 1_000_000, title="jackpot")]
        self.assertLess(build_profile("u", lucky).t_stat, build_profile("u", base + [pos(0.5, 200, 1000, title="j")]).t_stat * 10)
        self.assertGreater(build_profile("u", lucky).top_share, 0.99)

    def test_late_longshot_wins(self):
        end = "2026-01-10"
        late = 1_768_003_200 - DAY  # un día antes del fin del 10/01/2026 (UTC)
        positions = [pos(0.1, 60_000, 50_000, first=late, end_date=end, title=f"x{i}") for i in range(2)]
        p = build_profile("u", positions)
        self.assertEqual(p.late_longshot_wins, 2)
        self.assertTrue(any("información anticipada" in f for f in p.flags))

    def test_no_positions(self):
        p = build_profile("u", [])
        self.assertEqual(p.n, 0)
        self.assertIn("sin posiciones", p.flags[0])

    def test_categories(self):
        positions = [pos(0.5, 200, 10, title=f"m{i}", slug="nba" if i < 3 else "fed") for i in range(5)]
        p = build_profile("u", positions, categorize=lambda r: "sports" if r.event_slug == "nba" else "economy")
        self.assertEqual(p.categories["sports"]["n"], 3)
        self.assertEqual(list(p.categories), ["sports", "economy"])  # por dinero puesto


class TestFlags(unittest.TestCase):
    def test_flags(self):
        p = TraderProfile(user="u", n=5, top_share=0.8, total_pnl=10, share_favorites=0.7, share_longshots=0.6,
                          trades_per_day=500, roi_first_half=0.1, roi_second_half=-0.1, total_cost=100, worst_loss=-50)
        text = " | ".join(flags_for(p))
        for needle in ("pocas posiciones", "una sola apuesta", "casi seguros", "batacazos", "bot", "ganaba",
                       "peor posición"):
            self.assertIn(needle, text)

    def test_clean_profile_has_no_flags(self):
        self.assertEqual(flags_for(TraderProfile(user="u", n=100, total_cost=100)), [])


class TestRank(unittest.TestCase):
    def test_thresholds_grow_with_number_of_traders(self):
        th = thresholds(40)
        self.assertAlmostEqual(th["azar"], 1.96, places=2)
        self.assertAlmostEqual(th["solido"], 3.02, places=2)
        self.assertGreater(thresholds(1000)["solido"], th["solido"])

    def test_labels_and_order(self):
        ps = [TraderProfile(user=str(i), n=n, t_stat=t) for i, (n, t) in
              enumerate([(100, 3.5), (100, 2.2), (100, 0.5), (100, -1.0), (5, 9.0)] + [(100, 0.1)] * 35)]
        ranked = rank(ps, min_positions=20)
        labels = {p.user: p.significance for p in ranked}
        self.assertEqual([labels[str(i)] for i in range(5)],
                         ["sólido", "prometedor", "no se distingue de la suerte", "negativo", "muestra chica"])
        self.assertEqual(ranked[0].user, "0")
        self.assertAlmostEqual(next(p for p in ranked if p.user == "4").score, 9.0 * 5 / 20)  # muestra chica pesa menos


if __name__ == "__main__":
    unittest.main()

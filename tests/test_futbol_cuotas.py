import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import futbol.__main__ as cli
from futbol import cuotas as cq
from futbol import valor
from futbol.config import FutbolConfig
from tests.test_futbol_datos import api_with, ok


def bet(name, values):
    return {"name": name, "values": [{"value": k, "odd": str(v)} for k, v in values.items()]}


def item(fixture=77, league=128, pinnacle=None, bet365=None):
    books = []
    if pinnacle is not None:
        books.append({"id": 4, "name": "Pinnacle", "bets": pinnacle})
    if bet365 is not None:
        books.append({"id": 8, "name": "Bet365", "bets": bet365})
    return {"league": {"id": league, "name": "Liga Profesional Argentina"},
            "fixture": {"id": fixture, "date": "2026-10-12T20:00:00+00:00"}, "update": "2026-10-12T10:00:00+00:00",
            "bookmakers": books}


PIN = [bet("Match Winner", {"Home": 2.0, "Draw": 3.4, "Away": 4.2}),
       bet("Goals Over/Under", {"Over 2.5": 2.1, "Under 2.5": 1.8, "Over 1.5": 1.4}),
       bet("Both Teams Score", {"Yes": 1.95, "No": 1.95})]
B365 = [bet("Match Winner", {"Home": 2.25, "Draw": 3.2, "Away": 3.9}),
        bet("Goals Over/Under", {"Over 2.5": 2.0, "Under 2.5": 1.75}),
        bet("Both Teams Score", {"Yes": 1.9, "No": 1.9}),
        bet("Home Player Shots", {"Juan Pérez - 1": 1.3, "Juan Pérez - 2": 2.4, "Pedro Gómez - 1": 1.8,
                                  "Pedro Gómez - 2": 1.7}),
        bet("Home Player Shots On Target Total", {"Juan Pérez - 1": 2.2, "Pedro Gómez - 1": 1.6}),
        bet("Anytime Goal Scorer", {"Juan Pérez": 3.5, "Pedro Gómez": 5.0, "No Goalscorer": 9.0})]


class TestTeamValue(unittest.TestCase):
    def test_fair_probability_and_value(self):
        rows = cq.team_value(item(pinnacle=PIN, bet365=B365), min_edge=-1)
        home = next(r for r in rows if r["market"] == "Match Winner" and r["selection"] == "Home")
        p = cq.fair_probs({"Home": 2.0, "Draw": 3.4, "Away": 4.2})["Home"]  # método power por defecto
        self.assertAlmostEqual(home["p"], p)
        self.assertAlmostEqual(home["ev"], p * 2.25 - 1)
        self.assertEqual(rows[0]["selection"], "Home")  # el de más valor primero
        self.assertNotIn("Over 1.5", {r["selection"] for r in rows})  # sin su 'Under' no hay grupo completo

    def test_min_edge_and_missing_reference(self):
        rows = cq.team_value(item(pinnacle=PIN, bet365=B365), min_edge=0.05)
        self.assertEqual([(r["market"], r["selection"]) for r in rows], [("Match Winner", "Home")])
        self.assertEqual(cq.team_value(item(bet365=B365)), [])

    def test_broken_groups_are_ignored(self):
        bad = [bet("Match Winner", {"Home": 5.0, "Draw": 5.0, "Away": 5.0})]  # margen negativo: datos que no cierran
        self.assertEqual(cq.team_value(item(pinnacle=bad, bet365=B365), min_edge=-1), [])

    def test_devig_methods(self):
        g = {"Home": 1.5, "Draw": 4.2, "Away": 7.5}
        probs = {m: cq.fair_probs(g, m) for m in ("multiplicative", "power", "shin")}
        for m, p in probs.items():
            self.assertAlmostEqual(sum(p.values()), 1.0, places=6, msg=m)
        # power y Shin le sacan más margen al batacazo que el multiplicativo (sesgo favorito–batacazo)
        self.assertLess(probs["power"]["Away"], probs["multiplicative"]["Away"])
        self.assertLess(probs["shin"]["Away"], probs["multiplicative"]["Away"])
        self.assertGreater(probs["power"]["Home"], probs["multiplicative"]["Home"])
        fair = {"Yes": 2.0, "No": 2.0}  # sin margen: todos los métodos devuelven lo mismo
        self.assertAlmostEqual(cq.fair_probs(fair, "power")["Yes"], 0.5)
        with self.assertRaises(ValueError):
            cq.fair_probs(g, "otro")

    def test_groups(self):
        g = cq.outcome_groups("Goals Over/Under", {"Over 2.5": 2, "Under 2.5": 1.8, "Over 3.5": 3})
        self.assertEqual(g, [{"Over 2.5": 2, "Under 2.5": 1.8}])
        self.assertEqual(cq.outcome_groups("Match Winner", {"Home": 2, "Away": 3}), [])


class TestPlayers(unittest.TestCase):
    def test_parse_players(self):
        players = cq.bet365_players(item(bet365=B365))
        self.assertEqual(players["Juan Pérez"]["shots"], {1: 1.3, 2: 2.4})
        self.assertEqual(players["Juan Pérez"]["sot"], {1: 2.2})
        self.assertEqual(players["Juan Pérez"]["goal"], 3.5)
        self.assertEqual(players["Juan Pérez"]["side"], "home")
        self.assertNotIn("No Goalscorer", players)

    def test_coherence_flags(self):
        flags = cq.coherence_flags(cq.bet365_players(item(bet365=B365)))
        checks = {(f["player"], f["check"]) for f in flags}
        # Pedro: 2+ remates (1.70) paga menos que 1+ (1.80) y 1+ al arco (1.60) paga menos que 1+ remate (1.80)
        self.assertEqual(checks, {("Pedro Gómez", "2+ > 1+ remates"), ("Pedro Gómez", "al arco > remates")})
        self.assertEqual(cq.coherence_flags(cq.bet365_players(item(bet365=B365)), tolerance=0.5), [])


class TestMovementsClvHitRate(unittest.TestCase):
    def test_snapshot_and_movements(self):
        with tempfile.TemporaryDirectory() as d:
            first = cq.snapshot_rows(item(pinnacle=PIN, bet365=B365))
            self.assertEqual(cq.save_snapshot(Path(d), 77, first), [])
            pin2 = [bet("Match Winner", {"Home": 1.8, "Draw": 3.6, "Away": 4.6})] + PIN[1:]
            moved = item(pinnacle=pin2, bet365=B365)
            moved["update"] = "2026-10-12T13:00:00+00:00"
            second = cq.snapshot_rows(moved)
            prev = cq.save_snapshot(Path(d), 77, second)
            self.assertEqual(len(prev), len(first))
            mv = cq.movements(prev, second)
            lag = [m for m in mv if "bet365_lag" in m]
            self.assertEqual([(m["selection"], m["from"], m["to"], m["bet365_lag"]) for m in lag],
                             [("Home", 2.0, 1.8, 2.25)])  # Pinnacle bajó y bet365 quedó en 2,25

    def test_clv(self):
        closing = item(pinnacle=[bet("Match Winner", {"Home": 1.9, "Draw": 3.6, "Away": 4.6})], bet365=B365)
        e = {"kind": "equipo", "market": "Match Winner", "selection": "Home", "odd": 2.25}
        r = cq.closing_value(e, closing)
        p = cq.fair_probs({"Home": 1.9, "Draw": 3.6, "Away": 4.6})["Home"]
        self.assertAlmostEqual(r["clv"], 2.25 * p - 1)
        e = {"stat": "shots", "k": 1, "name": "Juan Pérez", "odd": 1.4}
        self.assertAlmostEqual(cq.closing_value(e, closing)["clv"], 1.4 / 1.3 - 1)
        self.assertIsNone(cq.closing_value({**e, "name": "Nadie"}, closing))

    def test_journal_clv_only_after_kickoff(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "papel.jsonl"
            valor.journal_add_team(path, 77, [{"market": "Match Winner", "selection": "Home", "odd": 2.25, "p": 0.5,
                                               "stake": 2.0}])
            closing = item(pinnacle=[bet("Match Winner", {"Home": 1.9, "Draw": 3.6, "Away": 4.6})], bet365=B365)
            kickoff = 1_791_835_200  # 2026-10-12 20:00 UTC, la fecha de item()
            self.assertEqual(valor.journal_clv(path, lambda f: closing, now=kickoff - 60)["with_clv"], 0)
            r = valor.journal_clv(path, lambda f: closing, now=kickoff + 60)
            self.assertEqual(r["with_clv"], 1)
            self.assertGreater(r["mean_clv"], 0)
            self.assertEqual(r["beat_close"], 1.0)

    def test_hit_rate(self):
        apps = [{"player": 1, "started": True, "ts": t, "sot": s} for t, s in enumerate([1, 0, 2, 1, 1, 0, 3])]
        apps.append({"player": 1, "started": False, "ts": 99, "sot": 5})
        self.assertEqual(cq.hit_rate(apps, 1, "sot", 1, last=5), (4, 5))
        self.assertEqual(cq.hit_rate(apps, 1, "sot", 1, last=5, before_ts=3), (2, 3))


class TestSettle(unittest.TestCase):
    def test_settle(self):
        self.assertTrue(cq.settle_team("Match Winner", "Home", 2, 1))
        self.assertFalse(cq.settle_team("Match Winner", "Draw", 2, 1))
        self.assertTrue(cq.settle_team("Goals Over/Under", "Over 2.5", 2, 1))
        self.assertIsNone(cq.settle_team("Goals Over/Under", "Over 3.0", 2, 1))  # exacto: se devuelve
        self.assertTrue(cq.settle_team("Both Teams Score", "No", 2, 0))
        self.assertTrue(cq.settle_team("Total - Away", "Under 1.5", 2, 1))
        self.assertIsNone(cq.settle_team("First Half Winner", "Home", 2, 1))
        self.assertTrue(cq.settle_team("First Half Winner", "Draw", 2, 1, (0, 0)))

    def test_team_journal(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "papel.jsonl"
            bets = [{"market": "Match Winner", "selection": "Home", "odd": 2.25, "p": 0.5, "stake": 2.0},
                    {"market": "Goals Over/Under", "selection": "Over 2.5", "odd": 2.0, "p": 0.5, "stake": 1.0},
                    {"market": "Both Teams Score", "selection": "Yes", "odd": 1.9, "p": 0.5, "stake": 0.0}]
            self.assertEqual(valor.journal_add_team(path, 77, bets, "A vs B"), 2)
            s = valor.journal_settle(path, [], 100, {77: (1, 0, None)})
            self.assertEqual((s["settled"], s["won"]), (2, 1))
            self.assertAlmostEqual(s["pnl"], 2.0 * 1.25 - 1.0)


class TestFindFixtures(unittest.TestCase):
    def test_falls_back_to_odds_mapping(self):
        def routes(path, q):
            if path == "fixtures":
                return {"errors": {"plan": "Free plans do not have access to this season"}, "response": []}
            if path == "odds/mapping":
                page = int(q.get("page", 1))
                rows = [{"league": {"id": 128, "season": 2026}, "fixture": {"id": 10 + page, "date": f"2026-10-1{page}T20:00:00+00:00"}},
                        {"league": {"id": 39, "season": 2026}, "fixture": {"id": 99, "date": "2026-10-12T20:00:00+00:00"}}]
                return ok(rows, page, 3)
            raise AssertionError(path)
        api, _ = api_with(routes)
        found = cq.league_fixtures_for_date(api, "2026-10-12", 128)
        self.assertEqual([f["fixture"] for f in found], [12])


class TestCuotasCommand(unittest.TestCase):
    def test_cli_prints_value_flags_and_journals(self):
        def routes(path, q):
            self.assertEqual(path, "odds")
            return ok([item(fixture=int(q["fixture"]), pinnacle=PIN, bet365=B365)])
        api, _ = api_with(routes)
        with tempfile.TemporaryDirectory() as d:
            cfg = FutbolConfig(data_dir=Path(d))
            out = io.StringIO()
            with mock.patch.object(cli, "api_from", return_value=api), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                cli.main(["cuotas", "--partido", "77", "--anotar"], cfg)
            text = out.getvalue()
            self.assertIn("Match Winner", text)
            self.assertIn("Incoherencia", text)
            self.assertIn("Juan Pérez", text)
            entries = [json.loads(x) for x in (Path(d) / "papel.jsonl").read_text().splitlines()]
            self.assertEqual([(e["kind"], e["selection"]) for e in entries], [("equipo", "Home")])
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                cli.main(["papel", "--resultado", "77:2-0"], cfg)
            self.assertIn("ganadas 1", out.getvalue())


if __name__ == "__main__":
    unittest.main()

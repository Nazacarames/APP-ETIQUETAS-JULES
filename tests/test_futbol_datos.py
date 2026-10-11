import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from futbol.api import ApiError, ApiFootball, odds_rows
from futbol.datos import appearances, find_fixture, goal_events, load_appearances, sync
from polylens.http import Http


def fixture(fid, ts, home=1, away=2, status="FT", goals=(1, 0)):
    return {"fixture": {"id": fid, "timestamp": ts, "status": {"short": status}},
            "league": {"id": 128, "season": 2024, "round": "Regular Season - 1"},
            "teams": {"home": {"id": home, "name": f"Equipo {home}"}, "away": {"id": away, "name": f"Equipo {away}"}},
            "goals": {"home": goals[0], "away": goals[1]}}


def player(pid, minutes, shots, on, sub=False, pos="F"):
    return {"player": {"id": pid, "name": f"Jugador {pid}"},
            "statistics": [{"games": {"minutes": minutes, "position": pos, "substitute": sub},
                            "shots": {"total": shots, "on": on}, "goals": {"total": None, "assists": None},
                            "cards": {"yellow": 0, "red": 0}}]}


def players_body(home_players, away_players, home=1, away=2):
    return [{"team": {"id": home, "name": f"Equipo {home}"}, "players": home_players},
            {"team": {"id": away, "name": f"Equipo {away}"}, "players": away_players}]


class FakeApi:
    """Transporte falso de API-Football: guarda URL y encabezados de cada pedido."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, timeout):
        u = urlparse(url)
        self.calls.append(u)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        body = self.routes(u.path.lstrip("/"), q)
        return 200, body, {}


def api_with(routes, cache_dir=None):
    t = FakeApi(routes)
    http = Http(cache_dir, transport=t, min_interval_s=0, sleep=lambda s: None,
                cacheable=lambda b: not (isinstance(b, dict) and b.get("errors")))
    return ApiFootball(None, "https://api.test", http=http), t


def ok(response, page=1, total=1):
    return {"errors": [], "results": len(response), "paging": {"current": page, "total": total}, "response": response}


class TestApi(unittest.TestCase):
    def test_key_is_required_and_goes_in_header(self):
        with self.assertRaises(ApiError):
            ApiFootball(None)
        api = ApiFootball("secreta")
        self.assertNotIn("secreta", api.base)

    def test_errors_raise_and_are_not_cached(self):
        with tempfile.TemporaryDirectory() as d:
            state = {"n": 0}

            def routes(path, q):
                state["n"] += 1
                if state["n"] == 1:
                    return {"errors": {"plan": "Free plans do not have access to this season"}, "response": []}
                return ok([{"x": 1}])

            api, t = api_with(routes, d)
            with self.assertRaises(ApiError) as cm:
                api.get("fixtures", {"season": 2026})
            self.assertIn("Free plans", str(cm.exception))
            self.assertEqual(api.get("fixtures", {"season": 2026})["response"], [{"x": 1}])  # no quedó en caché
            api.get("fixtures", {"season": 2026})
            self.assertEqual(len(t.calls), 2)  # la buena sí

    def test_pagination(self):
        def routes(path, q):
            page = int(q.get("page", 1))
            return ok([{"page": page}], page, 3)
        api, t = api_with(routes)
        self.assertEqual([r["page"] for r in api.all_pages("odds", {"fixture": 1})], [1, 2, 3])

    def test_odds_rows(self):
        body = [{"fixture": {"id": 9}, "bookmakers": [{"id": 8, "name": "Bet365", "bets": [
            {"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": "1.85"}, {"value": "Draw", "odd": "x"}]},
            {"id": 99, "name": "Player Shots On Target", "values": [{"value": "J. Pérez - Over 0.5", "odd": "2.10"}]}]}]}]
        rows = odds_rows(body)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["market"], "Player Shots On Target")
        self.assertEqual(rows[0]["odd"], 1.85)


class TestSync(unittest.TestCase):
    def routes(self, path, q):
        if path == "fixtures":
            return ok([fixture(10, 100), fixture(11, 200, 2, 1), fixture(12, 300, status="NS")])
        if path == "fixtures/players":
            fid = int(q["fixture"])
            if fid == 11:
                return ok(players_body([player(1, 90, None, None)], [player(2, 90, None, None)], 2, 1))
            return ok(players_body([player(1, 90, 3, 1), player(3, 20, 1, 0, sub=True), player(5, 0, None, None)],
                                   [player(2, 85, 0, 0, pos="D")]))
        if path == "fixtures/events":
            return ok([{"time": {"elapsed": 30, "extra": None}, "team": {"id": 1}, "type": "Goal", "detail": "Normal Goal"},
                       {"time": {"elapsed": 90, "extra": 4}, "team": {"id": 2}, "type": "Goal", "detail": "Missed Penalty"},
                       {"time": {"elapsed": 50}, "team": {"id": 1}, "type": "Card", "detail": "Yellow Card"}])
        raise AssertionError(path)

    def test_budget_resume_and_tables(self):
        with tempfile.TemporaryDirectory() as d:
            api, t = api_with(self.routes)
            r = sync(api, 128, 2024, Path(d), max_calls=2, kinds=("players", "events"))
            self.assertEqual((r["calls"], r["pending"]), (2, 3))  # calendario + 1; quedan 3 pedidos para otro día
            r = sync(api, 128, 2024, Path(d), max_calls=10, kinds=("players", "events"))
            self.assertEqual(r["fetched"], {"players": 1, "events": 2})  # solo lo que faltaba: no repite el partido 10
            rows = appearances(Path(d), 128, 2024)
            self.assertEqual({x["player"] for x in rows}, {1, 2, 3})  # sin el que no jugó ni el partido sin remates
            j1 = next(x for x in rows if x["player"] == 1)
            self.assertEqual((j1["shots"], j1["sot"], j1["started"], j1["home"], j1["opp"]), (3, 1, True, True, 2))
            self.assertFalse(next(x for x in rows if x["player"] == 3)["started"])
            ev = goal_events(Path(d), 128, 2024)
            self.assertEqual([g["minute"] for g in ev[0]["goals"]], [30])  # el penal errado no es gol
            self.assertEqual(load_appearances(Path(d), [(128, 2024)])[0]["league"], 128)
            self.assertEqual(find_fixture(Path(d), [(128, 2024)], 12)["fixture"]["status"]["short"], "NS")

    def test_quota_error_stops_cleanly(self):
        def routes(path, q):
            if path == "fixtures":
                return ok([fixture(10, 100), fixture(11, 200)])
            return {"errors": {"requests": "You have reached the request limit for the day"}, "response": []}
        with tempfile.TemporaryDirectory() as d:
            api, _ = api_with(routes)
            r = sync(api, 128, 2024, Path(d), kinds=("players",))
            self.assertIn("request limit", r["stopped"])
            self.assertFalse((Path(d) / "raw" / "players" / "10.json").exists())


if __name__ == "__main__":
    unittest.main()

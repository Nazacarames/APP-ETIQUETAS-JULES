import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from futbol import minutos, valor
from futbol.__main__ import build_parser, main
from futbol.config import FutbolConfig, parse_competitions
from futbol.noticias import STATUS, SpanishKeywords, mentions, player_news
from polylens.jev_client import Answer, JevError, JevResponse, MockJev
from polylens.news import Headline
from tests.test_futbol_datos import fixture, player, players_body

PLAYERS = [{"player": 1, "name": "Edinson Cavani", "p_sot_1": 0.55, "p_shots_2": 0.6},
           {"player": 2, "name": "Miguel Merentiel", "p_sot_1": 0.45},
           {"player": 3, "name": "Juan Pérez", "p_sot_1": 0.2},
           {"player": 4, "name": "Pedro Pérez", "p_sot_1": 0.2}]


class TestValor(unittest.TestCase):
    def test_match_player(self):
        self.assertEqual(valor.match_player("Edinson Cavani", PLAYERS)["player"], 1)
        self.assertEqual(valor.match_player("E. Cavani", PLAYERS)["player"], 1)
        self.assertEqual(valor.match_player("cavani", PLAYERS)["player"], 1)
        self.assertEqual(valor.match_player("J. Perez", PLAYERS)["player"], 3)  # sin tilde y con inicial
        self.assertIsNone(valor.match_player("Pérez", PLAYERS))                # ambiguo: no adivina
        self.assertIsNone(valor.match_player("Messi", PLAYERS))

    def test_threshold(self):
        for text, k in (("Over 0.5", 1), ("1.5", 2), ("2+", 2), ("Más de 2,5", 3), ("+1.5", 2)):
            self.assertEqual(valor.threshold_from(text), k, text)
        self.assertIsNone(valor.threshold_from("nada"))

    def test_stake_is_quarter_kelly_capped(self):
        self.assertEqual(valor.stake(0.5, 1.8, 100), 0.0)        # sin valor
        self.assertEqual(valor.stake(0.55, 2.0, 100), 2.5)       # Kelly 10 % → un cuarto = 2,5 %
        self.assertEqual(valor.stake(0.9, 3.0, 100), 3.0)        # tope de 3 %
        self.assertAlmostEqual(valor.ev(0.55, 2.0), 0.10)

    def test_api_player_odds(self):
        rows = [{"market": "Player Shots On Target", "selection": "E. Cavani - Over 0.5", "handicap": None, "odd": 2.1},
                {"market": "Player Shots On Target", "selection": "E. Cavani - Under 0.5", "handicap": None, "odd": 1.7},
                {"market": "Player Shots", "selection": "Edinson Cavani", "handicap": "1.5", "odd": 1.9},
                {"market": "Match Winner", "selection": "Home", "handicap": None, "odd": 1.8}]
        found, other = valor.api_player_odds(rows, PLAYERS)
        self.assertEqual([(f["stat"], f["k"], f["odd"]) for f in found], [("sot", 1, 2.1), ("shots", 2, 1.9)])
        self.assertEqual([o["market"] for o in other], ["Match Winner"])

    def test_manual_odds_and_value(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cuotas.csv"
            p.write_text("fixture,jugador,mercado,linea,cuota\n7,E. Cavani,remates_al_arco,0.5,2.10\n"
                         "7,Messi,remates,1.5,2\n8,Cavani,remates,0.5,1.2\n7,Cavani,goles,0.5,x\n", encoding="utf-8")
            odds, problems = valor.manual_odds(p, 7, PLAYERS)
            self.assertEqual(len(odds), 1)
            self.assertEqual(len(problems), 2)
            bets = valor.value_bets(odds, PLAYERS, 100)
            self.assertAlmostEqual(bets[0]["ev"], 0.55 * 2.1 - 1)
            self.assertGreater(bets[0]["stake"], 0)

    def test_journal(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "papel.jsonl"
            bets = [{"player": 1, "name": "Cavani", "stat": "sot", "k": 1, "odd": 2.0, "p": 0.6, "stake": 3.0},
                    {"player": 2, "name": "Merentiel", "stat": "shots", "k": 2, "odd": 2.0, "p": 0.6, "stake": 2.0},
                    {"player": 9, "name": "Suplente", "stat": "sot", "k": 1, "odd": 3.0, "p": 0.4, "stake": 1.0},
                    {"player": 3, "name": "Sin valor", "stat": "sot", "k": 1, "odd": 3.0, "p": 0.2, "stake": 0.0}]
            self.assertEqual(valor.journal_add(path, 77, bets), 3)
            apps = [{"fixture": 77, "player": 1, "sot": 2, "shots": 3}, {"fixture": 77, "player": 2, "sot": 0, "shots": 1}]
            s = valor.journal_settle(path, apps, 100)
            self.assertEqual((s["settled"], s["won"], s["pending"]), (2, 1, 0))
            self.assertAlmostEqual(s["pnl"], 3.0 - 2.0)
            self.assertAlmostEqual(s["bankroll"], 101.0)
            statuses = [json.loads(x)["status"] for x in path.read_text().splitlines()]
            self.assertEqual(statuses, ["ganada", "perdida", "anulada"])  # el que no jugó se anula


def match(goals, final=None):
    return {"fixture": 1, "ts": 0, "goals": [{"minute": m, "extra": 0, "home": h} for m, h in goals], "final": final}


class TestMinutos(unittest.TestCase):
    MATCHES = [match([(10, True), (80, False)]), match([]), match([(75, True)]), match([(20, True), (88, True)])]

    def test_score_and_state(self):
        self.assertEqual(minutos.score_at(self.MATCHES[0]["goals"], 80), (1, 0))
        self.assertEqual(minutos.state_label(1, 1), "empate con goles")
        self.assertEqual(minutos.state_label(3, 0), "diferencia de 2 o más")

    def test_another_goal(self):
        r = minutos.another_goal(self.MATCHES, 70)
        self.assertEqual((r["n"], r["p"]), (4, 0.75))
        self.assertAlmostEqual(r["fair_odd"], 1 / 0.75)
        r = minutos.another_goal(self.MATCHES, 70, "diferencia de 1")
        self.assertEqual((r["n"], r["p"]), (2, 1.0))
        lo, hi = r["ci95"]
        self.assertLess(lo, 1.0)  # con 2 partidos el intervalo es ancho

    def test_live_value_falls_back_to_all_matches(self):
        r = minutos.live_value(self.MATCHES, 70, 1, 0, 2.0)
        self.assertEqual(r["state"], "todos")  # menos de 30 partidos con ese estado
        self.assertAlmostEqual(r["ev"], 0.75 * 2 - 1)

    def test_periods(self):
        shares = minutos.goals_by_period(self.MATCHES)
        self.assertAlmostEqual(sum(p["share"] for p in shares), 1.0)


class FakeJev:
    name = "fake-jev"

    def __init__(self, fail=False):
        self.fail = fail

    def decide(self, state, questions):
        if self.fail:
            raise JevError("caído")
        return JevResponse("fake", {"status": Answer("choice", "out", {"out": 0.8}, 0.7)})


class TestNoticias(unittest.TestCase):
    PLAYERS = [{"player": 1, "name": "Edinson Cavani", "team_name": "Boca"},
               {"player": 2, "name": "Lu", "team_name": "River"}]
    HEADLINES = [Headline("Cavani sufrió un desgarro y es baja ante River"), Headline("Boca entrenó en Ezeiza"),
                 Headline("Lucas Lu, figura")]

    def test_question_neutral_first(self):
        self.assertEqual(next(iter(STATUS["criteria"])), "unclear")

    def test_mentions(self):
        self.assertTrue(mentions("Cavani, titular", "Edinson Cavani"))
        self.assertFalse(mentions("Cavanilles", "Edinson Cavani"))
        self.assertFalse(mentions("Lucas Lu, figura", "Lu"))  # apellidos muy cortos: demasiado ambiguos

    def test_keywords(self):
        r = SpanishKeywords().decide({"headline": "Cavani sufrió un desgarro"}, {})
        self.assertEqual(r.answers["status"].choice, "out")
        r = SpanishKeywords().decide({"headline": "Cavani está en duda"}, {})
        self.assertEqual(r.answers["status"].choice, "doubt")

    def test_player_news_with_jev_and_fallbacks(self):
        rows = player_news(FakeJev(), self.HEADLINES, self.PLAYERS)
        self.assertEqual([(r["name"], r["status"], r["judge"]) for r in rows], [("Edinson Cavani", "out", "fake-jev")])
        rows = player_news(FakeJev(fail=True), self.HEADLINES, self.PLAYERS)
        self.assertEqual(rows[0]["judge"], SpanishKeywords.name)
        rows = player_news(MockJev(), self.HEADLINES, self.PLAYERS)
        self.assertEqual(rows[0]["status"], "out")


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        fixtures = [fixture(i, 1000 + i, 1 + (i % 2), 2 - (i % 2)) for i in range(1, 6)] + [fixture(99, 9999, 1, 2, "NS")]
        (d / "fixtures_128_2024.json").write_text(json.dumps(fixtures))
        raw = d / "raw" / "players"
        raw.mkdir(parents=True)
        for f in fixtures[:-1]:
            h, a = f["teams"]["home"]["id"], f["teams"]["away"]["id"]
            team = {1: [player(1, 90, 3, 2), player(3, 90, 1, 0, pos="D")], 2: [player(2, 90, 2, 1)]}
            (raw / f"{f['fixture']['id']}.json").write_text(json.dumps(players_body(team[h], team[a], h, a)))
        (d / "cuotas.csv").write_text("fixture,jugador,mercado,linea,cuota\n99,Jugador 1,remates_al_arco,0.5,1.90\n")
        self.cfg = FutbolConfig(data_dir=d, competitions=((128, 2024),))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(list(argv), self.cfg)
        return out.getvalue()

    def test_remates_partido_papel(self):
        out = self.run_cli("remates", "--min-minutos", "90")
        self.assertIn("Equipo 1", out)
        self.assertIn("Jugador 1", out)
        out = self.run_cli("partido", "99", "--anotar")
        self.assertIn("Jugador 1", out)
        self.assertIn("1+ remates al arco", out)
        self.assertTrue((self.cfg.data_dir / "papel.jsonl").exists())
        out = self.run_cli("papel")
        self.assertIn("pendientes 1", out)
        self.assertIn("99", self.run_cli("proximos"))

    def test_parser_and_competitions(self):
        self.assertEqual(parse_competitions("1032:2024, 128:2024"), ((1032, 2024), (128, 2024)))
        a = build_parser().parse_args(["minutos", "--minuto", "70", "--resultado", "1-0", "--cuota", "2.1"])
        self.assertEqual((a.minuto, a.resultado, a.cuota), (70, "1-0", 2.1))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["noticias", "--partido", "1"])  # falta --rss


if __name__ == "__main__":
    unittest.main()

import math
import random
import unittest

from futbol.modelo import MARKETS, ShotModel, evaluate, fit_dispersion, nb_logpmf, nb_tail, validate, walk_forward


def poisson(rng, lam):
    """Muestra de Poisson (Knuth), suficiente para tasas chicas."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def synthetic_league(seed=1, teams=10, rounds=2):
    """Liga falsa con ritmos verdaderos conocidos: delanteros rematan más, algunos equipos conceden más."""
    rng = random.Random(seed)
    squads, defense = {}, {}
    pid = 1
    for t in range(1, teams + 1):
        defense[t] = rng.uniform(0.7, 1.3)
        squads[t] = []
        for pos, (lo, hi), n in (("D", (0.05, 0.25), 4), ("M", (0.2, 0.7), 4), ("F", (0.7, 1.6), 3)):
            for _ in range(n):
                squads[t].append({"player": pid, "name": f"Jugador {pid}", "pos": pos, "sot90": rng.uniform(lo, hi)})
                pid += 1
    pairs = [(h, a) for h in squads for a in squads if h != a]
    rows, ts, fid = [], 1_700_000_000, 1
    for _ in range(rounds):
        rng.shuffle(pairs)
        for h, a in pairs:
            for team, opp, home in ((h, a, True), (a, h, False)):
                for p in squads[team]:
                    minutes = 90 if rng.random() > 0.2 else rng.choice([60, 70, 80])
                    lam = p["sot90"] * minutes / 90 * defense[opp] * (1.1 if home else 0.9)
                    sot = poisson(rng, lam)
                    shots = sot + poisson(rng, lam * 1.4)
                    rows.append({"fixture": fid, "ts": ts, "team": team, "team_name": f"Equipo {team}", "opp": opp,
                                 "opp_name": f"Equipo {opp}", "home": home, "player": p["player"], "name": p["name"],
                                 "pos": p["pos"], "minutes": minutes, "started": True, "shots": shots, "sot": sot,
                                 "goals": 0, "assists": 0, "yellow": 0, "red": 0})
            fid += 1
            ts += 3600
    return rows, squads, defense


class TestDistributions(unittest.TestCase):
    def test_tails(self):
        self.assertAlmostEqual(nb_tail(1.0, 1), 1 - math.exp(-1))
        self.assertAlmostEqual(nb_tail(1.0, 2), 1 - 2 * math.exp(-1))
        self.assertEqual(nb_tail(5.0, 0), 1.0)
        self.assertGreater(nb_tail(1.0, 3, r=1.0), nb_tail(1.0, 3))  # más dispersa: colas más pesadas
        self.assertAlmostEqual(nb_tail(1.0, 2, r=1e9), nb_tail(1.0, 2), places=5)

    def test_logpmf_sums_to_one(self):
        for r in (None, 2.0):
            self.assertAlmostEqual(sum(math.exp(nb_logpmf(x, 1.3, r)) for x in range(60)), 1.0, places=6)


class TestShotModel(unittest.TestCase):
    def setUp(self):
        self.rows, self.squads, self.defense = synthetic_league()

    def test_rates_shrink_towards_position(self):
        m = ShotModel().fit(self.rows[:2000])
        fw = [p for p in self.squads[1] if p["pos"] == "F"][0]
        df = [p for p in self.squads[1] if p["pos"] == "D"][0]
        self.assertGreater(m.rate90(fw["player"], "F", "sot"), m.rate90(df["player"], "D", "sot"))
        unknown = m.rate90(999_999, "F", "sot")
        self.assertAlmostEqual(unknown, m.prior_rate("F", "sot"))  # sin historia: el promedio de la posición

    def test_opponent_factor_follows_true_defense(self):
        m = ShotModel(decay=1.0).fit(self.rows)
        worst = max(self.defense, key=self.defense.get)
        best = min(self.defense, key=self.defense.get)
        self.assertGreater(m.opp_factor(worst, "sot"), m.opp_factor(best, "sot"))

    def test_player_table_and_starters(self):
        m = ShotModel().fit(self.rows)
        table = m.player_table(1, 2, True)
        self.assertEqual(len(table), 11)
        self.assertEqual(table[0]["pos"], "F")  # ordenado por remates esperados
        for r in table:
            self.assertGreaterEqual(r["p_sot_1"], r["p_sot_2"])
            self.assertGreaterEqual(r["p_shots_2"], r["p_shots_3"])


class TestValidation(unittest.TestCase):
    def test_no_lookahead(self):
        rows, _, _ = synthetic_league(seed=2)
        before = walk_forward(rows, burn_in=10)
        last = rows[-1]["fixture"]
        changed = [{**r, "sot": 9, "shots": 15} if r["fixture"] == last else r for r in rows]
        after = walk_forward(changed, burn_in=10)
        self.assertEqual([p["lam_sot"] for p in before], [p["lam_sot"] for p in after])

    def test_beats_naive_and_is_calibrated_on_synthetic_league(self):
        rows, _, _ = synthetic_league(seed=3, rounds=4)
        res = validate(rows, burn_in=20)
        m = res["test"]["sot_1"]
        self.assertLessEqual(m["brier_model"], m["brier_base"])
        for c in m["calibration"]:
            self.assertLess(abs(c["pred"] - c["real"]), 0.1, c)
        r = res["dispersion"]["sot"]
        self.assertTrue(r is None or r >= 20, r)  # datos Poisson: elige Poisson o casi (solo el ruido de estimar)

    def test_dispersion_detects_overdispersed_counts(self):
        rng = random.Random(5)
        preds = []
        for _ in range(3000):
            lam = rng.uniform(0.5, 2.0)
            g = rng.gammavariate(1.5, lam / 1.5)  # mezcla gamma-Poisson = binomial negativa con r=1,5
            preds.append({"sot": poisson(rng, g), "lam_sot": lam})
        self.assertIn(fit_dispersion(preds, "sot"), (1.0, 1.5, 2.0))

    def test_too_little_data(self):
        rows, _, _ = synthetic_league(seed=4)
        self.assertIn("error", validate(rows[:300], burn_in=40))

    def test_evaluate_shapes(self):
        rows, _, _ = synthetic_league(seed=6)
        preds = walk_forward(rows, burn_in=10)
        out = evaluate(preds, {"sot": None, "shots": None})
        self.assertEqual(set(out), {f"{s}_{k}" for s, k in MARKETS})


if __name__ == "__main__":
    unittest.main()

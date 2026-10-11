"""Modelo de remates por jugador (totales y al arco), sin mirar el futuro.

Para cada jugador titular, la cantidad esperada de remates en un partido es:

    ritmo por 90 del jugador × minutos esperados / 90 × factor del rival × factor de localía

- Ritmo por 90: sus remates recientes (con más peso los últimos partidos), contraídos hacia el promedio de su
  posición. Un jugador con pocos minutos queda cerca del promedio; uno con muchos, cerca de su propio ritmo.
- Minutos esperados: lo que suele jugar cuando arranca de titular (las apuestas se hacen con la formación confirmada).
- Factor del rival: cuántos remates concede ese equipo comparado con la liga, también contraído.
- La cantidad sigue una binomial negativa (más dispersa que una Poisson); la dispersión se elige con datos viejos.

`walk_forward` recorre los partidos en orden: predice cada uno solo con lo anterior y recién después lo aprende.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from itertools import groupby

STATS = ("shots", "sot")
MARKETS = (("sot", 1), ("sot", 2), ("shots", 1), ("shots", 2), ("shots", 3))
LABEL = {"sot": "remates al arco", "shots": "remates"}


def nb_tail(lam: float, k: int, r: float | None = None) -> float:
    """P(X ≥ k) para una binomial negativa de media `lam` y dispersión `r` (var = lam + lam²/r); r=None es Poisson."""
    if k <= 0:
        return 1.0
    lam = max(lam, 1e-9)
    if r is None or r <= 0 or math.isinf(r):
        term = math.exp(-lam)
        cdf = term
        for i in range(1, k):
            term *= lam / i
            cdf += term
    else:
        p = r / (r + lam)
        term = p ** r
        cdf = term
        for i in range(1, k):
            term *= (i - 1 + r) / i * (1 - p)
            cdf += term
    return min(1.0, max(0.0, 1.0 - cdf))


def nb_logpmf(x: int, lam: float, r: float | None) -> float:
    lam = max(lam, 1e-9)
    if r is None or math.isinf(r):
        return -lam + x * math.log(lam) - math.lgamma(x + 1)
    return (math.lgamma(x + r) - math.lgamma(r) - math.lgamma(x + 1) + r * math.log(r / (r + lam))
            + x * math.log(lam / (r + lam)))


class ShotModel:
    def __init__(self, decay: float = 0.92, prior_minutes: float = 270.0, opp_matches: float = 6.0,
                 start_minutes_prior: float = 75.0, dispersion: dict | None = None):
        self.decay = decay                      # peso de cada partido anterior del jugador (0,92 ≈ vida media de 8)
        self.prior_minutes = prior_minutes      # cuántos minutos "vale" el promedio de la posición
        self.opp_matches = opp_matches
        self.start_prior = start_minutes_prior
        self.dispersion = dispersion or {s: None for s in STATS}
        self.player: dict = {}
        self.pos = defaultdict(lambda: {"min": 0.0, "shots": 0.0, "sot": 0.0})
        self.conceded: dict = {}
        self.side = {True: {"n": 0.0, "shots": 0.0, "sot": 0.0}, False: {"n": 0.0, "shots": 0.0, "sot": 0.0}}
        self.roster: dict = defaultdict(list)   # equipo -> últimos partidos [(ts, [jugadores])]
        self.teams: dict = {}
        self.league_hits = defaultdict(lambda: (0.0, 0.0))  # (stat, k) -> (veces que llegó, partidos de titular)

    # -- lo que el modelo sabe hasta ahora -----------------------------------------------
    def prior_rate(self, pos: str, stat: str) -> float:
        p = self.pos.get(pos)
        if not p or p["min"] < 900:
            tot_min = sum(v["min"] for v in self.pos.values())
            return sum(v[stat] for v in self.pos.values()) / tot_min * 90 if tot_min else 1.0
        return p[stat] / p["min"] * 90

    def rate90(self, pid, pos: str, stat: str) -> float:
        s = self.player.get(pid) or {}
        k = self.prior_minutes / 90
        return (s.get(stat, 0.0) + self.prior_rate(pos, stat) * k) / (s.get("min", 0.0) / 90 + k)

    def expected_minutes(self, pid) -> float:
        s = self.player.get(pid) or {}
        return (s.get("smin", 0.0) + self.start_prior * 2) / (s.get("sn", 0.0) + 2)

    def league_avg(self, stat: str) -> float:
        n = self.side[True]["n"] + self.side[False]["n"]
        return (self.side[True][stat] + self.side[False][stat]) / n if n else 0.0

    def opp_factor(self, opp, stat: str) -> float:
        avg = self.league_avg(stat)
        if not avg:
            return 1.0
        c = self.conceded.get(opp) or {"n": 0.0, stat: 0.0}
        return ((c[stat] + avg * self.opp_matches) / (c["n"] + self.opp_matches)) / avg

    def home_factor(self, home: bool, stat: str) -> float:
        h, a = self.side[True], self.side[False]
        if h["n"] < 20 or a["n"] < 20:
            return 1.0
        rh, ra = h[stat] / h["n"], a[stat] / a["n"]
        return (rh if home else ra) / ((rh + ra) / 2) if rh + ra else 1.0

    def expected(self, pid, pos: str, opp, home: bool, stat: str, minutes: float | None = None) -> float:
        mins = self.expected_minutes(pid) if minutes is None else minutes
        return self.rate90(pid, pos, stat) * mins / 90 * self.opp_factor(opp, stat) * self.home_factor(home, stat)

    def prob(self, lam: float, stat: str, k: int) -> float:
        return nb_tail(lam, k, self.dispersion.get(stat))

    def baseline(self, pid, stat: str, k: int) -> float:
        """Lo que haría alguien "a ojo": en qué porcentaje de sus partidos de titular llegó a k (contraído)."""
        s = self.player.get(pid) or {}
        hits, n = s.get(f"hit_{stat}_{k}", 0.0), s.get("sn", 0.0)
        h, n_league = self.league_hits.get((stat, k), (0.0, 0.0))
        prior = h / n_league if n_league else 0.5
        return (hits + prior * 3) / (n + 3)

    # -- aprender un partido ---------------------------------------------------------------
    def update(self, fixture_rows: list[dict]) -> None:
        d = self.decay
        totals: dict = defaultdict(lambda: {"shots": 0.0, "sot": 0.0})
        meta = {}
        for r in fixture_rows:
            s = self.player.setdefault(r["player"], {"min": 0.0, "shots": 0.0, "sot": 0.0, "smin": 0.0, "sn": 0.0})
            for key in ("min", "shots", "sot"):
                s[key] = s[key] * d + (r["minutes"] if key == "min" else r[key])
            if r["started"]:
                s["smin"] = s["smin"] * d + r["minutes"]
                s["sn"] = s["sn"] * d + 1
                for stat, k in MARKETS:
                    hk = f"hit_{stat}_{k}"
                    s[hk] = s.get(hk, 0.0) * d + (r[stat] >= k)
                    h, n = self.league_hits[(stat, k)]
                    self.league_hits[(stat, k)] = (h + (r[stat] >= k), n + 1)
            s.update(name=r["name"], pos=r["pos"] or s.get("pos", ""), team=r["team"], ts=r["ts"])
            p = self.pos[r["pos"]]
            p["min"] += r["minutes"]
            p["shots"] += r["shots"]
            p["sot"] += r["sot"]
            totals[r["team"]]["shots"] += r["shots"]
            totals[r["team"]]["sot"] += r["sot"]
            meta[r["team"]] = (r["opp"], r["home"], r["team_name"])
        for team, (opp, home, name) in meta.items():
            c = self.conceded.setdefault(opp, {"n": 0.0, "shots": 0.0, "sot": 0.0})
            c["n"] = c["n"] * d + 1
            for stat in STATS:
                c[stat] = c[stat] * d + totals[team][stat]
                self.side[home][stat] += totals[team][stat]
            self.side[home]["n"] += 1
            self.teams[team] = name
            players = [{"player": r["player"], "name": r["name"], "pos": r["pos"], "started": r["started"],
                        "minutes": r["minutes"]} for r in fixture_rows if r["team"] == team]
            self.roster[team] = (self.roster[team] + [(fixture_rows[0]["ts"], players)])[-5:]

    def fit(self, rows: list[dict]) -> "ShotModel":
        for _, frs in groupby(rows, key=lambda r: r["fixture"]):
            self.update(list(frs))
        return self

    # -- partido próximo -------------------------------------------------------------------
    def likely_starters(self, team) -> list[dict]:
        """Titulares probables: los que arrancaron en la mayoría de los últimos partidos del equipo."""
        recent = self.roster.get(team) or []
        count: dict = defaultdict(int)
        info = {}
        for _, players in recent:
            for p in players:
                if p["started"]:
                    count[p["player"]] += 1
                    info[p["player"]] = p
        need = max(1, (len(recent) + 1) // 2)
        return [info[pid] for pid, c in sorted(count.items(), key=lambda kv: -kv[1]) if c >= need][:11]

    def player_table(self, team, opp, home: bool, players: list[dict] | None = None) -> list[dict]:
        out = []
        for p in players or self.likely_starters(team):
            pid, pos = p["player"], p.get("pos") or (self.player.get(p["player"]) or {}).get("pos", "")
            row = {"player": pid, "name": p.get("name") or (self.player.get(pid) or {}).get("name"), "pos": pos,
                   "minutes": round(self.expected_minutes(pid))}
            for stat in STATS:
                lam = self.expected(pid, pos, opp, home, stat)
                row[f"lam_{stat}"] = lam
                row[f"rate90_{stat}"] = self.rate90(pid, pos, stat)
            for stat, k in MARKETS:
                row[f"p_{stat}_{k}"] = self.prob(row[f"lam_{stat}"], stat, k)
            out.append(row)
        return sorted(out, key=lambda r: -r["lam_shots"])


# -- validación ----------------------------------------------------------------------------
def walk_forward(rows: list[dict], burn_in: int = 40, **kw) -> list[dict]:
    """Predice cada titular con lo aprendido hasta el partido anterior (sin lookahead)."""
    model = ShotModel(**kw)
    preds = []
    for i, (fid, frs) in enumerate(groupby(rows, key=lambda r: r["fixture"])):
        frs = list(frs)
        if i >= burn_in:
            for r in frs:
                if not r["started"] or not r["pos"] or r["pos"] == "G":
                    continue
                p = {"fixture": fid, "ts": r["ts"], "player": r["player"], "name": r["name"],
                     "shots": int(r["shots"]), "sot": int(r["sot"])}
                for stat in STATS:
                    p[f"lam_{stat}"] = model.expected(r["player"], r["pos"], r["opp"], r["home"], stat)
                for stat, k in MARKETS:
                    p[f"base_{stat}_{k}"] = model.baseline(r["player"], stat, k)
                preds.append(p)
        model.update(frs)
    return preds


def fit_dispersion(preds: list[dict], stat: str) -> float | None:
    """Elige la dispersión que mejor explica los conteos (máxima verosimilitud en una grilla); None = Poisson."""
    grid = [None, 50.0, 20.0, 10.0, 6.0, 4.0, 3.0, 2.0, 1.5, 1.0]
    best = max(grid, key=lambda r: sum(nb_logpmf(p[stat], p[f"lam_{stat}"], r) for p in preds))
    return best


def evaluate(preds: list[dict], dispersion: dict) -> dict:
    """Brier y log-loss del modelo contra la línea base "a ojo", y tabla de calibración."""
    out = {}
    for stat, k in MARKETS:
        ys = [1.0 if p[stat] >= k else 0.0 for p in preds]
        pm = [nb_tail(p[f"lam_{stat}"], k, dispersion.get(stat)) for p in preds]
        pb = [p[f"base_{stat}_{k}"] for p in preds]

        def brier(ps):
            return statistics.fmean((a - y) ** 2 for a, y in zip(ps, ys))

        def logloss(ps):
            return -statistics.fmean(math.log(min(max(a if y else 1 - a, 1e-6), 1)) for a, y in zip(ps, ys))

        calib = []
        for lo, hi in ((0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
            sel = [(a, y) for a, y in zip(pm, ys) if lo <= a < hi]
            if len(sel) >= 20:
                calib.append({"range": (lo, min(hi, 1.0)), "n": len(sel), "pred": statistics.fmean(a for a, _ in sel),
                              "real": statistics.fmean(y for _, y in sel)})
        out[f"{stat}_{k}"] = {"n": len(ys), "rate": statistics.fmean(ys), "brier_model": brier(pm),
                              "brier_base": brier(pb), "logloss_model": logloss(pm), "logloss_base": logloss(pb),
                              "calibration": calib}
    return out


def validate(rows: list[dict], train_share: float = 0.6, burn_in: int = 40) -> dict:
    """Dispersión elegida con el primer 60 % de las predicciones; métricas informadas sobre el 40 % restante."""
    preds = walk_forward(rows, burn_in=burn_in)
    if len(preds) < 200:
        return {"error": f"muy pocos datos ({len(preds)} titulares con historia): sincronizá más partidos"}
    cut = int(len(preds) * train_share)
    train, test = preds[:cut], preds[cut:]
    disp = {stat: fit_dispersion(train, stat) for stat in STATS}
    return {"n_train": len(train), "n_test": len(test), "dispersion": disp, "test": evaluate(test, disp),
            "from_ts": test[0]["ts"], "to_ts": test[-1]["ts"]}

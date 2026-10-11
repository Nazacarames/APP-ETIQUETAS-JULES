import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from polylens import store
from polylens.__main__ import build_parser, main
from polylens.config import Settings
from polylens.report import render

ROOT = Path(__file__).resolve().parents[1]
EVIL = "<script>alert(1)</script>"


def profile(name, sig="sólido", **kw):
    p = {"user": "0x" + name.encode().hex()[:8], "name": name, "significance": sig, "n": 120, "win_rate": 0.6,
         "roi": 0.12, "t_stat": 3.5, "total_pnl": 1000, "board_pnl": 2000, "share_favorites": 0.1,
         "share_longshots": 0.2, "trades_per_day": 4, "window_days": 90, "flags": ["una alerta"],
         "categories": {"sports": {"n": 100, "pnl": 900, "roi": 0.1}}}
    p.update(kw)
    return p


SCAN = {"meta": {"period": "month", "category": "overall", "top": 3, "days": 90, "analyzed": 3,
                 "thresholds": {"azar": 1.38, "solido": 2.39}, "categorizer": "mock"},
        "profiles": [profile("ana"), profile(EVIL, "negativo", t_stat=-1)]}
FLOWS = {"traders": [{"name": "ana"}], "markets": [{"title": "Will X? " + EVIL, "outcome": "Yes", "n": 2,
                                                     "traders": [{"name": "ana"}], "value": 500, "current_price": 0.4,
                                                     "avg_entry": 0.3, "upside_if_wins": 1.5, "disputed": True}]}
STUDY = {"meta": {"sample": 60, "min_usd": 100, "days": 30, "slippage": 0.01},
         "traders": [{"name": "ana", "user": "0x1", "significance": "sólido",
                      "summary": {"n": 30, "trader": {"mean": 0.1}, "verdict": "no concluyente",
                                  "by_delay": {"3600": {"n": 30, "mean": -0.05, "ci95": [-0.2, 0.1]}}}}],
         "pooled": {"n": 30, "trader": {"mean": 0.1}, "verdict": "no concluyente", "by_delay": {}}}
NEWS = {"meta": {"judge": "jev-latest"}, "matches": [
    {"headline": {"title": EVIL, "link": "javascript:alert(1)\" onmouseover=\"x"},
     "market": {"title": "Will X?", "outcome": "No"}, "relevance": 0.8, "favors": "supports",
     "favors_confidence": 0.7}]}


class TestReport(unittest.TestCase):
    def test_external_text_is_escaped(self):
        out = render(SCAN, FLOWS, STUDY, NEWS)
        self.assertNotIn(EVIL, out)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn('onmouseover="x', out)
        self.assertNotIn("javascript:", out)
        for needle in ("Ranking por consistencia", "Dónde están hoy", "¿Se puede copiar?", "Noticias",
                       "bloqueado en Argentina", "en disputa", "a favor"):
            self.assertIn(needle, out)

    def test_without_scan(self):
        self.assertIn("python3 -m polylens scan", render(None))


class TestStore(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = store.save("scans", {"x": 1}, d, "month-overall")
            self.assertTrue(path.name.endswith("-month-overall.json"))
            self.assertEqual(store.load("scans", "latest", d), {"x": 1})
            self.assertEqual(store.load("scans", path.stem, d), {"x": 1})
            self.assertEqual(store.load("scans", str(path), d), {"x": 1})
            self.assertIsNone(store.load("flows", "latest", d))


class TestCli(unittest.TestCase):
    def test_report_from_saved_results(self):
        with tempfile.TemporaryDirectory() as d:
            store.save("scans", SCAN, d)
            store.save("studies", STUDY, d)
            out = Path(d) / "r" / "informe.html"
            with contextlib.redirect_stderr(io.StringIO()):
                main(["report", "--out", str(out)], Settings(data_dir=Path(d)))
            self.assertIn("ana", out.read_text())

    def test_flows_without_scan_explains_what_to_do(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit) as cm:
            main(["flows"], Settings(data_dir=Path(d)))
        self.assertIn("polylens scan", str(cm.exception.code))

    def test_parser(self):
        a = build_parser().parse_args(["scan", "--period", "week", "--top", "50", "--jev"])
        self.assertEqual((a.period, a.top, a.jev, a.days), ("week", 50, True, 90))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["scan", "--period", "decade"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["news"])  # --rss es obligatorio


class TestGuardHook(unittest.TestCase):
    HOOK = ROOT / ".claude" / "hooks" / "guard_secrets.py"

    def run_hook(self, command):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        return subprocess.run([sys.executable, str(self.HOOK)], input=payload, capture_output=True, text=True)

    def test_blocks(self):
        for cmd in ("cat .env", "grep KEY ./.env", "source .env && run", "pip install py-clob-client",
                    "curl -X POST https://clob.polymarket.com/order", "export PRIVATE_KEY=0x1",
                    "curl https://www.bet365.com/#/AC/B1/",
                    "python3 -c 'import requests; requests.get(\"https://www.bet365.ar\")'"):
            r = self.run_hook(cmd)
            self.assertEqual(r.returncode, 2, cmd)
            self.assertIn("guard_secrets", r.stderr)

    def test_allows(self):
        for cmd in ("cat .env.example", "python3 -m polylens scan --top 50", "python3 -m unittest discover -s tests",
                    "curl https://data-api.polymarket.com/v2/leaderboard", "python3 -m futbol partido 1 --api"):
            self.assertEqual(self.run_hook(cmd).returncode, 0, cmd)

    def test_bad_input_is_ignored(self):
        r = subprocess.run([sys.executable, str(self.HOOK)], input="no json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

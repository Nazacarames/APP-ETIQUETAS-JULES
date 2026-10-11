import os
import tempfile
import unittest
from pathlib import Path

from jevtrader.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["GATE_FAIL_CLOSED", "GATE_SHADOW", "JEV_SAMPLES", "BINANCE_ENV", "LIVE_TRADING", "TYPESAFE_API_KEY",
        "RISK_PER_TRADE", "JEV_TIMEOUT_S", "JEV_MODEL", "BINANCE_API_KEY", "BINANCE_API_SECRET"]


class TestDotenv(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k) for k in list(os.environ) if k in KEYS or k.startswith(("GATE_", "RISK_", "COST_", "JEV_"))}

    def tearDown(self):
        for k in list(os.environ):
            if k in KEYS or k.startswith(("GATE_", "RISK_", "COST_", "JEV_")):
                del os.environ[k]
        os.environ.update(self.saved)

    def test_env_example_loads_with_safe_defaults(self):
        """Copiar .env.example tal cual tiene que dar la configuración segura (comentarios incluidos)."""
        s = load_settings(ROOT / ".env.example")
        self.assertTrue(s.gate.fail_closed)
        self.assertFalse(s.gate.shadow)
        self.assertFalse(s.live_trading)
        self.assertEqual(s.jev.samples, 1)
        self.assertEqual(s.jev.timeout_s, 3.0)
        self.assertEqual(s.risk.risk_per_trade, 0.01)
        self.assertTrue(s.jev.use_mock)  # sin clave
        self.assertEqual(os.environ.get("BINANCE_ENV"), "demo")

    def test_quotes_and_hash_inside_value(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('TYPESAFE_API_KEY="abc#123"  # comentario\nJEV_MODEL=jev#1\n')
            s = load_settings(p)
        self.assertEqual(s.jev.api_key, "abc#123")
        self.assertEqual(s.jev.model, "jev#1")  # '#' sin espacio antes no es comentario


if __name__ == "__main__":
    unittest.main()

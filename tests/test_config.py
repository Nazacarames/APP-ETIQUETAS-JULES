import os
import tempfile
import unittest
from pathlib import Path

from polylens.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("JEV_", "TYPESAFE_", "DATA_DIR", "CACHE_TTL_S", "POLY_")


class TestDotenv(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith(PREFIXES)}

    def tearDown(self):
        for k in list(os.environ):
            if k.startswith(PREFIXES):
                del os.environ[k]
        os.environ.update(self.saved)

    def test_env_example_loads_with_defaults(self):
        """Copiar .env.example tal cual tiene que funcionar (comentarios al final de línea incluidos)."""
        s = load_settings(ROOT / ".env.example")
        self.assertTrue(s.jev.use_mock)  # sin clave
        self.assertEqual(s.jev.model, "jev-latest")
        self.assertEqual(s.jev.samples, 1)
        self.assertEqual(s.jev.timeout_s, 10.0)
        self.assertEqual(s.data_dir, Path("data"))
        self.assertEqual(s.cache_ttl_s, 21600.0)
        self.assertEqual(s.min_interval_s, 0.25)

    def test_quotes_and_hash_inside_value(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.env"
            p.write_text('TYPESAFE_API_KEY="abc#123"  # comentario\nJEV_MODEL=jev#1\nJEV_MOCK=si\n')
            s = load_settings(p)
        self.assertEqual(s.jev.api_key, "abc#123")
        self.assertEqual(s.jev.model, "jev#1")  # '#' sin espacio antes no es comentario
        self.assertTrue(s.jev.use_mock)

    def test_environment_wins_over_file(self):
        os.environ["JEV_SAMPLES"] = "3"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.env"
            p.write_text("JEV_SAMPLES=5\n")
            self.assertEqual(load_settings(p).jev.samples, 3)

    def test_missing_file_is_fine(self):
        self.assertTrue(load_settings(ROOT / "no-existe.env").jev.use_mock)


if __name__ == "__main__":
    unittest.main()

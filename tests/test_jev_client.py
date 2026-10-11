import tempfile
import unittest
from pathlib import Path

from polylens.config import JevConfig
from polylens.jev_client import (AnswerCache, JevClient, JevError, MockJev, choice, choice_confidence, make_client,
                                 noul, parse_response, score, score_confidence)

# Respuesta de ejemplo de docs.typesafe.ai/introduction/quickstart
DOCS_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "department": {"type": "choice", "choice": "technical", "confidence": 0.78,
                       "probabilities": {"technical": 0.85, "sales": 0.0, "billing": 0.15}},
        "frustration": {"type": "score", "score": 1.0, "confidence": 1.0,
                        "legend": {"0": "Calm", "1": "Frustrated", "2": "Angry"},
                        "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0}},
        "is_urgent": {"type": "noul", "noul": 1.0},
    },
    "usage": {"input_tokens": 392, "output_tokens": 65},
}


def body(cat_p=0.9, rel=0.2):
    return {"model": "jev-1.13.0", "answers": {
        "category": {"type": "choice", "choice": "politics",
                     "probabilities": {"other": 1 - cat_p, "politics": cat_p}},
        "relevant": {"type": "noul", "noul": rel},
    }}


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload))
        return self.responses.pop(0)


def cfg(**kw):
    return JevConfig(api_key="test-key", **kw)


class TestConfidence(unittest.TestCase):
    def test_choice_formula_matches_docs(self):
        self.assertAlmostEqual(choice_confidence({"a": 0.6, "b": 0.3, "c": 0.1}), 0.4)
        self.assertAlmostEqual(choice_confidence({"a": 0.6, "b": 0.2, "c": 0.2}), 0.4)
        self.assertAlmostEqual(choice_confidence({"t": 0.85, "s": 0.0, "b": 0.15}), 0.775)  # docs: 0.78

    def test_score_formula_matches_docs(self):
        self.assertAlmostEqual(score_confidence([0.0, 0.5, 0.5]), 0.25)
        self.assertAlmostEqual(score_confidence([0.5, 0.0, 0.5]), 0.0)
        self.assertAlmostEqual(score_confidence([0.0, 1.0, 0.0]), 1.0)


class TestParsing(unittest.TestCase):
    def test_docs_response(self):
        r = parse_response(DOCS_RESPONSE)
        self.assertEqual(r.model, "jev-1.13.0")
        self.assertEqual(r["department"].choice, "technical")
        self.assertEqual(r["frustration"].value, 1.0)
        self.assertEqual(r["is_urgent"].p, 1.0)
        self.assertEqual(r["is_urgent"].confidence, 1.0)  # |2p-1|

    def test_malformed(self):
        with self.assertRaises(JevError):
            parse_response({"nope": 1})

    def test_builders_validate(self):
        with self.assertRaises(ValueError):
            choice("x", {"only": None})
        with self.assertRaises(ValueError):
            score("x", ["a"] * 11)
        self.assertEqual(noul("q", true="yes")["criteria"], {"true": "yes", "false": ""})


class TestClient(unittest.TestCase):
    def test_request_shape_and_retry(self):
        t = FakeTransport([(429, {"error": "rate"}), (529, {}), (200, DOCS_RESPONSE)])
        c = JevClient(cfg(max_retries=2), transport=t, sleep=lambda s: None)
        r = c.decide("hola", {"q": noul("x")})
        self.assertEqual(r["department"].choice, "technical")
        self.assertEqual(len(t.calls), 3)
        url, headers, payload = t.calls[0]
        self.assertEqual(url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(payload["model"], "jev-latest")
        self.assertEqual(payload["state"], "hola")

    def test_no_retry_on_401(self):
        t = FakeTransport([(401, {"error": "bad key"}), (200, DOCS_RESPONSE)])
        c = JevClient(cfg(max_retries=3), transport=t, sleep=lambda s: None)
        with self.assertRaises(JevError):
            c.decide("x", {"q": noul("x")})
        self.assertEqual(len(t.calls), 1)

    def test_gives_up_after_retries(self):
        t = FakeTransport([(529, {})] * 3)
        c = JevClient(cfg(max_retries=2), transport=t, sleep=lambda s: None)
        with self.assertRaises(JevError):
            c.decide("x", {"q": noul("x")})

    def test_cache_replay(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cache.jsonl"
            t = FakeTransport([(200, DOCS_RESPONSE)])
            JevClient(cfg(), cache=AnswerCache(path), transport=t).decide("s", {"q": noul("x")})
            t2 = FakeTransport([])
            r = JevClient(cfg(), cache=AnswerCache(path), transport=t2).decide("s", {"q": noul("x")})
            self.assertTrue(r.cached)
            self.assertEqual(t2.calls, [])

    def test_samples_are_averaged(self):
        t = FakeTransport([(200, body(0.9, 0.2)), (200, body(0.5, 0.4))])
        r = JevClient(cfg(samples=2), transport=t).decide("s", {"q": noul("x")})
        self.assertAlmostEqual(r["category"].probabilities["politics"], 0.7)
        self.assertAlmostEqual(r["relevant"].p, 0.3)

    def test_make_client_without_key_is_mock(self):
        self.assertIsInstance(make_client(JevConfig()), MockJev)
        self.assertIsInstance(make_client(JevConfig(api_key="k", force_mock=True)), MockJev)
        self.assertIsInstance(make_client(cfg()), JevClient)


class TestMock(unittest.TestCase):
    def test_category_by_keywords(self):
        q = {"category": choice("Which category?", {"other": "none", "sports": "s", "crypto": "c"})}
        self.assertEqual(MockJev().decide("Will Bitcoin reach 150k?", q)["category"].choice, "crypto")
        self.assertEqual(MockJev().decide("Lakers vs. Celtics", q)["category"].choice, "sports")
        self.assertEqual(MockJev().decide("Something unrelated", q)["category"].choice, "other")

    def test_relevance_by_word_overlap(self):
        q = {"relevant": noul("Is it relevant?")}
        hi = MockJev().decide({"headline": "Iran blockade tightens", "market": "Iran blockade ends?"}, q)
        lo = MockJev().decide({"headline": "Rain in Paris", "market": "Iran blockade ends?"}, q)
        self.assertGreater(hi["relevant"].p, lo["relevant"].p)

    def test_unknown_questions_are_uniform_and_named(self):
        r = MockJev().decide("x", {"z": choice("?", {"a": 1, "b": 2}), "s": score("?", ["lo", "mid", "hi"])})
        self.assertEqual(r["z"].confidence, 0.0)
        self.assertEqual(r["s"].value, 1.0)
        self.assertIn("NO es Jev", r.model)


if __name__ == "__main__":
    unittest.main()

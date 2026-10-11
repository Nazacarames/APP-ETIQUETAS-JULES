import tempfile
import unittest
from pathlib import Path

from jevtrader.config import GateConfig, JevConfig
from jevtrader.jev_client import (AnswerCache, JevClient, JevError, MockJev, choice, choice_confidence, noul,
                                  parse_response, score, score_confidence)
from jevtrader.judge import JevJudge

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


def entry_body(regime="trending_up", regime_p=0.9, setup=(0.0, 0.1, 0.9), overext=0.1):
    others = {k: (1 - regime_p) / 3 for k in ("disorderly", "range_bound", "trending_down", "trending_up") if k != regime}
    probs = {regime: regime_p, **others}
    return {"model": "jev-1.13.0", "answers": {
        "regime": {"type": "choice", "choice": regime, "probabilities": probs},
        "setup_quality": {"type": "score", "score": sum(k * p for k, p in enumerate(setup)),
                          "probabilities": {str(k): p for k, p in enumerate(setup)}},
        "overextended": {"type": "noul", "noul": overext},
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
        a = entry_body(regime_p=0.9, setup=(0.0, 0.0, 1.0), overext=0.2)
        b = entry_body(regime_p=0.5, setup=(0.0, 1.0, 0.0), overext=0.4)
        t = FakeTransport([(200, a), (200, b)])
        r = JevClient(cfg(samples=2), transport=t).decide("s", {"q": noul("x")})
        self.assertAlmostEqual(r["regime"].probabilities["trending_up"], 0.7)
        self.assertAlmostEqual(r["setup_quality"].value, 1.5)
        self.assertAlmostEqual(r["overextended"].p, 0.3)


class TestJudge(unittest.TestCase):
    def judge(self, responses, **gate):
        t = FakeTransport(responses)
        return JevJudge(JevClient(cfg(max_retries=0), transport=t, sleep=lambda s: None), GateConfig(**gate))

    def test_fail_closed(self):
        v = self.judge([(503, {})]).review_entry({"x": "y"})
        self.assertFalse(v.allow)
        self.assertEqual(v.size_mult, 0.0)

    def test_fail_open_is_opt_in(self):
        v = self.judge([(503, {})], fail_closed=False).review_entry({"x": "y"})
        self.assertTrue(v.allow)
        self.assertEqual(v.size_mult, 0.5)

    def test_allows_confident_uptrend_full_size(self):
        v = self.judge([(200, entry_body())]).review_entry({"x": "y"})
        self.assertTrue(v.allow, v.reasons)
        self.assertEqual(v.size_mult, 1.0)

    def test_vetoes_wrong_regime(self):
        v = self.judge([(200, entry_body(regime="range_bound"))]).review_entry({"x": "y"})
        self.assertFalse(v.allow)

    def test_vetoes_weak_setup(self):
        v = self.judge([(200, entry_body(setup=(0.7, 0.3, 0.0)))]).review_entry({"x": "y"})
        self.assertFalse(v.allow)

    def test_halves_when_overextended(self):
        v = self.judge([(200, entry_body(overext=0.9))]).review_entry({"x": "y"})
        self.assertTrue(v.allow)
        self.assertEqual(v.size_mult, 0.5)

    def test_shadow_mode_records_veto_but_trades(self):
        v = self.judge([(200, entry_body(regime="range_bound"))], shadow=True).review_entry({"x": "y"})
        self.assertTrue(v.allow)
        self.assertEqual(v.size_mult, 1.0)
        self.assertFalse(v.summary()["shadow"]["allow"])
        self.assertIn("vetaría", v.reasons[0])

    def test_shadow_mode_survives_api_errors(self):
        v = self.judge([(503, {})], shadow=True).review_entry({"x": "y"})
        self.assertTrue(v.allow)
        self.assertFalse(v.shadow["allow"])

    def test_news_question_added_only_with_headlines(self):
        t = FakeTransport([(200, {**entry_body(), "answers": {**entry_body()["answers"],
                                                              "news_risk": {"type": "noul", "noul": 0.9}}})])
        j = JevJudge(JevClient(cfg(), transport=t), GateConfig())
        v = j.review_entry({"x": "y"}, asset="BTC", headlines=["Exchange hacked"])
        self.assertIn("news_risk", t.calls[0][2]["questions"])
        self.assertFalse(v.allow)


class TestMock(unittest.TestCase):
    def test_mock_has_same_shape(self):
        from jevtrader.questions import entry_review
        r = MockJev().decide({"context": "x"}, entry_review())
        self.assertEqual(set(r.answers), {"regime", "setup_quality", "overextended"})
        self.assertIn("NO es Jev", r.model)


if __name__ == "__main__":
    unittest.main()

import threading
import unittest

from polylens.categories import QUESTION, Categorizer, event_text
from polylens.jev_client import Answer, JevError, JevResponse
from polylens.profiles import position_result


class FakeClient:
    name = "fake"

    def __init__(self, answer="tech", confidence=0.9, fail=False):
        self.answer, self.confidence, self.fail = answer, confidence, fail
        self.calls = 0
        self.lock = threading.Lock()

    def decide(self, state, questions):
        with self.lock:
            self.calls += 1
        if self.fail:
            raise JevError("caído")
        a = Answer("choice", self.answer, {self.answer: 1.0}, self.confidence)
        return JevResponse("fake", {"category": a})


def position(slug, title):
    return position_result({"avg_price": 0.5, "total_size": 100, "total_pnl": 1, "event_slug": slug, "title": title})


class TestCategorizer(unittest.TestCase):
    def test_question_puts_neutral_option_first(self):
        self.assertEqual(next(iter(QUESTION["criteria"])), "other")

    def test_keywords_without_api_key(self):
        c = Categorizer()
        self.assertEqual(c(position("nba-finals", "Lakers vs. Celtics")), "sports")
        self.assertEqual(c(position("btc-price", "Will Bitcoin reach 150k?")), "crypto")
        self.assertIn("NO es Jev", c.name)

    def test_one_question_per_event(self):
        fake = FakeClient()
        c = Categorizer(fake)
        c.classify_many([("ev", "A"), ("ev", "B"), ("ev2", "C")])
        self.assertEqual(fake.calls, 2)
        self.assertEqual(c(position("ev", "otra")), "tech")
        self.assertEqual(fake.calls, 2)

    def test_call_cap_falls_back_to_keywords(self):
        fake = FakeClient(answer="tech")
        c = Categorizer(fake, max_calls=1, workers=1)
        c.classify_many([("e1", "Will Bitcoin reach 150k?"), ("e2", "Will Bitcoin reach 200k?")])
        self.assertEqual(fake.calls, 1)
        self.assertEqual(sorted(c.cache.values()), ["crypto", "tech"])

    def test_errors_and_low_confidence_fall_back(self):
        failing = Categorizer(FakeClient(fail=True))
        self.assertEqual(failing(position("x", "Fed decision in October")), "economy")
        self.assertEqual(failing.errors, 1)
        unsure = Categorizer(FakeClient(answer="tech", confidence=0.05))
        self.assertEqual(unsure(position("y", "Fed decision in October")), "economy")

    def test_event_text(self):
        self.assertEqual(event_text("fed-decision-in-october", "25 bps cut?"),
                         "Event: fed decision in october. Market: 25 bps cut?")


if __name__ == "__main__":
    unittest.main()

import unittest

from polylens.jev_client import Answer, JevError, JevResponse, MockJev
from polylens.news import (QUESTIONS, Headline, candidate_pairs, judge_pairs, market_text, news_scan, parse_feed,
                           words)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Iran blockade tightens as talks stall</title><link>https://n.example/1</link>
<pubDate>Sat, 10 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Rain expected in Paris</title><link>https://n.example/2</link></item>
<item><title></title></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Fed signals pause on rates</title><link href="https://a.example/x"/>
<updated>2026-10-10T12:00:00Z</updated></entry></feed>"""

MARKETS = [
    {"title": "US announces end of Iranian blockade by October 31?", "outcome": "No", "event_slug": "iran-blockade",
     "current_price": 0.86, "n": 2, "value": 1000},
    {"title": "Fed decision in October: pause?", "outcome": "Yes", "event_slug": "fed-october", "current_price": 0.7,
     "n": 1, "value": 500},
]


class FakeJudge:
    name = "fake-jev"

    def __init__(self, rel=0.8, fav="against", fail_on=None):
        self.rel, self.fav, self.fail_on = rel, fav, fail_on
        self.states = []

    def decide(self, state, questions):
        self.states.append(state)
        if self.fail_on and self.fail_on in state["headline"]:
            raise JevError("caído")
        probs = {"unclear": 0.1, "supports": 0.1, "against": 0.1, self.fav: 0.8}
        return JevResponse("fake", {"relevant": Answer("noul", self.rel, {}, 0.6),
                                    "favors": Answer("choice", self.fav, probs, 0.7)})


class TestFeeds(unittest.TestCase):
    def test_rss(self):
        hs = parse_feed(RSS, source="rss")
        self.assertEqual([h.title for h in hs], ["Iran blockade tightens as talks stall", "Rain expected in Paris"])
        self.assertEqual(hs[0].link, "https://n.example/1")
        self.assertEqual(hs[0].published, 1791626400)
        self.assertIsNone(hs[1].published)

    def test_atom(self):
        h = parse_feed(ATOM)[0]
        self.assertEqual((h.title, h.link, h.published), ("Fed signals pause on rates", "https://a.example/x", 1791633600))

    def test_garbage(self):
        self.assertEqual(parse_feed("<html><body>no"), [])


class TestMatching(unittest.TestCase):
    def test_words_drop_noise(self):
        self.assertEqual(words("Will Iran end the blockade by October 2026?"), {"iran", "blockade"})

    def test_questions_put_unclear_first(self):
        self.assertEqual(next(iter(QUESTIONS["favors"]["criteria"])), "unclear")
        self.assertIn("Outcome held by the tracked traders: No", market_text(MARKETS[0]))

    def test_candidate_pairs_need_overlap(self):
        hs = parse_feed(RSS) + parse_feed(ATOM)
        pairs = candidate_pairs(hs, MARKETS, min_overlap=2)
        got = {(h.title, m["event_slug"]) for h, m, _ in pairs}
        self.assertEqual(got, {("Iran blockade tightens as talks stall", "iran-blockade")})
        self.assertEqual(len(candidate_pairs(hs, MARKETS, min_overlap=1)), 2)
        self.assertEqual(len(candidate_pairs(hs, MARKETS, min_overlap=1, max_pairs=1)), 1)


class TestJudging(unittest.TestCase):
    def test_judge_pairs_filters_and_drops_errors(self):
        pairs = [(Headline("Iran blockade tightens"), MARKETS[0], 2), (Headline("Fed pause"), MARKETS[1], 1)]
        rows = judge_pairs(FakeJudge(fail_on="Fed"), pairs, workers=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["favors"], rows[0]["relevance"]), ("against", 0.8))
        self.assertEqual(judge_pairs(FakeJudge(rel=0.2), pairs, min_relevance=0.5), [])

    def test_news_scan_dedupes_and_survives_bad_feeds(self):
        def fetch(url):
            if url == "bad":
                raise OSError("timeout")
            return RSS
        judge = FakeJudge()
        res = news_scan(judge, ["a", "a2", "bad"], MARKETS, fetch=fetch, min_overlap=2)
        self.assertEqual(res["meta"]["headlines"], 2)
        self.assertIn("bad", res["meta"]["errors"])
        self.assertEqual(res["meta"]["judge"], "fake-jev")
        self.assertEqual(len(res["matches"]), 1)
        self.assertEqual(judge.states[0]["headline"], "Iran blockade tightens as talks stall")

    def test_mock_never_claims_a_direction(self):
        res = news_scan(MockJev(), ["a"], MARKETS, fetch=lambda u: RSS, min_relevance=0.0)
        self.assertTrue(all(r["favors"] == "unclear" for r in res["matches"]))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
import urllib.error

from polylens.http import Http, HttpError, build_url


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if len(r) == 3 else (*r, {})


def http(responses, **kw):
    t = FakeTransport(responses)
    sleeps = []
    h = Http(transport=t, sleep=sleeps.append, min_interval_s=0, **kw)
    return h, t, sleeps


class TestBuildUrl(unittest.TestCase):
    def test_lists_repeat_bools_lowercase_none_dropped(self):
        url = build_url("https://x/m", {"ids": ["a", "b"], "closed": True, "skip": None, "limit": 5})
        self.assertEqual(url, "https://x/m?closed=true&ids=a&ids=b&limit=5")

    def test_no_params(self):
        self.assertEqual(build_url("https://x/m", {"a": None}), "https://x/m")


class TestGet(unittest.TestCase):
    def test_disk_cache_avoids_second_request(self):
        with tempfile.TemporaryDirectory() as d:
            h, t, _ = http([(200, {"ok": 1})], cache_dir=d)
            self.assertEqual(h.get("https://x/a", {"q": 1}), {"ok": 1})
            self.assertEqual(h.get("https://x/a", {"q": 1}), {"ok": 1})
            self.assertEqual((h.requests, h.cache_hits, len(t.urls)), (1, 1, 1))

    def test_expired_cache_refetches(self):
        with tempfile.TemporaryDirectory() as d:
            now = [1000.0]
            h, t, _ = http([(200, 1), (200, 2)], cache_dir=d, clock=lambda: now[0])
            self.assertEqual(h.get("https://x/a", ttl=60), 1)
            now[0] += 61
            self.assertEqual(h.get("https://x/a", ttl=60), 2)

    def test_retries_rate_limit_honoring_retry_after(self):
        h, t, sleeps = http([(429, "slow", {"Retry-After": "7"}), (503, "down"), (200, {"ok": 1})])
        self.assertEqual(h.get("https://x/a"), {"ok": 1})
        self.assertEqual(len(t.urls), 3)
        self.assertEqual(sleeps, [7.0, 2.0])

    def test_network_error_is_retried(self):
        h, t, _ = http([urllib.error.URLError("reset"), (200, [1])])
        self.assertEqual(h.get("https://x/a"), [1])

    def test_client_error_is_not_retried(self):
        h, t, _ = http([(404, {"error": "nope"}), (200, {})])
        with self.assertRaises(HttpError) as cm:
            h.get("https://x/a")
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(len(t.urls), 1)

    def test_gives_up(self):
        h, t, _ = http([(500, "x")] * 3, max_retries=2)
        with self.assertRaises(HttpError):
            h.get("https://x/a")
        self.assertEqual(len(t.urls), 3)


class TestPaginate(unittest.TestCase):
    def test_follows_cursor_and_stops_at_max(self):
        pages = [
            (200, {"data": [{"i": 1}, {"i": 2}], "pagination": {"has_more": True, "next_cursor": "c2"}}),
            (200, {"data": [{"i": 3}, {"i": 4}], "pagination": {"has_more": True, "next_cursor": "c3"}}),
        ]
        h, t, _ = http(pages)
        rows = list(h.paginate("https://x/list", {"user": "u"}, max_items=3, page_size=2))
        self.assertEqual([r["i"] for r in rows], [1, 2, 3])
        self.assertIn("limit=2", t.urls[0])
        self.assertIn("cursor=c2", t.urls[1])
        self.assertNotIn("limit", t.urls[1])  # con cursor manda el tamaño del cursor

    def test_stops_without_more(self):
        h, t, _ = http([(200, {"data": [{"i": 1}], "pagination": {"has_more": False}})])
        self.assertEqual(len(list(h.paginate("https://x/list"))), 1)
        self.assertEqual(len(t.urls), 1)


if __name__ == "__main__":
    unittest.main()

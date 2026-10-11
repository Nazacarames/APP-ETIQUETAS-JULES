"""Cliente HTTP de solo lectura: JSON, caché en disco, ritmo máximo, reintentos y paginación.

Solo hace GET a APIs públicas. No envía datos ni credenciales.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

USER_AGENT = "polylens/0.1 (analisis de datos publicos)"
RETRYABLE = {429, 500, 502, 503, 504}

Transport = Callable[[str, float], tuple[int, Any, dict]]


class HttpError(RuntimeError):
    def __init__(self, status: int, body: Any, url: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status} en {url}: {str(body)[:200]}")


def urllib_transport(url: str, timeout: float) -> tuple[int, Any, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw.decode(errors="replace")
        return exc.code, body, dict(exc.headers or {})


def build_url(base: str, params: dict | None) -> str:
    """Las listas se repiten como parámetro (a=1&a=2), que es lo que espera Gamma."""
    clean = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in sorted((params or {}).items())
             if v is not None}
    return base + ("?" + urllib.parse.urlencode(clean, doseq=True) if clean else "")


class Http:
    def __init__(self, cache_dir: str | Path | None = None, ttl_s: float = 6 * 3600, min_interval_s: float = 0.25,
                 transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time, max_retries: int = 4, timeout_s: float = 30.0):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.ttl_s = ttl_s
        self.min_interval_s = min_interval_s
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self._last = 0.0
        self._lock = threading.Lock()
        self.requests = 0      # pedidos reales a la red (sin contar la caché)
        self.cache_hits = 0

    # -- caché ---------------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.json"

    def _cache_get(self, url: str, ttl: float) -> Any:
        path = self._cache_path(url)
        if not path or not path.exists():
            return None
        try:
            rec = json.loads(path.read_text())
        except (ValueError, OSError):
            return None
        if self.clock() - rec.get("t", 0) > ttl:
            return None
        self.cache_hits += 1
        return rec

    def _cache_put(self, url: str, body: Any) -> None:
        path = self._cache_path(url)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"t": self.clock(), "url": url, "body": body}))
        tmp.replace(path)

    # -- pedidos -------------------------------------------------------------
    def get(self, base: str, params: dict | None = None, ttl: float | None = None) -> Any:
        url = build_url(base, params)
        cached = self._cache_get(url, self.ttl_s if ttl is None else ttl)
        if cached is not None:
            return cached["body"]
        last = ""
        for attempt in range(self.max_retries + 1):
            with self._lock:
                wait = self._last + self.min_interval_s - self.clock()
                if wait > 0:
                    self.sleep(wait)
                self._last = self.clock()
            try:
                status, body, headers = self.transport(url, self.timeout_s)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                status, body, headers = 0, str(exc), {}
            self.requests += 1
            if status == 200:
                self._cache_put(url, body)
                return body
            last = HttpError(status, body, url)
            if status not in RETRYABLE and status != 0:
                raise last
            if attempt < self.max_retries:
                retry_after = headers.get("Retry-After") or headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                self.sleep(min(delay, 30))
        raise last

    def paginate(self, base: str, params: dict | None = None, max_items: int = 1000, page_size: int = 500,
                 ttl: float | None = None) -> Iterator[dict]:
        """Recorre páginas con `pagination.next_cursor` (Data API v2) hasta max_items."""
        params = dict(params or {})
        params["limit"] = min(page_size, max_items)
        got = 0
        while True:
            body = self.get(base, params, ttl)
            rows = (body or {}).get("data") or []
            for row in rows:
                yield row
                got += 1
                if got >= max_items:
                    return
            pag = (body or {}).get("pagination") or {}
            if not pag.get("has_more") or not pag.get("next_cursor") or not rows:
                return
            params = {k: v for k, v in params.items() if k != "limit"}
            params["cursor"] = pag["next_cursor"]

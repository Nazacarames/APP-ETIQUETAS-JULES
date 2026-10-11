"""Cliente de API-Football v3 (https://www.api-football.com). Solo lectura.

- La clave va en el encabezado `x-apisports-key`, nunca en la URL: así tampoco queda en la caché.
- La API responde 200 aunque haya un error (cupo agotado, plan que no incluye la temporada): esas respuestas
  no se guardan en caché y se convierten en ApiError con el mensaje de la API.
- El plan gratis tiene 100 pedidos por día: los partidos terminados no cambian, así que se guardan para siempre.
"""
from __future__ import annotations

from typing import Any, Iterator

from polylens.http import Http, urllib_transport

DAY = 86_400
FOREVER = 3650 * DAY
FINISHED = ("FT", "AET", "PEN")


class ApiError(RuntimeError):
    pass


def _has_errors(body: Any) -> bool:
    return isinstance(body, dict) and bool(body.get("errors"))


class ApiFootball:
    def __init__(self, api_key: str | None, base_url: str = "https://v3.football.api-sports.io",
                 cache_dir=None, min_interval_s: float = 6.5, http: Http | None = None):
        if http is None:
            if not api_key:
                raise ApiError("Falta APIFOOTBALL_KEY: creá una clave gratis en api-football.com y ponela en tu "
                               "archivo de claves local (ver .env.example).")
            headers = {"x-apisports-key": api_key}
            http = Http(cache_dir, ttl_s=DAY, min_interval_s=min_interval_s,
                        transport=lambda url, timeout: urllib_transport(url, timeout, headers),
                        cacheable=lambda body: not _has_errors(body))
        self.http = http
        self.base = base_url.rstrip("/")

    # -- base -------------------------------------------------------------------
    def get(self, endpoint: str, params: dict | None = None, ttl: float = DAY) -> Any:
        body = self.http.get(f"{self.base}/{endpoint.lstrip('/')}", params, ttl=ttl)
        if _has_errors(body):
            errors = body["errors"]
            msg = "; ".join(f"{k}: {v}" for k, v in errors.items()) if isinstance(errors, dict) else str(errors)
            raise ApiError(f"API-Football: {msg}")
        return body

    def all_pages(self, endpoint: str, params: dict | None = None, ttl: float = DAY) -> Iterator[dict]:
        params = dict(params or {})
        page = 1
        while True:
            body = self.get(endpoint, {**params, **({"page": page} if page > 1 else {})}, ttl)
            yield from body.get("response") or []
            paging = body.get("paging") or {}
            if page >= int(paging.get("total") or 1):
                return
            page += 1

    # -- endpoints ----------------------------------------------------------------
    def status(self) -> dict:
        return self.get("status", ttl=0).get("response") or {}

    def leagues(self, country: str = "Argentina") -> list[dict]:
        return list(self.all_pages("leagues", {"country": country}, ttl=7 * DAY))

    def fixtures(self, league: int, season: int) -> list[dict]:
        return list(self.all_pages("fixtures", {"league": league, "season": season}, ttl=6 * 3600))

    def fixture_players(self, fixture: int, finished: bool = True) -> list[dict]:
        return list(self.all_pages("fixtures/players", {"fixture": fixture}, ttl=FOREVER if finished else 600))

    def fixture_events(self, fixture: int, finished: bool = True) -> list[dict]:
        return list(self.all_pages("fixtures/events", {"fixture": fixture}, ttl=FOREVER if finished else 60))

    def lineups(self, fixture: int) -> list[dict]:
        return list(self.all_pages("fixtures/lineups", {"fixture": fixture}, ttl=600))

    def injuries(self, fixture: int) -> list[dict]:
        return list(self.all_pages("injuries", {"fixture": fixture}, ttl=3600))

    def bookmakers(self) -> list[dict]:
        return list(self.all_pages("odds/bookmakers", ttl=7 * DAY))

    def bookmaker_id(self, name: str) -> int | None:
        for b in self.bookmakers():
            if str(b.get("name", "")).strip().lower() == name.strip().lower():
                return int(b["id"])
        return None

    def odds(self, fixture: int, bookmaker: int) -> list[dict]:
        """Cuotas previas al partido. La API las guarda pocos días: hay que pedirlas antes de cada fecha."""
        return list(self.all_pages("odds", {"fixture": fixture, "bookmaker": bookmaker}, ttl=1800))

    def fixture_odds(self, fixture: int, bookmaker: int | None = None) -> list[dict]:
        """Todas las casas (o una) para un partido. Funciona en el plan gratis aunque sea de 2026."""
        return list(self.all_pages("odds", {"fixture": fixture, "bookmaker": bookmaker}, ttl=1800))

    def fixtures_by_date(self, date: str) -> list[dict]:
        """Todos los partidos de una fecha (AAAA-MM-DD). Puede no estar habilitado en el plan gratis."""
        return list(self.all_pages("fixtures", {"date": date}, ttl=1800))

    def odds_mapping_pages(self, max_pages: int = 40):
        """Partidos con cuotas disponibles (todas las ligas), página por página: el que llama decide cuándo parar."""
        page = 1
        while page <= max_pages:
            body = self.get("odds/mapping", {"page": page} if page > 1 else {}, ttl=3 * 3600)
            yield body.get("response") or []
            if page >= int((body.get("paging") or {}).get("total") or 1):
                return
            page += 1

    def live_odds(self, fixture: int) -> list[dict]:
        return list(self.all_pages("odds/live", {"fixture": fixture}, ttl=30))


def odds_rows(odds_response: list[dict]) -> list[dict]:
    """Aplana la respuesta de /odds: una fila por (casa, mercado, selección, cuota)."""
    rows = []
    for item in odds_response:
        fixture = (item.get("fixture") or {}).get("id")
        for b in item.get("bookmakers") or []:
            for bet in b.get("bets") or []:
                for v in bet.get("values") or []:
                    try:
                        odd = float(v.get("odd"))
                    except (TypeError, ValueError):
                        continue
                    rows.append({"fixture": fixture, "bookmaker": b.get("name"), "market": bet.get("name"),
                                 "market_id": bet.get("id"), "selection": str(v.get("value")),
                                 "handicap": v.get("handicap"), "odd": odd})
    return rows

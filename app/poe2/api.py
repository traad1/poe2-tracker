"""Thin client for the poe2scout public API.

API base: https://poe2scout.com/api
OpenAPI spec: https://poe2scout.com/api/openapi.json

Only the endpoints we currently use are wrapped. Responses are returned as raw dicts/lists —
shape normalization happens in `repository.py` so the API client stays close to the wire.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

BASE_URL = "https://poe2scout.com/api"
DEFAULT_REALM = "poe2"
USER_AGENT = "poe2-tracker/0.1 (personal)"


class Poe2ApiError(RuntimeError):
    pass


@dataclass
class League:
    value: str
    short_name: str
    is_current: bool
    divine_price_ex: float


class Poe2ScoutClient:
    def __init__(self, base_url: str = BASE_URL, realm: str = DEFAULT_REALM, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            try:
                r = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == 2:
                    raise Poe2ApiError(f"network error fetching {url}: {e}") from e
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            if not r.ok:
                raise Poe2ApiError(f"{r.status_code} {r.reason} for {url}: {r.text[:200]}")
            return r.json()
        raise Poe2ApiError(f"giving up on {url} after retries")

    def list_leagues(self) -> list[League]:
        raw = self._get(f"/{self.realm}/Leagues")
        return [
            League(
                value=L["Value"],
                short_name=L.get("ShortName", ""),
                is_current=bool(L.get("IsCurrent", False)),
                divine_price_ex=float(L.get("DivinePrice") or 0),
            )
            for L in raw
        ]

    def categories(self, league: str) -> dict[str, Any]:
        return self._get(f"/{self.realm}/Leagues/{quote(league)}/Items/Categories")

    def currencies_by_category(
        self, league: str, category: str, page: int = 1, per_page: int = 50
    ) -> dict[str, Any]:
        return self._get(
            f"/{self.realm}/Leagues/{quote(league)}/Currencies/ByCategory",
            params={"Category": category, "page": page, "perPage": per_page},
        )

    def uniques_by_category(
        self, league: str, category: str, page: int = 1, per_page: int = 50
    ) -> dict[str, Any]:
        return self._get(
            f"/{self.realm}/Leagues/{quote(league)}/Uniques/ByCategory",
            params={"Category": category, "page": page, "perPage": per_page},
        )

    def item_price_history(self, league: str, item_id: int) -> dict[str, Any]:
        return self._get(f"/{self.realm}/Leagues/{quote(league)}/Items/{item_id}/History")

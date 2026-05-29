"""Headless price refresher — called by GitHub Actions cron every 3 hours.

Pulls every category for the current league from poe2scout, upserts the snapshot,
appends to price_history. No Streamlit dependency — safe to run as a plain `python -m`.

Usage:
    python -m poe2.refresh                       # current league, all categories
    python -m poe2.refresh --league "League name"   # override league
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

from .api import Poe2ApiError, Poe2ScoutClient
from . import repository as repo

# Mirror of pages_/market.py's CATEGORIES. Kept duplicated to avoid the CLI importing Streamlit.
ALL_CATEGORIES: list[tuple[str, str, str]] = [
    ("currency", "currency", "Currency"),
    ("currency", "ritual", "Ritual Omens"),
    ("currency", "essences", "Essences"),
    ("currency", "runes", "Runes"),
    ("currency", "ultimatum", "Soul Cores"),
    ("currency", "fragments", "Fragments"),
    ("currency", "breach", "Breach"),
    ("currency", "expedition", "Expedition"),
    ("currency", "delirium", "Delirium"),
    ("currency", "vaultkeys", "Reliquary Keys"),
    ("currency", "idol", "Idols"),
    ("unique", "weapon", "Unique Weapons"),
    ("unique", "armour", "Unique Armour"),
    ("unique", "accessory", "Unique Accessories"),
    ("unique", "jewel", "Unique Jewels"),
    ("unique", "flask", "Unique Flasks"),
    ("unique", "map", "Unique Maps"),
    ("unique", "sanctum", "Sanctum Research"),
]


def pick_league(client: Poe2ScoutClient, override: str | None) -> str:
    if override:
        return override
    leagues = client.list_leagues()
    if not leagues:
        raise RuntimeError("poe2scout returned no leagues at all")
    current = next((L for L in leagues if L.is_current), None)
    if current:
        return current.value
    # Between-leagues window: no IsCurrent flag yet. Skip HC variants (shortname suffix 'hc')
    # and pick the first softcore league in the response, which is the most recently active one.
    softcore = [L for L in leagues if not L.short_name.endswith("hc")]
    fallback = (softcore or leagues)[0]
    print(f"[refresh] no IsCurrent league; falling back to {fallback.value!r}", file=sys.stderr)
    return fallback.value


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", default=None, help="League name override")
    args = parser.parse_args(list(argv) if argv is not None else None)

    client = Poe2ScoutClient()
    league = pick_league(client, args.league)
    print(f"[refresh] league={league!r}  categories={len(ALL_CATEGORIES)}")

    started = time.time()
    try:
        n = repo.refresh_prices(league, ALL_CATEGORIES, client=client)
    except Poe2ApiError as e:
        print(f"[refresh] API error: {e}", file=sys.stderr)
        return 1
    elapsed = time.time() - started
    print(f"[refresh] cached {n} rows in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

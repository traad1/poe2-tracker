"""Repository layer: live API + DB cache + user watchlist + trade log + crafted-item lots.

Dual storage backend:
- **Local dev**: SQLite at `app/data/tracker.db`. Used when DATABASE_URL is unset.
- **Production**: Postgres (e.g. Neon free tier). Used when DATABASE_URL is set, either as an
  environment variable or via Streamlit secrets (`.streamlit/secrets.toml`).

The Streamlit UI never imports the API client directly. Everything UI-facing returns pandas
DataFrames with stable columns so the storage layer can be swapped without touching the UI.

Stable item record columns:
    item_id, api_id, name, category, current_price_ex, price_24h_ago_ex, change_24h_pct,
    icon_url, last_updated
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .api import Poe2ScoutClient

CACHE_TTL_MINUTES = 30
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "tracker.db"


def _resolve_database_url() -> str:
    """Pick a connection string.

    Priority:
    1. DATABASE_URL env var (set by Streamlit Cloud secrets, or shell).
    2. st.secrets["DATABASE_URL"] if Streamlit is running (won't crash if it isn't).
    3. Local SQLite file at app/data/tracker.db.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return _normalize_url(url)
    try:
        import streamlit as st  # local import — Streamlit isn't required for CLI/tests
        if "DATABASE_URL" in st.secrets:
            return _normalize_url(st.secrets["DATABASE_URL"])
    except Exception:
        pass
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def _normalize_url(url: str) -> str:
    # Heroku/Neon historically hand out `postgres://`, SQLAlchemy 2 needs `postgresql://`.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # If the user pasted a psycopg2 URL without a driver, default to psycopg2.
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _resolve_database_url()
        # pool_pre_ping handles Neon's idle-disconnects gracefully.
        _engine = create_engine(url, pool_pre_ping=True, future=True)
        _init_schema(_engine)
    return _engine


def _is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


# Schemas diverge in a few small ways between SQLite and Postgres (autoincrement syntax,
# real vs double precision). Keep both in one place so they're easy to diff.

SQLITE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS price_snapshot (
        league       TEXT NOT NULL,
        item_id      INTEGER NOT NULL,
        api_id       TEXT NOT NULL,
        name         TEXT NOT NULL,
        category     TEXT NOT NULL,
        current_price_ex REAL,
        price_24h_ago_ex REAL,
        listing_count   INTEGER,
        price_logs_json TEXT,
        icon_url     TEXT,
        fetched_at   TEXT NOT NULL,
        PRIMARY KEY (league, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        league          TEXT NOT NULL,
        item_id         INTEGER NOT NULL,
        target_buy_ex   REAL,
        target_sell_ex  REAL,
        tag             TEXT NOT NULL DEFAULT 'flip',
        note            TEXT,
        added_at        TEXT NOT NULL,
        PRIMARY KEY (league, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trade (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        league          TEXT NOT NULL,
        item_id         INTEGER,
        item_name       TEXT NOT NULL,
        side            TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
        qty             REAL NOT NULL,
        price_ex        REAL NOT NULL,
        executed_at     TEXT NOT NULL,
        note            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trade_league_item ON trade(league, item_name)",
    """
    CREATE TABLE IF NOT EXISTS lot (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        league          TEXT NOT NULL,
        item_name       TEXT NOT NULL,
        category        TEXT,
        created_at      TEXT NOT NULL,
        sold_price_ex   REAL,
        sold_at         TEXT,
        note            TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lot_cost_line (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        lot_id          INTEGER NOT NULL REFERENCES lot(id) ON DELETE CASCADE,
        kind            TEXT NOT NULL,
        label           TEXT NOT NULL,
        cost_ex         REAL NOT NULL,
        cost_input      REAL,
        cost_currency   TEXT,
        created_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_costline_lot ON lot_cost_line(lot_id)",
    """
    CREATE TABLE IF NOT EXISTS price_history (
        league      TEXT NOT NULL,
        item_id     INTEGER NOT NULL,
        fetched_at  TEXT NOT NULL,
        price_ex    REAL,
        PRIMARY KEY (league, item_id, fetched_at)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_history_item ON price_history(league, item_id, fetched_at)",
]

POSTGRES_DDL = [
    """
    CREATE TABLE IF NOT EXISTS price_snapshot (
        league       TEXT NOT NULL,
        item_id      INTEGER NOT NULL,
        api_id       TEXT NOT NULL,
        name         TEXT NOT NULL,
        category     TEXT NOT NULL,
        current_price_ex DOUBLE PRECISION,
        price_24h_ago_ex DOUBLE PRECISION,
        listing_count   INTEGER,
        price_logs_json TEXT,
        icon_url     TEXT,
        fetched_at   TEXT NOT NULL,
        PRIMARY KEY (league, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        league          TEXT NOT NULL,
        item_id         INTEGER NOT NULL,
        target_buy_ex   DOUBLE PRECISION,
        target_sell_ex  DOUBLE PRECISION,
        tag             TEXT NOT NULL DEFAULT 'flip',
        note            TEXT,
        added_at        TEXT NOT NULL,
        PRIMARY KEY (league, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trade (
        id              BIGSERIAL PRIMARY KEY,
        league          TEXT NOT NULL,
        item_id         INTEGER,
        item_name       TEXT NOT NULL,
        side            TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
        qty             DOUBLE PRECISION NOT NULL,
        price_ex        DOUBLE PRECISION NOT NULL,
        executed_at     TEXT NOT NULL,
        note            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trade_league_item ON trade(league, item_name)",
    """
    CREATE TABLE IF NOT EXISTS lot (
        id              BIGSERIAL PRIMARY KEY,
        league          TEXT NOT NULL,
        item_name       TEXT NOT NULL,
        category        TEXT,
        created_at      TEXT NOT NULL,
        sold_price_ex   DOUBLE PRECISION,
        sold_at         TEXT,
        note            TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lot_cost_line (
        id              BIGSERIAL PRIMARY KEY,
        lot_id          BIGINT NOT NULL REFERENCES lot(id) ON DELETE CASCADE,
        kind            TEXT NOT NULL,
        label           TEXT NOT NULL,
        cost_ex         DOUBLE PRECISION NOT NULL,
        cost_input      DOUBLE PRECISION,
        cost_currency   TEXT,
        created_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_costline_lot ON lot_cost_line(lot_id)",
    """
    CREATE TABLE IF NOT EXISTS price_history (
        league      TEXT NOT NULL,
        item_id     INTEGER NOT NULL,
        fetched_at  TEXT NOT NULL,
        price_ex    DOUBLE PRECISION,
        PRIMARY KEY (league, item_id, fetched_at)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_history_item ON price_history(league, item_id, fetched_at)",
]


def _init_schema(engine: Engine) -> None:
    ddl = SQLITE_DDL if _is_sqlite(engine) else POSTGRES_DDL
    with engine.begin() as con:
        for stmt in ddl:
            con.execute(text(stmt))
        if _is_sqlite(engine):
            wl_cols = {row[1] for row in con.exec_driver_sql(
                "PRAGMA table_info(watchlist)").fetchall()}
            if "tag" not in wl_cols:
                con.exec_driver_sql(
                    "ALTER TABLE watchlist ADD COLUMN tag TEXT NOT NULL DEFAULT 'flip'"
                )
            snap_cols = {row[1] for row in con.exec_driver_sql(
                "PRAGMA table_info(price_snapshot)").fetchall()}
            if "listing_count" not in snap_cols:
                con.exec_driver_sql("ALTER TABLE price_snapshot ADD COLUMN listing_count INTEGER")
            if "price_logs_json" not in snap_cols:
                con.exec_driver_sql("ALTER TABLE price_snapshot ADD COLUMN price_logs_json TEXT")
        else:
            # Postgres: IF NOT EXISTS makes these safe to run every boot.
            con.execute(text(
                "ALTER TABLE price_snapshot ADD COLUMN IF NOT EXISTS listing_count INTEGER"
            ))
            con.execute(text(
                "ALTER TABLE price_snapshot ADD COLUMN IF NOT EXISTS price_logs_json TEXT"
            ))


# ---------- price cache ----------

def _flatten_item(raw: dict, category_label: str) -> dict:
    import json as _json
    raw_logs = raw.get("PriceLogs") or []
    # PriceLogs is a 7-element array of {"Price": float, ...} or null per day.
    # Use the first non-null log as the "24h ago" reference (kept for back-compat with the
    # existing 24h Δ column). For the sparkline, persist the full log array as JSON.
    logs = [p for p in raw_logs if p]
    price_24h = logs[0].get("Price") if logs else None
    return {
        "item_id": raw["ItemId"],
        "api_id": raw.get("ApiId") or raw.get("Text"),
        "name": raw.get("Text") or raw.get("ItemMetadata", {}).get("name", "?"),
        "category": category_label,
        "current_price_ex": raw.get("CurrentPrice"),
        "price_24h_ago_ex": price_24h,
        "listing_count": raw.get("CurrentQuantity"),
        "price_logs_json": _json.dumps(raw_logs) if raw_logs else None,
        "icon_url": raw.get("IconUrl"),
    }


# SQLite and Postgres both support ON CONFLICT, but Postgres needs target columns spelled out
# without the `excluded.` prefix differing by dialect (it's the same). Statements verified on both.

_PRICE_UPSERT = """
INSERT INTO price_snapshot (league, item_id, api_id, name, category,
                            current_price_ex, price_24h_ago_ex,
                            listing_count, price_logs_json,
                            icon_url, fetched_at)
VALUES (:league, :item_id, :api_id, :name, :category,
        :current_price_ex, :price_24h_ago_ex,
        :listing_count, :price_logs_json,
        :icon_url, :fetched_at)
ON CONFLICT (league, item_id) DO UPDATE SET
    api_id = EXCLUDED.api_id,
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    current_price_ex = EXCLUDED.current_price_ex,
    price_24h_ago_ex = EXCLUDED.price_24h_ago_ex,
    listing_count = EXCLUDED.listing_count,
    price_logs_json = EXCLUDED.price_logs_json,
    icon_url = EXCLUDED.icon_url,
    fetched_at = EXCLUDED.fetched_at
"""

_WATCHLIST_UPSERT = """
INSERT INTO watchlist (league, item_id, target_buy_ex, target_sell_ex, tag, note, added_at)
VALUES (:league, :item_id, :target_buy_ex, :target_sell_ex, :tag, :note, :added_at)
ON CONFLICT (league, item_id) DO UPDATE SET
    target_buy_ex = EXCLUDED.target_buy_ex,
    target_sell_ex = EXCLUDED.target_sell_ex,
    tag = EXCLUDED.tag,
    note = EXCLUDED.note
"""


def refresh_prices(
    league: str,
    categories: Iterable[tuple[str, str, str]],
    client: Poe2ScoutClient | None = None,
) -> int:
    client = client or Poe2ScoutClient()
    rows: list[dict] = []
    for kind, api_id, label in categories:
        page = 1
        while True:
            if kind == "currency":
                resp = client.currencies_by_category(league, api_id, page=page, per_page=100)
            else:
                resp = client.uniques_by_category(league, api_id, page=page, per_page=100)
            for item in resp.get("Items", []):
                rows.append(_flatten_item(item, label))
            if page >= int(resp.get("Pages", 1)):
                break
            page += 1

    now = datetime.now(timezone.utc).isoformat()
    payload = [{**r, "league": league, "fetched_at": now} for r in rows]
    if not payload:
        return 0
    history_payload = [
        {"league": league, "item_id": r["item_id"], "fetched_at": now,
         "price_ex": r.get("current_price_ex")}
        for r in rows
    ]
    engine = get_engine()
    with engine.begin() as con:
        con.execute(text(_PRICE_UPSERT), payload)
        # Append-only history: PK (league, item_id, fetched_at) ensures dedupe on retry.
        con.execute(
            text(
                "INSERT INTO price_history (league, item_id, fetched_at, price_ex) "
                "VALUES (:league, :item_id, :fetched_at, :price_ex) "
                "ON CONFLICT (league, item_id, fetched_at) DO NOTHING"
            ),
            history_payload,
        )
    return len(payload)


def trends(
    league: str,
    min_price_ex: float = 0.0,
    lookback_24h_tolerance_hours: float = 6.0,
) -> pd.DataFrame:
    """Compute per-item trend metrics from price_history + the current snapshot.

    Returns one row per item with: name, category, icon_url, current_price_ex,
    price_24h_ago_ex (best history row closest to 24h ago, within tolerance),
    price_7d_ago_ex, change_24h_pct, change_24h_ex, change_7d_pct.

    Items with no usable history are still returned with NaN deltas — UI can filter.
    `min_price_ex` filters out garbage rows where small absolute moves blow up %.
    """
    df = _read_sql(
        """
        SELECT p.item_id, p.name, p.category, p.icon_url, p.current_price_ex,
               p.listing_count, p.price_logs_json
          FROM price_snapshot p
         WHERE p.league = :league
        """,
        {"league": league},
    )
    if df.empty:
        return df

    history = _read_sql(
        "SELECT item_id, fetched_at, price_ex FROM price_history WHERE league = :league",
        {"league": league},
    )

    df["current_price_ex"] = pd.to_numeric(df["current_price_ex"], errors="coerce")
    df["listing_count"] = pd.to_numeric(df["listing_count"], errors="coerce")
    fallback = _history_sparklines(league)
    df["sparkline"] = df.apply(lambda r: _build_sparkline(r, fallback), axis=1)

    if history.empty:
        df["price_24h_ago_ex"] = pd.NA
        df["price_7d_ago_ex"] = pd.NA
        df["change_24h_pct"] = pd.NA
        df["change_24h_ex"] = pd.NA
        df["change_7d_pct"] = pd.NA
        return df[df["current_price_ex"] >= min_price_ex].copy()

    history["fetched_at_dt"] = pd.to_datetime(history["fetched_at"], utc=True)
    history["price_ex"] = pd.to_numeric(history["price_ex"], errors="coerce")
    now = pd.Timestamp.now(tz="UTC")
    target_24h = now - pd.Timedelta(hours=24)
    target_7d = now - pd.Timedelta(days=7)
    tol = pd.Timedelta(hours=lookback_24h_tolerance_hours)

    # For each item, find the history row closest to 24h-ago (within tolerance) and 7d-ago.
    def closest_within(group: pd.DataFrame, target: pd.Timestamp, tolerance: pd.Timedelta):
        group = group.dropna(subset=["price_ex"])
        if group.empty:
            return None
        diffs = (group["fetched_at_dt"] - target).abs()
        idx = diffs.idxmin()
        if diffs.loc[idx] > tolerance:
            return None
        return float(group.loc[idx, "price_ex"])

    def _lookup_frame(target: pd.Timestamp, tolerance: pd.Timedelta, col: str) -> pd.DataFrame:
        results = {
            int(item_id): closest_within(group, target, tolerance)
            for item_id, group in history.groupby("item_id")
        }
        return pd.DataFrame({"item_id": list(results.keys()), col: list(results.values())})

    p24_df = _lookup_frame(target_24h, tol, "price_24h_ago_ex")
    p7d_df = _lookup_frame(target_7d, pd.Timedelta(days=2), "price_7d_ago_ex")
    df = df.merge(p24_df, how="left", on="item_id")
    df = df.merge(p7d_df, how="left", on="item_id")
    df["price_24h_ago_ex"] = pd.to_numeric(df["price_24h_ago_ex"], errors="coerce")
    df["price_7d_ago_ex"] = pd.to_numeric(df["price_7d_ago_ex"], errors="coerce")

    df["change_24h_ex"] = df["current_price_ex"] - df["price_24h_ago_ex"]
    df["change_24h_pct"] = (df["change_24h_ex"] / df["price_24h_ago_ex"] * 100).round(2)
    df["change_7d_pct"] = (
        (df["current_price_ex"] - df["price_7d_ago_ex"]) / df["price_7d_ago_ex"] * 100
    ).round(2)

    # Volatility: coefficient of variation (std / mean) over the last 7 days of history,
    # expressed as percent. Items with <3 history points get NaN. CoV normalizes across
    # very different price levels so a Mirror moving ±1k ex doesn't dominate a 5-ex item.
    recent = history[history["fetched_at_dt"] >= now - pd.Timedelta(days=7)].copy()
    if not recent.empty:
        agg = recent.groupby("item_id")["price_ex"].agg(["std", "mean", "count"])
        agg = agg[agg["count"] >= 3]
        agg["volatility_pct"] = (agg["std"] / agg["mean"] * 100).round(2)
        vol_df = agg[["volatility_pct"]].reset_index()
        df = df.merge(vol_df, how="left", on="item_id")
    else:
        df["volatility_pct"] = pd.NA
    df["volatility_pct"] = pd.to_numeric(df["volatility_pct"], errors="coerce")

    df = df[df["current_price_ex"] >= min_price_ex].copy()
    return df


def load_item_history(league: str, item_id: int) -> pd.DataFrame:
    """All price snapshots for a single item, oldest first. For the per-item chart."""
    df = _read_sql(
        """
        SELECT fetched_at, price_ex
          FROM price_history
         WHERE league = :league AND item_id = :item_id
         ORDER BY fetched_at ASC
        """,
        {"league": league, "item_id": item_id},
    )
    if df.empty:
        return df
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df["price_ex"] = pd.to_numeric(df["price_ex"], errors="coerce")
    return df


def _read_sql(query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    return pd.read_sql_query(text(query), get_engine(), params=params or {})


def load_prices(league: str) -> pd.DataFrame:
    df = _read_sql("SELECT * FROM price_snapshot WHERE league = :league", {"league": league})
    if df.empty:
        return df
    cur = pd.to_numeric(df["current_price_ex"], errors="coerce")
    prev = pd.to_numeric(df["price_24h_ago_ex"], errors="coerce")
    df["current_price_ex"] = cur
    df["price_24h_ago_ex"] = prev
    df["change_24h_pct"] = ((cur - prev) / prev * 100).round(2)
    if "listing_count" in df.columns:
        df["listing_count"] = pd.to_numeric(df["listing_count"], errors="coerce")

    fallback = _history_sparklines(league)
    df["sparkline"] = df.apply(lambda r: _build_sparkline(r, fallback), axis=1)
    return df


def _history_sparklines(league: str) -> dict[int, list[float]]:
    """Per-item sparkline series from our own price_history table.

    Used as a fallback when poe2scout's PriceLogs is empty (e.g. early league).
    Returns up to the last 14 snapshots per item, in chronological order.
    """
    df = _read_sql(
        """
        SELECT item_id, price_ex
          FROM price_history
         WHERE league = :league
         ORDER BY item_id, fetched_at ASC
        """,
        {"league": league},
    )
    if df.empty:
        return {}
    df["price_ex"] = pd.to_numeric(df["price_ex"], errors="coerce")
    out: dict[int, list[float]] = {}
    for item_id, group in df.groupby("item_id"):
        series = [float(v) for v in group["price_ex"].dropna().tolist()]
        if series:
            out[int(item_id)] = series[-14:]
    return out


def _build_sparkline(row, fallback: dict[int, list[float]]) -> list[float]:
    """Build a numeric series for a row's sparkline.

    Source priority:
    1. poe2scout's PriceLogs (7 daily entries) when populated. We append current price
       so the line ends "today" not 24h ago.
    2. Our own price_history rolled up.
    3. Empty list — Streamlit renders this as no line, which is fine for "no data yet".
    """
    import json as _json
    logs_raw = row.get("price_logs_json")
    if logs_raw:
        try:
            logs = _json.loads(logs_raw)
        except (ValueError, TypeError):
            logs = []
        series = [float(e["Price"]) for e in logs
                  if isinstance(e, dict) and e.get("Price") is not None]
        if series:
            cur = row.get("current_price_ex")
            if pd.notna(cur):
                series.append(float(cur))
            return series
    return fallback.get(int(row["item_id"]), [])


def cache_age_minutes(league: str) -> float | None:
    with get_engine().connect() as con:
        row = con.execute(
            text("SELECT MAX(fetched_at) AS ts FROM price_snapshot WHERE league = :league"),
            {"league": league},
        ).first()
    if not row or not row[0]:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(row[0])).total_seconds() / 60


def mirror_price_ex(league: str) -> float | None:
    return _currency_price_ex(league, "mirror")


def divine_price_ex(league: str) -> float | None:
    return _currency_price_ex(league, "divine")


def _currency_price_ex(league: str, api_id: str) -> float | None:
    with get_engine().connect() as con:
        row = con.execute(
            text(
                "SELECT current_price_ex FROM price_snapshot "
                "WHERE league = :league AND api_id = :api_id"
            ),
            {"league": league, "api_id": api_id},
        ).first()
    return float(row[0]) if row and row[0] is not None else None


def to_ex(amount: float, currency: str, league: str) -> float:
    if currency == "ex":
        return float(amount)
    if currency == "div":
        rate = divine_price_ex(league)
        if not rate:
            raise ValueError(
                "Divine→Exalt rate not in cache. Refresh the Currency category on Market first."
            )
        return float(amount) * rate
    raise ValueError(f"unknown currency {currency!r}")


# ---------- watchlist ----------

def add_to_watchlist(
    league: str, item_id: int,
    target_buy_ex: float | None = None,
    target_sell_ex: float | None = None,
    tag: str = "flip",
    note: str = "",
) -> None:
    with get_engine().begin() as con:
        con.execute(text(_WATCHLIST_UPSERT), {
            "league": league, "item_id": item_id,
            "target_buy_ex": target_buy_ex, "target_sell_ex": target_sell_ex,
            "tag": tag, "note": note,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })


def remove_from_watchlist(league: str, item_id: int) -> None:
    with get_engine().begin() as con:
        con.execute(
            text("DELETE FROM watchlist WHERE league = :league AND item_id = :item_id"),
            {"league": league, "item_id": item_id},
        )


def load_watchlist(league: str, tag: str | None = None) -> pd.DataFrame:
    query = """
        SELECT w.item_id, w.tag, p.name, p.category, p.current_price_ex,
               w.target_buy_ex, w.target_sell_ex, w.note, p.icon_url
          FROM watchlist w
          LEFT JOIN price_snapshot p ON p.league = w.league AND p.item_id = w.item_id
         WHERE w.league = :league
    """
    params: dict[str, Any] = {"league": league}
    if tag:
        query += " AND w.tag = :tag"
        params["tag"] = tag
    df = _read_sql(query, params)
    if df.empty:
        return df
    for col in ("current_price_ex", "target_buy_ex", "target_sell_ex"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["profit_margin_ex"] = df["target_sell_ex"] - df["target_buy_ex"]
    df["margin_pct"] = (df["profit_margin_ex"] / df["target_buy_ex"] * 100).round(1)
    df["distance_to_buy_pct"] = (
        (df["current_price_ex"] - df["target_buy_ex"]) / df["target_buy_ex"] * 100
    ).round(1)
    return df.sort_values("margin_pct", ascending=False, na_position="last")


# ---------- trades (PnL) ----------

def record_trade(
    league: str, item_name: str, side: str, qty: float, price_ex: float,
    item_id: int | None = None, note: str = "", executed_at: datetime | None = None,
) -> int:
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    ts = (executed_at or datetime.now(timezone.utc)).isoformat()
    with get_engine().begin() as con:
        result = con.execute(
            text(
                "INSERT INTO trade (league, item_id, item_name, side, qty, price_ex, executed_at, note) "
                "VALUES (:league, :item_id, :item_name, :side, :qty, :price_ex, :executed_at, :note) "
                "RETURNING id"
            ),
            {
                "league": league, "item_id": item_id, "item_name": item_name,
                "side": side, "qty": qty, "price_ex": price_ex,
                "executed_at": ts, "note": note,
            },
        )
        return int(result.scalar_one())


def delete_trade(trade_id: int) -> None:
    with get_engine().begin() as con:
        con.execute(text("DELETE FROM trade WHERE id = :id"), {"id": trade_id})


def load_trades(league: str) -> pd.DataFrame:
    df = _read_sql(
        "SELECT * FROM trade WHERE league = :league ORDER BY executed_at DESC",
        {"league": league},
    )
    if df.empty:
        return df
    df["total_ex"] = df["qty"] * df["price_ex"]
    return df


# ---------- crafted-item lots ----------

def create_lot(league: str, item_name: str, category: str = "", note: str = "") -> int:
    if not item_name.strip():
        raise ValueError("item_name is required")
    with get_engine().begin() as con:
        result = con.execute(
            text(
                "INSERT INTO lot (league, item_name, category, created_at, note) "
                "VALUES (:league, :item_name, :category, :created_at, :note) "
                "RETURNING id"
            ),
            {
                "league": league, "item_name": item_name.strip(), "category": category,
                "created_at": datetime.now(timezone.utc).isoformat(), "note": note,
            },
        )
        return int(result.scalar_one())


def add_cost_line(
    lot_id: int, kind: str, label: str, amount: float, currency: str, league: str,
) -> int:
    if kind not in ("base", "mod", "socket", "jewel", "other"):
        raise ValueError(f"kind must be one of base/mod/socket/jewel/other, got {kind!r}")
    if amount <= 0:
        raise ValueError("amount must be > 0")
    cost_ex = to_ex(amount, currency, league)
    with get_engine().begin() as con:
        result = con.execute(
            text(
                "INSERT INTO lot_cost_line (lot_id, kind, label, cost_ex, cost_input, cost_currency, created_at) "
                "VALUES (:lot_id, :kind, :label, :cost_ex, :cost_input, :cost_currency, :created_at) "
                "RETURNING id"
            ),
            {
                "lot_id": lot_id, "kind": kind, "label": label,
                "cost_ex": cost_ex, "cost_input": amount, "cost_currency": currency,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return int(result.scalar_one())


def delete_cost_line(line_id: int) -> None:
    with get_engine().begin() as con:
        con.execute(text("DELETE FROM lot_cost_line WHERE id = :id"), {"id": line_id})


def record_lot_sale(lot_id: int, amount: float, currency: str, league: str) -> None:
    sold_ex = to_ex(amount, currency, league)
    with get_engine().begin() as con:
        con.execute(
            text("UPDATE lot SET sold_price_ex = :p, sold_at = :t WHERE id = :id"),
            {"p": sold_ex, "t": datetime.now(timezone.utc).isoformat(), "id": lot_id},
        )


def clear_lot_sale(lot_id: int) -> None:
    with get_engine().begin() as con:
        con.execute(
            text("UPDATE lot SET sold_price_ex = NULL, sold_at = NULL WHERE id = :id"),
            {"id": lot_id},
        )


def delete_lot(lot_id: int) -> None:
    with get_engine().begin() as con:
        con.execute(text("DELETE FROM lot_cost_line WHERE lot_id = :id"), {"id": lot_id})
        con.execute(text("DELETE FROM lot WHERE id = :id"), {"id": lot_id})


def load_lots(league: str) -> pd.DataFrame:
    df = _read_sql(
        """
        SELECT l.id, l.item_name, l.category, l.created_at, l.sold_price_ex, l.sold_at, l.note,
               COALESCE(SUM(c.cost_ex), 0) AS total_cost_ex,
               COUNT(c.id) AS cost_line_count
          FROM lot l
          LEFT JOIN lot_cost_line c ON c.lot_id = l.id
         WHERE l.league = :league
         GROUP BY l.id, l.item_name, l.category, l.created_at, l.sold_price_ex, l.sold_at, l.note
         ORDER BY l.created_at DESC
        """,
        {"league": league},
    )
    if df.empty:
        return df
    df["pnl_ex"] = df["sold_price_ex"] - df["total_cost_ex"]
    df["roi_pct"] = (df["pnl_ex"] / df["total_cost_ex"] * 100).round(1)
    df["status"] = df["sold_price_ex"].apply(lambda v: "sold" if pd.notna(v) else "open")
    return df


def load_cost_lines(lot_id: int) -> pd.DataFrame:
    return _read_sql(
        "SELECT * FROM lot_cost_line WHERE lot_id = :lot_id ORDER BY id",
        {"lot_id": lot_id},
    )


def pnl_summary(league: str) -> pd.DataFrame:
    trades = load_trades(league)
    if trades.empty:
        return trades

    rows: list[dict] = []
    for item, group in trades.sort_values("executed_at").groupby("item_name"):
        buys = group[group["side"] == "buy"]
        sells = group[group["side"] == "sell"]
        bought_qty = float(buys["qty"].sum())
        bought_cost = float((buys["qty"] * buys["price_ex"]).sum())
        sold_qty = float(sells["qty"].sum())
        sold_proceeds = float((sells["qty"] * sells["price_ex"]).sum())

        avg_cost = bought_cost / bought_qty if bought_qty else 0.0
        realized_pnl = sold_proceeds - avg_cost * sold_qty
        open_qty = bought_qty - sold_qty
        open_value_at_cost = avg_cost * max(open_qty, 0.0)
        roi_pct = (realized_pnl / (avg_cost * sold_qty) * 100) if sold_qty and avg_cost else None

        rows.append({
            "item": item,
            "bought_qty": bought_qty,
            "sold_qty": sold_qty,
            "open_qty": open_qty,
            "avg_cost_ex": round(avg_cost, 2),
            "realized_pnl_ex": round(realized_pnl, 2),
            "roi_pct": round(roi_pct, 1) if roi_pct is not None else None,
            "open_value_at_cost_ex": round(open_value_at_cost, 2),
        })
    return pd.DataFrame(rows).sort_values("realized_pnl_ex", ascending=False)

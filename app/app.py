"""PoE 2 Trade & Economy Tracker — Streamlit entry point.

Focused on economy/trade only: live prices, flip watchlist, inflation hedge tracker, and a
PnL log. The strategy this app supports comes from the Mirror-tier "beating inflation" guide:
ladder Omens (Abyssal Echoes -> Whittling/Light -> Hinekora's Lock) until you can afford a
mirror outright.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from pages_ import market, watchlist, pnl, trends

# Patch 0.5 "Return of the Ancients" goes live at this absolute UTC moment.
# The countdown banner below auto-hides once we're past it.
PATCH_LAUNCH_UTC = datetime(2026, 5, 29, 20, 0, tzinfo=timezone.utc)

st.set_page_config(page_title="PoE 2 Trade Tracker", page_icon=":coin:", layout="wide")

st.title("Path of Exile 2 — Trade & Economy")
st.caption("Live market • Trends • Flip watchlist • Inflation hedges • PnL")


def _patch_countdown() -> None:
    now = datetime.now(timezone.utc)
    if now >= PATCH_LAUNCH_UTC:
        return  # Banner auto-hides after launch.
    delta = PATCH_LAUNCH_UTC - now
    total_seconds = int(delta.total_seconds())
    hours, rem = divmod(total_seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours > 0:
        countdown = f"{hours}h {minutes}m"
    else:
        countdown = f"{minutes}m"
    st.info(
        f"⏳ **Patch 0.5 launches in {countdown}** "
        f"(2026-05-29 20:00 UTC / 12:00 PM PT). "
        "The app and 3-hourly cron auto-switch to the new league once poe2scout flags it."
    )


_patch_countdown()

league = market.league_selector()

tab_market, tab_trends, tab_watch, tab_pnl = st.tabs(["Market", "Trends", "Watchlist", "PnL"])

with tab_market:
    market.render(league)
with tab_trends:
    trends.render(league)
with tab_watch:
    watchlist.render(league)
with tab_pnl:
    pnl.render(league)

"""PoE 2 Trade & Economy Tracker — Streamlit entry point.

Focused on economy/trade only: live prices, flip watchlist, inflation hedge tracker, and a
PnL log. The strategy this app supports comes from the Mirror-tier "beating inflation" guide:
ladder Omens (Abyssal Echoes -> Whittling/Light -> Hinekora's Lock) until you can afford a
mirror outright.
"""
from __future__ import annotations

import streamlit as st

from pages_ import market, watchlist, pnl, trends

st.set_page_config(page_title="PoE 2 Trade Tracker", page_icon=":coin:", layout="wide")

st.title("Path of Exile 2 — Trade & Economy")
st.caption("Live market • Trends • Flip watchlist • Inflation hedges • PnL")

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

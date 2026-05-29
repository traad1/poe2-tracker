"""Trends tab — what's moving in the economy."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from poe2 import repository as repo
from .market import poe2db_url


def render(league: str) -> None:
    st.header("Trends")
    st.caption(
        "Top gainers and losers, computed from the price snapshots a GitHub Actions cron "
        "refreshes every 3 hours. 24h Δ uses the closest history row to 24h-ago "
        "(±6h tolerance); 7d Δ uses ±2 days."
    )

    div_ex = repo.divine_price_ex(league)

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        top_n = st.number_input("Top N", min_value=5, max_value=100, value=10, step=5)
    with c2:
        min_price = st.number_input(
            "Min price (ex)", min_value=0.0, value=5.0, step=1.0,
            help="Filter out junk items where a 0.01→0.05 ex bump shows as a 400% gainer.",
        )
    with c3:
        all_cats = sorted(repo.load_prices(league)["category"].dropna().unique().tolist())
        chosen_cats = st.multiselect(
            "Categories", options=all_cats, default=all_cats,
            help="Filter the trend universe.",
        )

    df = repo.trends(league, min_price_ex=float(min_price))
    if df.empty:
        st.info(
            "No price data yet. Either nobody has triggered a refresh, or the league has "
            "no cached prices. Hit **Refresh prices** on the Market tab, or wait up to 3 hours "
            "for the scheduled cron."
        )
        return

    if chosen_cats:
        df = df[df["category"].isin(chosen_cats)]
    if div_ex:
        df["current_price_div"] = (df["current_price_ex"] / div_ex).round(3)

    df["poe2db"] = df["name"].apply(poe2db_url)

    tab_gain, tab_loss, tab_all = st.tabs(["📈 Gainers", "📉 Losers", "All movers"])
    with tab_gain:
        _render_table(df, sort_col="change_24h_pct", ascending=False, top_n=int(top_n), div_ex=div_ex)
    with tab_loss:
        _render_table(df, sort_col="change_24h_pct", ascending=True, top_n=int(top_n), div_ex=div_ex)
    with tab_all:
        st.caption("Click any column header to re-sort.")
        _render_table(df, sort_col="change_24h_pct", ascending=False, top_n=None, div_ex=div_ex)


def _render_table(
    df: pd.DataFrame, sort_col: str, ascending: bool, top_n: int | None, div_ex: float | None,
) -> None:
    view = df.dropna(subset=[sort_col]).sort_values(sort_col, ascending=ascending)
    if top_n:
        view = view.head(top_n)
    if view.empty:
        st.info("No items with enough history yet. Wait a few cron cycles.")
        return

    cols = ["icon_url", "name", "category", "current_price_ex"]
    rename = {
        "icon_url": " ",
        "name": "Item",
        "category": "Category",
        "current_price_ex": "Price (ex)",
    }
    if div_ex:
        cols.append("current_price_div")
        rename["current_price_div"] = "Price (div)"
    cols += ["price_24h_ago_ex", "change_24h_pct", "change_24h_ex", "change_7d_pct", "poe2db"]
    rename.update({
        "price_24h_ago_ex": "24h ago (ex)",
        "change_24h_pct": "24h Δ %",
        "change_24h_ex": "24h Δ (ex)",
        "change_7d_pct": "7d Δ %",
        "poe2db": "poe2db",
    })

    st.dataframe(
        view[cols].rename(columns=rename),
        use_container_width=True,
        hide_index=True,
        column_config={
            " ": st.column_config.ImageColumn("", width="small"),
            "Price (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Price (div)": st.column_config.NumberColumn(format="%.3f"),
            "24h ago (ex)": st.column_config.NumberColumn(format="%.2f"),
            "24h Δ %": st.column_config.NumberColumn(format="%+.1f%%"),
            "24h Δ (ex)": st.column_config.NumberColumn(format="%+.2f"),
            "7d Δ %": st.column_config.NumberColumn(format="%+.1f%%"),
            "poe2db": st.column_config.LinkColumn("poe2db", display_text="open ↗"),
        },
    )

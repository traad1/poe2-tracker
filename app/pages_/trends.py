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

    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        top_n = st.number_input("Top N", min_value=5, max_value=100, value=10, step=5)
    with c2:
        min_price = st.number_input(
            "Min price (ex)", min_value=0.0, value=5.0, step=1.0,
            help="Filter out junk where a 0.01→0.05 ex bump shows as a 400% gainer.",
        )
    with c3:
        min_listings = st.number_input(
            "Min listings", min_value=0, value=5, step=1,
            help="Filters out low-confidence prices. poe.ninja-style: <5 listings is suspicious.",
        )
    with c4:
        all_cats = sorted(repo.load_prices(league)["category"].dropna().unique().tolist())
        chosen_cats = st.multiselect(
            "Categories", options=all_cats, default=all_cats,
            help="Filter the trend universe.",
        )

    df = repo.trends(league, min_price_ex=float(min_price))
    if min_listings > 0:
        df = df[df["listing_count"].fillna(0) >= min_listings]
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

    tab_gain, tab_loss, tab_all, tab_item = st.tabs(
        ["📈 Gainers", "📉 Losers", "All movers", "Item detail"]
    )
    with tab_gain:
        _render_table(df, sort_col="change_24h_pct", ascending=False, top_n=int(top_n), div_ex=div_ex)
    with tab_loss:
        _render_table(df, sort_col="change_24h_pct", ascending=True, top_n=int(top_n), div_ex=div_ex)
    with tab_all:
        st.caption("Click any column header to re-sort. Volatility = coefficient of variation "
                   "over the last 7 days (std / mean × 100), so it's comparable across price levels. "
                   "High volatility = flippable (wide spread). Low volatility = storage.")
        _render_table(df, sort_col="change_24h_pct", ascending=False, top_n=None, div_ex=div_ex)
    with tab_item:
        _render_item_detail(league, df, div_ex)


def _render_item_detail(league: str, trends_df: pd.DataFrame, div_ex: float | None) -> None:
    if trends_df.empty:
        st.info("No items in the trend universe yet.")
        return
    options = trends_df.sort_values("name")
    label_to_id = {
        f'{r["name"]} ({r["category"]})  —  {r["current_price_ex"]:,.2f} ex': int(r["item_id"])
        for _, r in options.iterrows()
    }
    pick = st.selectbox("Item", list(label_to_id.keys()), key="trends_item_pick")
    item_id = label_to_id[pick]
    item_row = options[options["item_id"] == item_id].iloc[0]

    history = repo.load_item_history(league, item_id)
    if history.empty or len(history) < 2:
        st.info("Not enough history yet — need at least two snapshots. Check back after the next cron cycle.")
        return

    # Headline numbers
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current (ex)", f"{item_row['current_price_ex']:,.2f}")
    if div_ex and div_ex > 0:
        c2.metric("Current (div)", f"{item_row['current_price_ex'] / div_ex:.3f}")
    if pd.notna(item_row.get("change_24h_pct")):
        c3.metric("24h Δ", f"{item_row['change_24h_pct']:+.1f}%")
    if pd.notna(item_row.get("volatility_pct")):
        c4.metric("7d volatility", f"{item_row['volatility_pct']:.1f}%")

    # Chart
    chart_df = history.rename(columns={"fetched_at": "When (UTC)", "price_ex": "Price (ex)"})
    st.line_chart(chart_df.set_index("When (UTC)")["Price (ex)"], height=320)

    if div_ex and div_ex > 0:
        chart_div = history.copy()
        chart_div["Price (div)"] = chart_div["price_ex"] / div_ex
        chart_div = chart_div.rename(columns={"fetched_at": "When (UTC)"})
        with st.expander("Same chart in divines"):
            st.line_chart(chart_div.set_index("When (UTC)")["Price (div)"], height=320)

    with st.expander("Raw snapshots"):
        st.dataframe(
            history.rename(columns={"fetched_at": "When (UTC)", "price_ex": "Price (ex)"}),
            use_container_width=True, hide_index=True,
            column_config={
                "Price (ex)": st.column_config.NumberColumn(format="%.4f"),
            },
        )


def _render_table(
    df: pd.DataFrame, sort_col: str, ascending: bool, top_n: int | None, div_ex: float | None,
) -> None:
    view = df.dropna(subset=[sort_col]).sort_values(sort_col, ascending=ascending)
    if top_n:
        view = view.head(top_n)
    if view.empty:
        st.info("No items with enough history yet. Wait a few cron cycles.")
        return

    LOW_CONF_THRESHOLD = 5
    view = view.copy()
    view["item_label"] = view.apply(
        lambda r: ("⚠️ " if pd.notna(r.get("listing_count"))
                   and r["listing_count"] < LOW_CONF_THRESHOLD else "") + str(r["name"]),
        axis=1,
    )

    cols = ["icon_url", "item_label", "category", "current_price_ex"]
    rename = {
        "icon_url": " ",
        "item_label": "Item",
        "category": "Category",
        "current_price_ex": "Price (ex)",
    }
    if div_ex:
        cols.append("current_price_div")
        rename["current_price_div"] = "Price (div)"
    cols += ["listing_count", "sparkline",
             "change_24h_pct", "change_24h_ex",
             "change_7d_pct", "volatility_pct", "poe2db"]
    rename.update({
        "listing_count": "Listings",
        "sparkline": "Trend",
        "change_24h_pct": "24h Δ %",
        "change_24h_ex": "24h Δ (ex)",
        "change_7d_pct": "7d Δ %",
        "volatility_pct": "7d vol %",
        "poe2db": "poe2db",
    })

    st.dataframe(
        view[cols].rename(columns=rename),
        use_container_width=True,
        hide_index=True,
        column_config={
            " ": st.column_config.ImageColumn("", width="small"),
            "Item": st.column_config.TextColumn(
                "Item", help="⚠️ = <5 active listings; price may be a single fake listing.",
            ),
            "Price (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Price (div)": st.column_config.NumberColumn(format="%.3f"),
            "Listings": st.column_config.NumberColumn(format="%d"),
            "Trend": st.column_config.LineChartColumn(
                "Trend", help="7-day daily series from poe2scout, with our snapshot history "
                              "as a fallback.",
            ),
            "24h Δ %": st.column_config.NumberColumn(format="%+.1f%%"),
            "24h Δ (ex)": st.column_config.NumberColumn(format="%+.2f"),
            "7d Δ %": st.column_config.NumberColumn(format="%+.1f%%"),
            "7d vol %": st.column_config.NumberColumn(format="%.1f%%"),
            "poe2db": st.column_config.LinkColumn("poe2db", display_text="open ↗"),
        },
    )

"""Watchlist tab — flips + inflation hedges."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from poe2 import repository as repo
from .market import poe2db_url


def render(league: str) -> None:
    st.header("Watchlist")
    st.caption("Flips track buy/sell targets. Hedges show value in mirror-equivalents — "
               "the goal is your hedge stack growing as fast as the mirror price.")

    mirror_ex = repo.mirror_price_ex(league)
    tab_flip, tab_hedge = st.tabs(["Flips", "Inflation Hedges"])
    with tab_flip:
        _render_flips(league)
    with tab_hedge:
        _render_hedges(league, mirror_ex)


def _render_flips(league: str) -> None:
    wl = repo.load_watchlist(league, tag="flip")
    if wl.empty:
        st.info("No flip targets yet. Add items from the Market tab (tag: flip).")
        return
    wl = wl.copy()
    wl["poe2db"] = wl["name"].apply(poe2db_url)
    st.dataframe(
        wl[["icon_url", "name", "category", "current_price_ex", "target_buy_ex", "target_sell_ex",
            "profit_margin_ex", "margin_pct", "distance_to_buy_pct", "note", "poe2db"]]
          .rename(columns={
              "icon_url": " ",
              "name": "Item",
              "category": "Category",
              "current_price_ex": "Market (ex)",
              "target_buy_ex": "Target buy (ex)",
              "target_sell_ex": "Target sell (ex)",
              "profit_margin_ex": "Profit (ex)",
              "margin_pct": "Margin %",
              "distance_to_buy_pct": "Market vs buy %",
              "note": "Note",
              "poe2db": "poe2db",
          }),
        use_container_width=True,
        hide_index=True,
        column_config={
            " ": st.column_config.ImageColumn("", width="small"),
            "Market (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Target buy (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Target sell (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Profit (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Margin %": st.column_config.NumberColumn(format="%+.1f%%"),
            "Market vs buy %": st.column_config.NumberColumn(format="%+.1f%%"),
            "poe2db": st.column_config.LinkColumn("poe2db", display_text="open ↗"),
        },
    )
    _remove_picker(league, wl, key_prefix="flip")


def _render_hedges(league: str, mirror_ex: float | None) -> None:
    wl = repo.load_watchlist(league, tag="hedge")
    if wl.empty:
        st.info(
            "No hedges yet. The Mirror-tier guide suggests laddering investments in this order:\n\n"
            "1. **Omen of Abyssal Echoes** — entry level, used with putrefaction crafts\n"
            "2. **Omen of Whittling** and **Omen of Light** — bulk of the savings; mid/high-end crafting\n"
            "3. **Hinekora's Lock** — long-term; corruption / sanctify on expensive items\n"
            "4. **Mirror of Kalandra** — endgame\n\n"
            "Add them from the Market tab (filter 'Omen of' or 'Hinekora', tag: hedge)."
        )
        return

    view = wl[["icon_url", "name", "category", "current_price_ex", "target_buy_ex", "note"]].copy()
    if mirror_ex and mirror_ex > 0:
        view["price_in_mirror"] = view["current_price_ex"] / mirror_ex
        view["buy_in_mirror"] = view["target_buy_ex"] / mirror_ex
    else:
        view["price_in_mirror"] = None
        view["buy_in_mirror"] = None
    view["poe2db"] = view["name"].apply(poe2db_url)

    st.dataframe(
        view.rename(columns={
            "icon_url": " ",
            "name": "Item",
            "category": "Category",
            "current_price_ex": "Market (ex)",
            "target_buy_ex": "Entry (ex)",
            "price_in_mirror": "Market (mirrors)",
            "buy_in_mirror": "Entry (mirrors)",
            "note": "Note",
            "poe2db": "poe2db",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            " ": st.column_config.ImageColumn("", width="small"),
            "Market (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Entry (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Market (mirrors)": st.column_config.NumberColumn(format="%.6f"),
            "Entry (mirrors)": st.column_config.NumberColumn(format="%.6f"),
            "poe2db": st.column_config.LinkColumn("poe2db", display_text="open ↗"),
        },
    )
    if mirror_ex:
        st.caption(
            f"Current mirror price: **{mirror_ex:,.0f} ex**. Mirror-equivalent values stay flat "
            "if your hedge keeps pace with inflation; they drop if mirror outruns it."
        )
    else:
        st.warning(
            "Mirror price not in cache yet — refresh prices on the Market tab with the Currency "
            "category selected so mirror-equivalent math works."
        )
    _remove_picker(league, wl, key_prefix="hedge")


def _remove_picker(league: str, wl: pd.DataFrame, key_prefix: str) -> None:
    with st.expander("Remove an item"):
        label_to_id = {str(r["name"]): int(r["item_id"]) for _, r in wl.iterrows()}
        if not label_to_id:
            return
        picked = st.selectbox("Item to remove", list(label_to_id.keys()),
                              key=f"{key_prefix}_remove_pick")
        if st.button("Remove", key=f"{key_prefix}_remove_btn"):
            repo.remove_from_watchlist(league, label_to_id[picked])
            st.rerun()

"""Market tab — live prices + add to watchlist."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from poe2 import repository as repo
from poe2.api import Poe2ScoutClient

# (kind, api_id, label) — the categories we offer to the user.
# Curated for the inflation/flip workflow from the Mirror-tier guide:
#   - currency: includes Mirror, Divine, Exalt (needed for mirror-equivalent math)
#   - ritual: Omens — the inflation-hedge investments (Whittling, Light, Abyssal Echoes,
#     Putrefaction, etc.) Names confirmed for 0.5 only once GGG ships the patch.
#   - essences/runes/soul cores: crafting consumables, often flipped early league
#   - uniques: the boots/belts/rings/amulets/weapons referenced in the tier-1/7/11 farming guide
CATEGORIES = [
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

DEFAULT_CATS = ["Currency", "Ritual Omens", "Essences", "Runes"]


def poe2db_url(item_name: str) -> str:
    """Build a deep-link to poe2db.tw for an item.

    poe2db uses underscored names: 'Mirror of Kalandra' -> /us/Mirror_of_Kalandra.
    Apostrophes are kept as-is (verified working for Hinekora's Lock).
    """
    if not item_name:
        return ""
    return "https://poe2db.tw/us/" + item_name.strip().replace(" ", "_")


@st.cache_data(ttl=600)
def available_leagues() -> list[tuple[str, bool]]:
    leagues = Poe2ScoutClient().list_leagues()
    return [(L.value, L.is_current) for L in leagues]


def league_selector() -> str:
    leagues = available_leagues()
    current = next((v for v, is_cur in leagues if is_cur), None)
    values = [v for v, _ in leagues]
    idx = values.index(current) if current else 0
    league = st.selectbox(
        "League",
        values,
        index=idx,
        help="Defaults to the current league (IsCurrent=true on poe2scout).",
        key="_league_picker",
    )
    st.session_state["_current_league"] = league
    return league


def render(league: str) -> None:
    st.header("Market")
    st.caption("Live prices from poe2scout.com — cached locally for 30 minutes.")

    chosen_cats = st.multiselect(
        "Categories to track",
        options=[label for _, _, label in CATEGORIES],
        default=DEFAULT_CATS,
        help="Pick what to fetch. Ritual Omens are the inflation-hedge items "
             "(Whittling, Light, Abyssal Echoes, Putrefaction, Hinekora's Lock).",
    )

    age = repo.cache_age_minutes(league)
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Refresh prices", type="primary"):
            with st.spinner("Pulling fresh prices..."):
                selected = [(k, aid, lbl) for k, aid, lbl in CATEGORIES if lbl in chosen_cats]
                n = repo.refresh_prices(league, selected)
                st.success(f"Cached {n} items.")
                st.rerun()
    with col2:
        if age is None:
            st.info(f"No cached data yet for **{league}** — click **Refresh prices**.")
        else:
            mirror_ex = repo.mirror_price_ex(league)
            div_ex = repo.divine_price_ex(league)
            bits = [f"Cache age: {age:.1f} min (TTL 30 min)."]
            if div_ex:
                bits.append(f"Divine: **{div_ex:,.0f} ex**")
            if mirror_ex:
                bits.append(f"Mirror: **{mirror_ex:,.0f} ex**")
            st.caption(" • ".join(bits))

    df = repo.load_prices(league)
    if df.empty:
        return

    if chosen_cats:
        df = df[df["category"].isin(chosen_cats)]

    _render_market_table(league, df)


def _render_market_table(league: str, df: pd.DataFrame) -> None:
    div_ex = repo.divine_price_ex(league)

    c1, c2 = st.columns([2, 1])
    with c1:
        search = st.text_input(
            "Filter by name",
            placeholder="e.g. Divine, Omen of, Hinekora",
        )
    with c2:
        tier_options = ["All", "Divine-tier (≥ 1 div)", "Exalt-tier (< 1 div)"]
        tier_help = (
            "Splits items by whether their typical listing price is in divines or exalts. "
            "Cutoff is the live Divine→Exalt rate."
            if div_ex else "Cache the Currency category to enable the price-tier filter."
        )
        tier = st.selectbox("Price tier", tier_options, help=tier_help, disabled=not div_ex)

    view = df.copy()
    if search:
        view = view[view["name"].str.contains(search, case=False, na=False)]
    if div_ex and tier == "Divine-tier (≥ 1 div)":
        view = view[view["current_price_ex"] >= div_ex]
    elif div_ex and tier == "Exalt-tier (< 1 div)":
        view = view[view["current_price_ex"] < div_ex]
    view = view.sort_values("current_price_ex", ascending=False, na_position="last")

    if div_ex and div_ex > 0:
        view["price_div"] = (view["current_price_ex"] / div_ex).round(3)
    else:
        view["price_div"] = None

    view["poe2db"] = view["name"].apply(poe2db_url)

    # Confidence marker: items with <5 listings get a ⚠️ prefix on the Item column.
    # Mirrors poe.ninja's "low confidence" treatment without needing a separate column.
    LOW_CONF_THRESHOLD = 5

    def _label(row) -> str:
        lc = row.get("listing_count")
        marker = "⚠️ " if pd.notna(lc) and lc < LOW_CONF_THRESHOLD else ""
        return marker + str(row["name"])

    view["item_label"] = view.apply(_label, axis=1)

    cols = ["icon_url", "item_label", "category", "current_price_ex", "price_div",
            "listing_count", "sparkline", "change_24h_pct", "poe2db"]

    st.dataframe(
        view[cols].rename(columns={
            "icon_url": " ",
            "item_label": "Item",
            "category": "Category",
            "current_price_ex": "Price (ex)",
            "price_div": "Price (div)",
            "listing_count": "Listings",
            "sparkline": "Trend",
            "change_24h_pct": "24h Δ %",
            "poe2db": "poe2db",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            " ": st.column_config.ImageColumn("", width="small"),
            "Item": st.column_config.TextColumn(
                "Item",
                help=f"⚠️ marks items with fewer than {LOW_CONF_THRESHOLD} active listings — "
                     "their displayed price may be a single fake listing.",
            ),
            "Price (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Price (div)": st.column_config.NumberColumn(format="%.3f"),
            "Listings": st.column_config.NumberColumn(format="%d"),
            "Trend": st.column_config.LineChartColumn(
                "Trend", help="poe2scout's 7-day daily series, or our own snapshot history "
                              "as a fallback.",
            ),
            "24h Δ %": st.column_config.NumberColumn(format="%+.1f%%"),
            "poe2db": st.column_config.LinkColumn("poe2db", display_text="open ↗"),
        },
    )

    with st.expander("Add an item to my watchlist"):
        if view.empty:
            st.write("No items match your filter.")
            return
        label_to_id = {
            f'{r["name"]} ({r["category"]})': int(r["item_id"]) for _, r in view.iterrows()
        }
        picked = st.selectbox("Item", list(label_to_id.keys()), key="market_add_pick")
        tag = st.radio(
            "Track as",
            options=["flip", "hedge"],
            horizontal=True,
            help="**Flip**: short-term buy-low / sell-high. **Hedge**: long-term inflation hedge "
                 "(Whittling, Light, Abyssal Echoes, Hinekora's Lock). Hedge items are shown "
                 "with mirror-equivalent values in the Watchlist tab.",
            key="market_add_tag",
        )
        c1, c2 = st.columns(2)
        with c1:
            buy = st.number_input("Target buy (ex)", min_value=0.0, value=0.0, step=1.0,
                                   key="market_add_buy")
        with c2:
            sell = st.number_input("Target sell (ex)", min_value=0.0, value=0.0, step=1.0,
                                    key="market_add_sell")
        note = st.text_input("Note (optional)", placeholder="e.g. flip strategy or league timing",
                              key="market_add_note")
        if st.button("Save to watchlist", key="market_add_save"):
            repo.add_to_watchlist(
                league=league,
                item_id=label_to_id[picked],
                target_buy_ex=buy or None,
                target_sell_ex=sell or None,
                tag=tag,
                note=note,
            )
            st.success(f"Added as {tag}.")
            st.rerun()

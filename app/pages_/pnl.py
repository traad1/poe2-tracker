"""PnL tracker — fungible trades (avg cost) and crafted-item lots (cost + premium)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from poe2 import repository as repo


def render(league: str) -> None:
    st.header("PnL Tracker")
    st.caption(
        "**Trades** = fungible buys/sells (currency, omens, hedges) on average-cost basis. "
        "**Crafted Lots** = one row per unique item with line-item costs (base + mods + sockets) "
        "and a sale price."
    )

    tab_trades, tab_lots = st.tabs(["Trades (fungible)", "Crafted Lots"])
    with tab_trades:
        _render_entry_form(league)
        st.divider()
        _render_summary(league)
        st.divider()
        _render_trade_log(league)
    with tab_lots:
        _render_lots(league)


def _render_entry_form(league: str) -> None:
    prices = repo.load_prices(league)
    name_hint = prices["name"].tolist() if not prices.empty else []

    with st.form("trade_entry", clear_on_submit=True):
        st.subheader("Log a trade")
        c1, c2 = st.columns([2, 1])
        with c1:
            item_name = st.text_input(
                "Item name",
                placeholder="e.g. Omen of Whittling",
                help=("Any text — keep the spelling consistent across buys and sells so they "
                      "match. Suggestions: " + ", ".join(name_hint[:5]) if name_hint else "Any text."),
            )
        with c2:
            side = st.radio("Side", ["buy", "sell"], horizontal=True)
        c3, c4 = st.columns(2)
        with c3:
            qty = st.number_input("Quantity", min_value=0.0, value=1.0, step=1.0)
        with c4:
            price_ex = st.number_input("Price per unit (ex)", min_value=0.0, value=0.0, step=1.0)
        note = st.text_input("Note (optional)")

        submitted = st.form_submit_button("Record trade", type="primary")
        if submitted:
            if not item_name.strip():
                st.error("Item name is required.")
            elif qty <= 0 or price_ex <= 0:
                st.error("Quantity and price must be positive.")
            else:
                repo.record_trade(
                    league=league,
                    item_name=item_name.strip(),
                    side=side,
                    qty=qty,
                    price_ex=price_ex,
                    note=note,
                    executed_at=datetime.now(timezone.utc),
                )
                st.success(f"Recorded {side} {qty:g} {item_name} @ {price_ex:g} ex.")
                st.rerun()


def _render_summary(league: str) -> None:
    st.subheader("Realized PnL")
    summary = repo.pnl_summary(league)
    if summary.empty:
        st.info("No trades recorded yet.")
        return

    total_realized = float(summary["realized_pnl_ex"].sum())
    total_open_at_cost = float(summary["open_value_at_cost_ex"].sum())
    mirror_ex = repo.mirror_price_ex(league)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total realized PnL", f"{total_realized:,.0f} ex")
    c2.metric("Open position (at cost)", f"{total_open_at_cost:,.0f} ex")
    if mirror_ex:
        c3.metric("Realized PnL (mirrors)", f"{total_realized / mirror_ex:.4f}")

    st.dataframe(
        summary.rename(columns={
            "item": "Item",
            "bought_qty": "Bought",
            "sold_qty": "Sold",
            "open_qty": "Open",
            "avg_cost_ex": "Avg cost (ex)",
            "realized_pnl_ex": "Realized PnL (ex)",
            "roi_pct": "ROI %",
            "open_value_at_cost_ex": "Open @ cost (ex)",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Avg cost (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Realized PnL (ex)": st.column_config.NumberColumn(format="%+.2f"),
            "ROI %": st.column_config.NumberColumn(format="%+.1f%%"),
            "Open @ cost (ex)": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def _render_trade_log(league: str) -> None:
    st.subheader("Trade log")
    trades = repo.load_trades(league)
    if trades.empty:
        return

    view = trades[["executed_at", "item_name", "side", "qty", "price_ex", "total_ex", "note"]].copy()
    view["executed_at"] = pd.to_datetime(view["executed_at"]).dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(
        view.rename(columns={
            "executed_at": "When (UTC)",
            "item_name": "Item",
            "side": "Side",
            "qty": "Qty",
            "price_ex": "Price (ex)",
            "total_ex": "Total (ex)",
            "note": "Note",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Price (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Total (ex)": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    with st.expander("Delete a trade"):
        id_to_label = {
            int(r["id"]): f'#{r["id"]} {r["side"]} {r["qty"]:g} {r["item_name"]} @ {r["price_ex"]:g}'
            for _, r in trades.iterrows()
        }
        picked = st.selectbox("Trade to delete", list(id_to_label.keys()),
                              format_func=lambda i: id_to_label[i])
        if st.button("Delete trade"):
            repo.delete_trade(int(picked))
            st.rerun()


# ---------- crafted lots ----------

KINDS = ["base", "mod", "socket", "jewel", "other"]


def _render_lots(league: str) -> None:
    div_ex = repo.divine_price_ex(league)
    if not div_ex:
        st.warning(
            "Divine→Exalt rate not in cache — costs entered as 'div' won't convert. "
            "Cache the Currency category on the Market tab first."
        )

    _render_new_lot_form(league)
    st.divider()
    _render_lot_summary(league, div_ex)
    st.divider()
    _render_lot_detail(league, div_ex)


def _render_new_lot_form(league: str) -> None:
    with st.expander("Start a new lot", expanded=False):
        with st.form("new_lot", clear_on_submit=True):
            c1, c2 = st.columns([3, 2])
            with c1:
                name = st.text_input("Item name", placeholder="e.g. T11 Sapphire Ring (crafted)")
            with c2:
                category = st.text_input("Category", placeholder="Ring / Boots / Helmet...")
            note = st.text_input("Note (optional)", placeholder="Strategy, base details, etc.")
            if st.form_submit_button("Create lot", type="primary"):
                if not name.strip():
                    st.error("Item name required.")
                else:
                    lid = repo.create_lot(league, name, category=category, note=note)
                    st.success(f"Lot #{lid} created. Open it below to add cost lines.")
                    st.rerun()


def _render_lot_summary(league: str, div_ex: float | None) -> None:
    st.subheader("All lots")
    lots = repo.load_lots(league)
    if lots.empty:
        st.info("No lots yet. Start one above.")
        return

    realized = lots[lots["status"] == "sold"]
    open_lots = lots[lots["status"] == "open"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Realized PnL (ex)", f"{realized['pnl_ex'].sum():,.0f}")
    c2.metric("Open lots", f"{len(open_lots)}")
    c3.metric("Capital tied up (ex)", f"{open_lots['total_cost_ex'].sum():,.0f}")

    view = lots[["id", "item_name", "category", "status", "total_cost_ex",
                 "sold_price_ex", "pnl_ex", "roi_pct", "cost_line_count"]].copy()
    if div_ex:
        view["total_cost_div"] = (view["total_cost_ex"] / div_ex).round(3)
        view["sold_price_div"] = (view["sold_price_ex"] / div_ex).round(3)
        view["pnl_div"] = (view["pnl_ex"] / div_ex).round(3)
        cols = ["id", "item_name", "category", "status",
                "total_cost_ex", "total_cost_div",
                "sold_price_ex", "sold_price_div",
                "pnl_ex", "pnl_div", "roi_pct", "cost_line_count"]
    else:
        cols = ["id", "item_name", "category", "status", "total_cost_ex",
                "sold_price_ex", "pnl_ex", "roi_pct", "cost_line_count"]

    st.dataframe(
        view[cols].rename(columns={
            "id": "Lot #",
            "item_name": "Item",
            "category": "Category",
            "status": "Status",
            "total_cost_ex": "Cost (ex)",
            "total_cost_div": "Cost (div)",
            "sold_price_ex": "Sold (ex)",
            "sold_price_div": "Sold (div)",
            "pnl_ex": "PnL (ex)",
            "pnl_div": "PnL (div)",
            "roi_pct": "ROI %",
            "cost_line_count": "# lines",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Cost (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Cost (div)": st.column_config.NumberColumn(format="%.3f"),
            "Sold (ex)": st.column_config.NumberColumn(format="%.2f"),
            "Sold (div)": st.column_config.NumberColumn(format="%.3f"),
            "PnL (ex)": st.column_config.NumberColumn(format="%+.2f"),
            "PnL (div)": st.column_config.NumberColumn(format="%+.3f"),
            "ROI %": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )


def _render_lot_detail(league: str, div_ex: float | None) -> None:
    lots = repo.load_lots(league)
    if lots.empty:
        return

    st.subheader("Edit a lot")
    id_to_label = {
        int(r["id"]): f'#{r["id"]} {r["item_name"]} — {r["status"]} ({r["total_cost_ex"]:.0f} ex)'
        for _, r in lots.iterrows()
    }
    lot_id = st.selectbox(
        "Lot",
        list(id_to_label.keys()),
        format_func=lambda i: id_to_label[i],
        key="lot_detail_pick",
    )
    if lot_id is None:
        return
    lot = lots[lots["id"] == lot_id].iloc[0]

    lines = repo.load_cost_lines(int(lot_id))
    if not lines.empty:
        view = lines[["kind", "label", "cost_input", "cost_currency", "cost_ex"]].rename(
            columns={
                "kind": "Kind",
                "label": "Label",
                "cost_input": "Cost",
                "cost_currency": "Cur",
                "cost_ex": "Cost (ex)",
            }
        )
        st.dataframe(
            view, use_container_width=True, hide_index=True,
            column_config={
                "Cost": st.column_config.NumberColumn(format="%.2f"),
                "Cost (ex)": st.column_config.NumberColumn(format="%.2f"),
            },
        )
    else:
        st.caption("No cost lines yet — add the base item and crafting inputs below.")

    # Add cost line
    with st.form(f"add_line_{lot_id}", clear_on_submit=True):
        st.markdown("**Add a cost line**")
        c1, c2, c3, c4 = st.columns([1, 3, 1, 1])
        with c1:
            kind = st.selectbox("Kind", KINDS, key=f"k_{lot_id}")
        with c2:
            label = st.text_input("Label", placeholder="e.g. Omen of Putrefaction + Rib",
                                   key=f"l_{lot_id}")
        with c3:
            amount = st.number_input("Cost", min_value=0.0, value=0.0, step=1.0, key=f"a_{lot_id}")
        with c4:
            currency = st.radio("Cur", ["ex", "div"], horizontal=True, key=f"c_{lot_id}")
        if st.form_submit_button("Add line"):
            if not label.strip():
                st.error("Label is required.")
            elif amount <= 0:
                st.error("Cost must be > 0.")
            else:
                try:
                    repo.add_cost_line(int(lot_id), kind, label, amount, currency, league)
                    st.success(f"Added {kind} line.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # Sale and lot actions
    sold = pd.notna(lot["sold_price_ex"])
    st.markdown("**Sale**")
    if sold:
        sale_ex = float(lot["sold_price_ex"])
        sale_div = f" ({sale_ex / div_ex:.3f} div)" if div_ex else ""
        st.write(f"Sold for **{sale_ex:,.2f} ex**{sale_div}. PnL: **{lot['pnl_ex']:+.2f} ex** "
                  f"(ROI {lot['roi_pct']:+.1f}%).")
        if st.button("Clear sale", key=f"clearsale_{lot_id}"):
            repo.clear_lot_sale(int(lot_id))
            st.rerun()
    else:
        with st.form(f"sale_{lot_id}", clear_on_submit=True):
            c1, c2 = st.columns([2, 1])
            with c1:
                sale_amount = st.number_input("Sale price", min_value=0.0, value=0.0, step=1.0,
                                                key=f"sa_{lot_id}")
            with c2:
                sale_cur = st.radio("Currency", ["ex", "div"], horizontal=True, key=f"sc_{lot_id}")
            if st.form_submit_button("Record sale", type="primary"):
                if sale_amount <= 0:
                    st.error("Sale price must be > 0.")
                else:
                    try:
                        repo.record_lot_sale(int(lot_id), sale_amount, sale_cur, league)
                        st.success("Sale recorded.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    with st.expander("Delete this lot"):
        if st.button("Delete lot (cannot undo)", key=f"del_{lot_id}"):
            repo.delete_lot(int(lot_id))
            st.rerun()

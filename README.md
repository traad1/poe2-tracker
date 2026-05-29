# Path of Exile 2 — Trade & Economy Tracker

Personal Streamlit app focused on **one thing**: tracking the PoE 2 marketplace, flipping items, and beating mirror-driven inflation. Patch 0.5 ("Return of the Ancients") goes live 2026-05-29 — this is built to be used from day one of the new league.

## What's here

Three tabs, all driven by [poe2scout.com](https://poe2scout.com)'s public API (cached locally for 30 minutes):

- **Market** — live prices across currency, ritual omens, essences, runes, soul cores, fragments, breach, expedition, and uniques. Filter by name, sort, and add items to your watchlist with one click.
- **Watchlist** — split into two sub-tabs:
  - **Flips**: target buy/sell + auto-calculated margin %, distance-to-buy %.
  - **Inflation Hedges**: long-term holds (Omen of Whittling, Light, Abyssal Echoes, Hinekora's Lock) shown in *mirror-equivalent* values. Goal: your stack keeps pace with the rising mirror price.
- **PnL** — log actual executed buys/sells. Shows realized PnL per item (average-cost basis), open positions, and total ROI. Also expresses total PnL in mirrors.

## Strategy this app supports

The hedge laddering follows Viking 0071's Mirror-tier guide ([source video](https://www.youtube.com/watch?v=I0dD-5I_xlw)):

1. Start: **Omen of Abyssal Echoes** (cheap, used with putrefaction crafts)
2. Bulk: **Omen of Whittling / Omen of Light** (every mid-to-high-end craft burns them; big crafters hoard them, keeping prices high)
3. Long-term: **Hinekora's Lock** (corruption/sanctify on expensive items late league)
4. Endgame: **Mirror of Kalandra**

The app prices these in both Exalts and Mirrors so you can see at a glance whether your hedge is actually outrunning inflation.

> Note: 0.5 introduces new omen and item names. On patch day, the items may not appear under exactly these labels right away — search the Market tab for "Omen of" or "Hinekora" and add whatever poe2scout has indexed.

## Running locally

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501 by default.

## Layout

```
app/
├── app.py                  # Streamlit entry — three tabs
├── requirements.txt
├── poe2/
│   ├── api.py              # Poe2ScoutClient — public API wrapper
│   └── repository.py       # SQLite cache + watchlist + trades; UI-facing data layer
├── pages_/
│   ├── market.py           # Market tab + league selector
│   ├── watchlist.py        # Flips & Hedges
│   └── pnl.py              # Trade log + realized PnL
└── data/                   # SQLite db (gitignored)
```

The `poe2/` package never imports Streamlit. That keeps the data layer reusable if/when this moves off Streamlit (Postgres + Next.js for a hosted version).

## Patch-day notes (2026-05-29)

- The league selector defaults to whichever league is flagged `IsCurrent=true` on poe2scout, so it should auto-flip to the new 0.5 league as soon as their API updates.
- On day one, `24h ago` columns will be blank (no history yet) — the table handles this without crashing.
- Refresh Market with the **Currency** category selected before doing anything else, so the Mirror price loads and the Hedges tab can do mirror-equivalent math.

## Data source attribution

Prices come from poe2scout's public API (`https://poe2scout.com/api`). Cache TTL is 30 minutes to be polite to their service.

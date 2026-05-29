# Deploying online (free tier)

Target stack: **Neon** (free Postgres) + **GitHub** (code) + **Streamlit Community Cloud** (free hosting). Total cost: $0. Auto-redeploys on every `git push`.

Time: ~20 minutes for the first deploy. Updates after that are one `git push`.

---

## 1. Create a Neon database (Postgres, free)

1. Go to https://neon.tech and sign up (GitHub login is fastest).
2. After login, click **"Create project"**. Name it `poe2-tracker`. Region: pick whatever's closest to you (e.g. `aws-us-east-2`). Postgres version: default is fine.
3. Once the project is created, Neon shows a **"Connection string"** panel. Copy the full URI — it looks like:
   ```
   postgresql://USERNAME:PASSWORD@ep-something-12345.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Save it somewhere private (a password manager). You'll paste it into Streamlit Cloud in step 3.

You don't need to create tables — the app does that on first connection.

**Free tier limits**: 512 MB storage (way more than you need), DB auto-suspends after 5 min idle and wakes on first query (adds ~1 second to the first request after idle — fine).

---

## 2. Push the code to GitHub

The app is already a git repo at the project root. Push it to your GitHub account:

```bash
cd "/Users/thomasraad/Documents/Agentic Workflows/Path of Exile 2"

# Create a new repo on GitHub and push (uses the gh CLI you already have authed):
gh repo create poe2-tracker --public --source=. --remote=origin --push
```

If you'd rather keep the repo private, use `--private` instead of `--public`. **Streamlit Community Cloud free tier can still deploy private repos** if you give it access during setup.

After this, your code lives at `https://github.com/traad1/poe2-tracker`.

---

## 3. Deploy on Streamlit Community Cloud

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **"New app"**.
3. Fill in:
   - **Repository**: `traad1/poe2-tracker`
   - **Branch**: `main`
   - **Main file path**: `app/app.py`
   - **App URL** (subdomain): anything you like, e.g. `poe2-tracker.streamlit.app`
4. Click **"Advanced settings"** → **"Secrets"**. Paste this, with your real Neon URI:
   ```toml
   DATABASE_URL = "postgresql://USERNAME:PASSWORD@ep-something.neon.tech/neondb?sslmode=require"
   ```
5. Click **Deploy**. First build takes ~3 minutes (installing deps).
6. When it shows "Your app is running", open the URL. The first page load takes ~1 sec longer than usual because Neon is waking up from idle — normal.

---

## 4. Verify it's working

On the live app:

1. Check the league selector loads (it queries poe2scout, not your DB).
2. Click **Refresh prices** on the Market tab with Currency selected. You should see Divine and Mirror prices appear in the header — those came from Neon.
3. Add an item to your watchlist and reload the page. If it persists, Postgres is wired up correctly. (If it resets, the app fell back to SQLite — check Streamlit Cloud → Settings → Secrets for typos.)

---

## 5. Pushing updates

Every change you want live, do this from your laptop:

```bash
cd "/Users/thomasraad/Documents/Agentic Workflows/Path of Exile 2"
git add -A
git commit -m "Describe the change"
git push
```

Streamlit Cloud picks up the push automatically and redeploys in ~1-2 minutes. The "Manage app" panel on the Streamlit Cloud dashboard shows live build logs if anything fails.

### Schema changes

If you add a new table or column in `repository.py`, the `_init_schema()` function runs on every cold start, so new tables appear automatically. **Adding a column to an existing table** is the one case you need to handle manually — either:
- Drop and recreate the table (loses data — only OK for caches like `price_snapshot`), or
- Add a one-off migration block in `_init_schema()`, similar to the SQLite `tag` migration already there but using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for Postgres.

---

## 6. Local development after deploying

Your laptop should keep using SQLite (fast, no network), and only the cloud app uses Neon. The code is set up so:

- **DATABASE_URL unset** (your laptop) → SQLite at `app/data/tracker.db`
- **DATABASE_URL set** (Streamlit Cloud secrets) → Neon Postgres

If you ever want to point your *local* dev against Neon (e.g. to debug what's on the live DB):
```bash
export DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"
streamlit run app.py
```
Don't commit your real connection string anywhere — `.streamlit/secrets.toml` and `app/.streamlit/secrets.toml` are gitignored, and there's a `.streamlit/secrets.toml.example` showing the format.

---

## Troubleshooting

**"Could not connect to database"** — Neon DB might still be paused. Open the Neon console once; the first manual query wakes it. Then redeploy.

**Watchlist resets between visits** — the app fell back to SQLite (which is ephemeral on Streamlit Cloud). Confirm `DATABASE_URL` is set in Streamlit Cloud → app → Settings → Secrets, and that the URI starts with `postgresql://` (not `postgres://` — though the app normalizes both).

**Build fails with `psycopg2` install error** — Streamlit Cloud sometimes needs `psycopg2-binary` not `psycopg2`. `requirements.txt` already uses `psycopg2-binary`; if you ever pin a different version, keep the `-binary` suffix.

**App is slow on first load** — Neon's free tier sleeps after 5 min idle. First query wakes it (~1 sec extra). For a personal tool this is fine.

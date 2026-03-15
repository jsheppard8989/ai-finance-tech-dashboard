# Three Dashboard Sections — Tie-Out & Consistency

The main site has **three sections** that should be tied out, buttoned up, and consistent.

## 1. Left: The Overton Window + Emerging Terms

| What | Source | Limit |
|------|--------|-------|
| **Overton Window** | `mainContent.overton` from `get_main_page_content()` → active `overton_terms` (display_on_main=1, status='active') | 8 |
| **Emerging Terms** | `dashboardData.suggestedTerms` from `get_suggested_terms_for_website()` → `v_priority_suggestions` | 4 |

- **Flow:** AI episode analysis → `emerging_terms` in JSON → ingested into `suggested_terms` → promotion (votes or auto-curate) → `overton_terms` → shown in Overton Window.
- **Consistency:** No definitions on main flow; Overton only. Person-name filter prevents names appearing as terms.

## 2. Middle: Latest Insights

| What | Source | Limit |
|------|--------|-------|
| **Insights** | `mainContent.insights` from `get_main_page_content()` → `latest_insights` joined to `podcast_episodes` for `key_tickers` | 8 |
| **Key tickers** | From episode AI JSON (`podcast_episodes.key_tickers`) only — no fallback. |

- **Flow:** Transcript → AI analysis → `latest_insights` + episode `key_tickers` / `investment_thesis` / `key_takeaways` → export → data.js.
- **Consistency:** Key tickers on cards and Deep Dive come only from AI JSON.

## 3. Right: Podcast Pundits + Alpha or Atrophy

| What | Source | Limit |
|------|--------|-------|
| **Pundits** | `pundits.json` (or `dashboardData.pundits`) from `export_for_website()` → entities with `guest_primary` + last episode thesis/takeaways | 20 |
| **Alpha or Atrophy** | `ticker_scores.json` / `dashboardData.tickerScores` from `get_all_ticker_scores()`. | — |

- **Flow:** Entities/appearances (guest_primary) → join to `podcast_episodes` for `last_episode_*` and `investment_thesis` / `key_takeaways` → `last_main_idea` → pundits.json.
- **Consistency:** Frontend falls back to `./data/pundits.json` if `dashboardData.pundits` is missing.

---

## Tie-Out Checklist

- **Single source per section:** Overton = overton_terms only; Insights = latest_insights + episode key_tickers; Pundits = entities + appearances + episode thesis/takeaways.
- **Counts in one place:** `status.json` includes `main_page: { overton, insights, pundits }` — the exact counts shown on the main page (written at export time).
- **Pipeline Health:** Shows these section counts so you can verify at a glance that all three are populated as expected.
- **Empty states:** Each section has a clear “No X yet” message and a short note on what fills it (e.g. “Promote from Emerging Terms”, “Run transcript analysis”, “Ensure entity pipeline has run”). Optional link to Pipeline Health.
- **Blurbs:** Each section has a one-line “Source: …” so it’s obvious where the data comes from.

---

## Making Changes

- **Change limits:** Edit `get_main_page_content()` in `db_manager.py` (insights/overton LIMIT) and pundits query LIMIT; `get_suggested_terms_for_website(limit=…)` in `export_data.py`.
- **Change what’s “on main”:** Toggle `display_on_main` / `status` in DB; archive flow updates these. Export regenerates data.js and status.json.
- **Verify:** Open Pipeline Health and check “Main page” counts match what you see on the dashboard.

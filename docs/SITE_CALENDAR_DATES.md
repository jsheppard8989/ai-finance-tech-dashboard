# Site calendar dates (one source of truth for **display**)

## Canonical data

- **Database / export**: Podcast and insight dates are stored as **calendar dates**, usually `YYYY-MM-DD` (`podcast_episodes.episode_date`, `latest_insights.source_date`).
- **`pipeline_state.json`**: The `published` field on each tracked episode is the **RSS / curation** timestamp string, often normalized to `YYYY-MM-DD` when possible (see `export_data.py`).

Those strings denote a **calendar day**, not a moment in UTC.

## Why the main page looked “one day early”

In JavaScript, `new Date('2026-03-19')` is specified as **UTC midnight** on that date. In US timezones, `toLocaleDateString` can show **March 18**, while Pipeline Health showed the raw string **`2026-03-19`** — same episode, inconsistent UI.

## What we do instead

- **`site/js/common.js`**: `formatSiteCalendarDate()` parses a leading `YYYY-MM-DD` as **local** year/month/day, then formats with `toLocaleDateString`.
- **`parseSiteDateForSort()`**: Same local interpretation for sorting insights.
- **Pipeline Health**: “Published” column uses `getPublishedIso()` + `formatSiteCalendarDate()` so it matches the main dashboard wording (e.g. `Mar 19, 2026`). RSS-derived dates no longer use `toISOString().slice(0,10)` when building a calendar date (that could shift the day in some timezones).

Full timestamps (e.g. `last_pipeline_run`, `generatedAt`) still use `new Date(iso)` — those are true instants, not bare calendar dates.

# Date consistency across the site

All user-facing dates for **episode-derived content** (insights, pundits) must show the **episode release date** so the same episode shows the same date everywhere.

## Single source of truth

- **Canonical date:** `podcast_episodes.episode_date` (or `published_date` when we persist it; both should be the episode’s release date).
- **Insights:** `latest_insights.source_date` must equal the linked episode’s `episode_date`. The site prefers `episode_release_date` (from the join) for display so it always matches the episode.
- **Pundits:** `last_episode_date` comes from `podcast_episodes.episode_date` via the export join. Display uses the same format as insights (e.g. “Mar 13, 2026”).

## Where dates are set

| Step | What | Rule |
|------|------|------|
| **analyze_transcript** | `podcast_episodes.episode_date` | From sidecar `published_date` or AI `episode_date`; never use “today” for display. |
| **auto_pipeline** (promote to insight) | `latest_insights.source_date` | Always `episode_date` of the episode; never substitute today() for old episodes. |
| **Export** | `get_main_page_content()` | Insights get `episode_release_date` from join to `podcast_episodes`; pundits get `last_episode_date` from same table. |
| **Frontend** | Insight card date | Use `episode_release_date \|\| source_date`, formatted with `toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })`. |
| **Frontend** | Pundit card date | Format `last_episode_date` with the same options so it matches insights. |

## Backfill / maintenance

If insight dates were ever set incorrectly (e.g. old “today” logic):

```bash
python3 pipeline/sync_insight_dates.py
```

Then re-run export so the site gets updated data.

## Audit checklist

- [ ] All insights with `podcast_episode_id` have `source_date = (SELECT episode_date FROM podcast_episodes WHERE id = podcast_episode_id)`.
- [ ] Frontend uses `episode_release_date` when available for insight date.
- [ ] Insight and pundit dates use the same locale format (e.g. “Mar 12, 2026”).
- [ ] No code path sets insight `source_date` to “today” for episode-derived insights.

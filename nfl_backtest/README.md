## NFL Underdog Parlay Backtest

This is a **separate project** inside your workspace for testing your NFL edge:

> Take the **6 biggest underdogs against the spread** each week, and bet **all 3-leg parlays** that cover every way 3 of those 6 dogs can win.

We start with **free data (Path B)** using public historical NFL scores + betting lines (e.g. the Kaggle *\"NFL scores and betting data\"* dataset) instead of paid odds feeds.

---

### 1. Data we need

For each NFL game we want at least:

- **Season + week** (or date we can map to a week)
- **Home team, away team**
- **Final score**
- **Closing spread** (point spread vs the spread)

Your model for now only needs **spread data** to:

1. Rank games each week by **largest point spread underdogs**.
2. Measure outcomes **against the spread (ATS)**.

Later we can extend this to **moneyline parlays** once we have a richer dataset.

---

### 2. Where to put the raw data

1. Download the historical data CSV (e.g. from Kaggle).
2. Save it under:

   - `nfl_backtest/data/nfl_scores_betting.csv`

3. Make sure the CSV has at least these columns (exact names can be mapped in code):

   - `date` or `schedule_date`
   - `team_home`, `team_away`
   - `score_home`, `score_away`
   - `spread_favorite` (or similar)
   - `team_favorite_id` (to know which side is favored)

If column names differ, we will **adapt the loader** to your specific file.

---

### 3. Strategy definition (what the code will simulate)

For each **regular-season week**:

1. Identify all games in that week.
2. Compute the **point spread** for the underdog in each game.
3. Sort by **largest underdog spread** (most points given).
4. Take the **top 6 underdogs**.
5. Form **all 3-leg combinations** of those 6 underdogs:

   - Number of bets \( = \binom{6}{3} = 20 \)

6. For each parlay:

   - Check whether each leg **covers the spread ATS**.
   - If **all 3 cover**, the parlay “wins” for ATS purposes.

We’ll start by tracking:

- **Weekly number of winning parlays**
- **Hit rate** (winning parlays / total parlays)

Once we add **moneyline prices**, we’ll convert this into **$ returns**.

---

### 4. How this code will be structured

- `nfl_backtest/`
  - `README.md` — this file
  - `data/` — raw CSV(s) you download
  - `backtest.py` — core backtest logic (to be implemented)
  - `requirements.txt` — Python dependencies (pandas, etc.)

The goal is to keep this **isolated from the finance/AI dashboard**, so your main workspace stays focused while this project proves out your NFL edge.

---

### 5. Running the backtest (once implemented)

From the workspace root:

```bash
cd ~/.openclaw/workspace/nfl_backtest
python3 backtest.py
```

This will:

- Load the CSV from `data/`
- Group games by week
- Find the 6 biggest underdogs ATS each week
- Compute the 20 3-leg ATS-parlay outcomes
- Print season-level summary stats

Once we confirm the logic and data quality, we can:

- Extend to **moneyline parlays with actual payout math**
- Add **multiple seasons**
- Export results to a small dashboard or notebook for visualization.


# Dragonfly 7 — Phase 1 data plumbing (Yahoo via yfinance)

Private. Paper book only. Everything here is **provisional** data and is stamped
`source: "yahoo", provisional: true`. The governor blocks provisional data from
live approval (`structural_blocks(..., book="live", provisional_data=...)` →
`provisional_source_live`). Paper cards may use it.

State and caches live under `dragonfly/state/live/` (gitignored). Override with
`DRAGONFLY_STATE_DIR` (tests do).

Install: `python3 -m pip install --user -r dragonfly/requirements.txt`
(jsonschema + yfinance). Python 3.9 compatible.

## Watchlist — `dragonfly/build_watchlist.py` → `dragonfly/watchlist.json`

- Candidates: S&P 500 (Wikipedia constituents table, carries GICS sector) ∪
  Nasdaq-100 (Nasdaq's own list at `api.nasdaq.com`; Wikipedia no longer
  carries that table).
- Gates are the existing universe gates, called through
  `risk_math.universe_reasons` (not re-typed): price ≥ $10, 20-day ADV ≥ $25M,
  spread ≤ max($0.05, 0.15% of mid).
- Price and ADV run on every candidate (from `bars.py`). Survivors are ranked by
  ADV, descending.
- **Spread gate on the ADV-ranked shortlist only.** Yahoo bid/ask is fetched in
  rank order, in small batches, until `cap` (200) names pass.
  - A name that is **never spread-checked** because the cap filled first is
    **excluded** (`not_spread_checked`). It is never admitted to the watchlist
    or the scan.
  - A name whose **bid/ask fetch fails**, or whose quote is unusable (missing,
    zero, or crossed), is **excluded** (`spread_unavailable`).
  - Checked in the final batch after the cap filled: `beyond_cap` (excluded).
- Output carries `as_of`, `gates`, `funnel`, `excluded_summary`, per-name
  measurements, and every excluded ticker with its reason. The scanner reads
  only `names`.
- Run during regular hours so bid/ask is live.

### Known data-quality issue (read before trusting the list)

Yahoo's `bid`/`ask` for many Nasdaq-listed names is not an NBBO. On
2026-09-25 intraday, AAPL showed 336.96 × 341.98 (size 2 × 4), MSFT 498.20 ×
518.97, AMZN 236.40 × 261.65, while NYSE names (JPM, XOM, BAC, KO) showed
penny-wide quotes with real size. Some quotes were crossed. The spread gate
fails closed on these, so the watchlist is gate-correct but **skewed away from
Nasdaq-listed mega-caps**. Fixing this needs a better quote source; it must not
be fixed by softening the gate.

## Bars — `dragonfly/bars.py`

- One `Ticker.history` call per name (auto-adjusted daily bars), cached as JSON
  in `dragonfly/state/live/cache/bars/<TICKER>.json`.
- Incremental refresh: with a cache, one call from the second-to-last cached
  session. The last cached bar (possibly partial intraday) is always replaced.
  If the completed overlap bar's close moved > 0.5%, Yahoo re-adjusted history
  (split/dividend) and the name is refetched in full.
- Computed from the cache: Wilder ATR(14), 20-day ADV (dollars and shares),
  relative volume (last bar ÷ prior 20-bar mean). During the session the partial
  bar is excluded from ATR/ADV, and `rvol20` is its raw pace (`rvol_partial`).
- Fail closed: `BarsUnavailable(reason)` for `fetch_failed` / `empty_history`.

## Chains — `dragonfly/chains.py`

- `get_chain(ticker, expiration)`: one `Ticker.option_chain(exp)` call for one
  expiration. Keeps contractSymbol, strike, bid, ask, volume, openInterest,
  impliedVolatility (Yahoo IV), lastTradeDate.
- Fail closed: `ChainUnavailable(reason)` for `fetch_failed`, `no_expirations`,
  `expiration_not_listed`, `empty_chain`, `no_expiration_in_range`. Missing
  values stay `None`; nothing is filled in. `contract_passes_gates` applies the
  plan's option gates and fails any contract with a missing field.

## Tests

- `python3 dragonfly/test_risk_math.py` — constitution vectors plus the
  provenance block and universe-gate vectors.
- `python3 dragonfly/test_phase1_data.py` — offline (fakes only): bars math,
  incremental cache, chain fail-closed, watchlist selection including the
  never-checked / failed-quote exclusions.

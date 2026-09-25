# Dragonfly 7 — Phase 1 data plumbing (Yahoo via yfinance)

Private. Paper book only. Everything here is **provisional** data and is stamped
`source: "yahoo", provisional: true`. The governor blocks provisional data from
live approval (`structural_blocks(..., book="live", provisional_data=...)` →
`provisional_source_live`). Paper cards may use it.

State and caches live under `dragonfly/state/live/` (gitignored). Override with
`DRAGONFLY_STATE_DIR` (tests do).

Install: `python3 -m pip install --user -r dragonfly/requirements.txt`
(jsonschema + yfinance). Python 3.9 compatible.

## Load guards — `dragonfly/guards.py` (never overlap the site pipeline)

Every Dragonfly network fetch (bars, chains, watchlist quotes) calls
`guards.before_fetch()` first; every CLI entry point calls `guards.preflight()`.

- **Pipeline lock.** While the site pipeline's lock is held by a live PID,
  Dragonfly refuses. Entry points wait up to `DRAGONFLY_LOCK_WAIT_SECONDS`
  (default 300 s, polling every 10 s) and then abort; per-request checks do not
  wait, so a pipeline that starts mid-run stops Dragonfly at its next request.
  A guard stop aborts a watchlist build and writes nothing.
  Default lock paths on Jared's Mac (override: `DRAGONFLY_PIPELINE_LOCK`, one
  path or several joined by `:`):
  - `…/ai-finance-tech-dashboard/pipeline/state/auto_pipeline.lock` (the file
    `auto_pipeline.py` actually writes)
  - `…/ai-finance-tech-dashboard/pipeline/auto_pipeline.lock` (also honoured)
  A lock with an unreadable PID counts as held; a dead PID is stale.
- **Daemon windows.** Refuses inside 05:00–07:59, 12:00–14:59 and 22:00–23:59
  America/Chicago unless explicitly overridden (`--allow-daemon-window` or
  `DRAGONFLY_ALLOW_DAEMON_WINDOW=1`). The midday catch-up (14:40) and the
  evening catch-up (22:10) sit inside these windows too.
- **Pre-open timing.** The planned ~07:10 pre-open is inside the morning
  window (the daemon's second morning run lands ~06:40–07:15). Recommended
  start: **08:05 CT** — after the morning window closes and the morning
  publish has landed, before the 08:30 CT open. Trigger it on the clock at
  08:05 (the lock guard still covers a late morning run), not at 07:10.
- **Cache-first.** Bars CLI/builder skip the network when a name's cache is
  younger than `DRAGONFLY_BARS_MAX_AGE_MINUTES` (30). Chains for a named
  expiration reuse a cache younger than `DRAGONFLY_CHAINS_MAX_AGE_MINUTES` (15).

## Watchlist — `dragonfly/build_watchlist.py` → `dragonfly/watchlist.json`

- **US listed common stock only.** Before any Yahoo call, each candidate's
  security type is resolved from Nasdaq's descriptor: the screener's security
  name (one call for all US listings), then the per-symbol quote-info
  `stockType` where the screener name is blank, then an explicit denylist of
  known depositary receipts (`KNOWN_DEPOSITARY_RECEIPTS`, tightening only).
  Common stock, ordinary shares and subordinate-voting shares of directly
  listed issuers, and REIT common shares of beneficial interest count as
  common. Excluded, never admitted: `depositary_receipt` (ADR/ADS/NY registry
  shares), `not_common_stock` (preferred, units, etc.), and
  `security_type_unknown` when the type cannot be determined (fail closed).
  Excluded names never reach the bars or spread steps, so the next names by
  ADV backfill. The list may be shorter than 200; the gates stay exact.

- Candidates: S&P 500 (Wikipedia constituents table, carries GICS sector) ∪
  Nasdaq-100 (Nasdaq's own list at `api.nasdaq.com`; Wikipedia no longer
  carries that table).
- Gates are the existing universe gates, called through
  `risk_math.universe_reasons` (not re-typed): price ≥ $10, 20-day ADV ≥ $25M,
  spread ≤ max($0.05, 0.15% of mid).
- Price and ADV run on every candidate (from `bars.py`). Survivors are ranked by
  ADV, descending.
- **Quotes on the ADV-ranked shortlist only.** Yahoo bid/ask/last is fetched in
  rank order, in small batches, until `cap` (200) names are admitted. Names
  ranked below the cutoff are `beyond_cap` (excluded).
- **Paper quote model (default, `--spread-mode modeled`, PAPER ONLY; Jared,
  2026-09-25).** Each name's quote is resolved by `risk_math.resolve_quote`:
  1. Yahoo bid/ask passes the spread gate as-is → real quote,
     `spread_source: "yahoo"`.
  2. Crossed, zero, missing, or gate-fail → mid = (bid+ask)/2, modeled
     bid/ask = mid ∓ $0.025, `spread_source: "modeled_mid_0.05"`,
     `provisional: true`.
  3. Sanity guard: if that mid is more than the gate width
     (`stock_spread_limit(last)` = max($0.05, 0.15% of last)) away from
     Yahoo's last trade, or bid/ask give no usable mid (missing/zero on either
     side), last trade is the mid: `spread_source: "modeled_last_0.05"`,
     `mid_source: "last_trade"`, provisional.
  4. No usable mid and no usable last trade → excluded
     (`no_usable_mid_or_last`). Fail closed. A mid with no last trade to check
     it against is admitted as `mid_source: "quote_mid_unverified"`.
  - The price gate (on the resolved mid) and the ADV gate stay exact. Thin
    names still fall out on ADV. Modeled names are admitted on price/ADV; the
    spread gate is satisfied by the modeled $0.05 spread for paper purposes.
  - The modeled $0.05 is **not** re-checked against the 0.15% width. It would
    pass anyway: the gate is max($0.05, 0.15%·mid), so $0.05 is always legal.
    For low-priced names it is wider than 0.15% (0.5% at $10) and overstates
    friction for liquid names priced under $33.33.
  - Per name: `bid`/`ask`/`mid`/`spread` (as resolved), `spread_source`,
    `mid_source`, `provisional`, raw `yahoo_bid`/`yahoo_ask`/`last_trade`.
    `quote_fallbacks` records why each modeled name fell back.
  - `not_spread_checked` and `spread_unavailable` no longer occur in modeled
    mode.
  - **Live:** any card using a `modeled_*` spread source is rejected
    (`structural_blocks(..., spread_source=...)` → `provisional_source_live`,
    and `sources_provisional` treats a modeled source as provisional).
- **Strict mode (`--spread-mode exact`)**, the previous behavior: only names
  whose Yahoo bid/ask passes the gate are admitted.
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
penny-wide quotes with real size. Some quotes were crossed. In strict mode the
spread gate fails closed on these, so the list is **skewed away from
Nasdaq-listed mega-caps**. The paper quote model above admits them on a modeled
$0.05 spread (provisional, paper only, live-blocked). A real fix for live still
needs a better quote source; it must not be fixed by softening the gate.

## Paper fills — `risk_math.paper_buy_fill` / `paper_sell_fill` / `paper_entry_fill`

- Buys fill at mid + $0.025 (rounded up to the cent), sells at mid − $0.025
  (rounded down). Mid is the resolved quote mid; for a buy-stop entry it
  defaults to the trigger. Labeled `fill_type: hypothetical`.
- The max-fill rule is unchanged: a buy fill above `max_fill` = trigger × 1.0015
  invalidates the card. Because $0.025 > 0.15% of prices under $16.67, a paper
  entry at the trigger on a name under $16.67 always exceeds `max_fill` and is
  invalidated (e.g. trigger $12.00 → fill $12.03 > max $12.02).

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

- **Shortlist only.** The entry point (`fetch_shortlist_chains` / the CLI)
  takes an explicit list of tickers and refuses — never truncates — more than
  `DRAGONFLY_CHAINS_MAX_NAMES` (default 20). A watchlist document, a bare
  string, or the full 200-name list is refused. One `Ticker` per name.

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
- `python3 dragonfly/test_phase1_modeled.py` — offline: `resolve_quote`
  vectors (yahoo-pass, crossed, zero, missing, gate-fail, mid-vs-last swap,
  no-mid-no-last exclusion), paper buy/sell fills and the max-fill interaction,
  live-reject / paper-pass for both modeled sources, modeled selection.
- `python3 dragonfly/test_phase1_guards.py` — offline: lock guard (live /
  dead / unreadable PID, bounded wait), daemon windows and override, guarded
  fetchers, chains shortlist cap, security-type resolution and ADR exclusion
  with backfill, cache-first bars.

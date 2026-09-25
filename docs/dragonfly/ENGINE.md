# Dragonfly 7 — pre-open engine, READY and DONE

Private. Paper book. Code: `dragonfly/engine/`, `dragonfly/market_calendar.py`,
`dragonfly/setup_gates.py`. Tests: `python3 dragonfly/test_engine.py`
(offline). Python 3.9 compatible (the Mac runs `/usr/bin/python3` 3.9.6); needs
`jsonschema` (`dragonfly/requirements.txt`). Without it the engine refuses to
write anything.

The Mac is the engine of record. The engine reads the live book from
`dragonfly/state/live/book.json` (gitignored) and the bars cache
`dragonfly/state/live/cache/bars/` (read-only), and exchanges files with box
agents through a local checkout of the private repo `dragonfly-private`:

- `handoff/YYYY-MM-DD/` — written by the Mac (prep bundle, READY, and the engine's `cards/`).
- `inbox/YYYY-MM-DD/` — written by box agents (regime snapshot, drafts, red team files, brief).

The engine makes **no market-data calls**. Every number it decides on is
recomputed from files already on the Mac.

## Timeline (America/Chicago, NYSE sessions only)

| CT | Step | Writes |
| --- | --- | --- |
| 15:00+ prior session | Mac prep (built separately): marks the book **after the close**, refreshes the bars cache, prep data | `state/live/book.json`, `state/live/cache/bars/`, `handoff/<date>/…` |
| 08:05 | Pre-open job (built separately). **Last step:** `python3 -m dragonfly.engine ready` | `handoff/<date>/READY` by ~08:07 |
| 08:07–08:11 | Market Read (box) | `inbox/<date>/regime_snapshot.json` |
| 08:11–08:15 | Trade Architect (box) | `inbox/<date>/<trade_id>.draft.json` |
| 08:13–08:20 | Red Team (box), rolling, one file per draft; **cutoff 08:20** | `inbox/<date>/<trade_id>.redteam.json` |
| 08:08–08:24 | **Engine** (Mac), polls every 60 s. Sizes each trade about a minute after its red team file lands. DONE after 08:20 once every draft has a card | `handoff/<date>/cards/<trade_id>.json`, `cards/DONE` |
| 08:22–08:29 | Ditka's brief | inbox |

On an NYSE holiday or weekend the engine logs `not_session` and exits 0
without writing anything. 08:08–08:24 sits outside every pipeline daemon
window, and the engine makes no market-data calls, so it never calls the load
guards (`dragonfly/guards.py`). A held pipeline lock does not block it (tested).

## Layout

```
dragonfly-private/
  handoff/2026-09-28/
    manifest.json, measurements.json, ...   Mac prep (before READY)
    READY                                   last file of the 08:05 job
    cards/
      DF-2026-0001.json                     one frozen card per trade_id
      unidentified/<draft-stem>.json        drafts with no usable / a duplicate trade_id
      DONE                                  engine finished for the day
  inbox/2026-09-28/
    regime_snapshot.json                    Market Read (regime_snapshot.schema.json)
    DF-2026-0001.draft.json                 Architect (trade_draft.schema.json)
    DF-2026-0001.redteam.json               Red Team (trade_redteam.schema.json)
Mac, gitignored:
  dragonfly/state/live/book.json            live book (engine_book.schema.json)
  dragonfly/state/live/cache/bars/<T>.json  bars cache (#266), read-only here
  dragonfly/state/live/engine/<date>.json   engine's first-seen times (drafts, red team files)
```

## Drafts (Architect → engine)

Schema: `docs/dragonfly/schemas/trade_draft.schema.json`; example
`docs/dragonfly/examples/trade_draft.json`. A draft is a trade card minus
everything the engine owns. It carries **no** `sizing`, **no** `risk_decision`,
**no** `entry.max_fill`, and no status, red team, human decision, watcher, or
timestamps the engine sets. It adds:

- `measurements` — the Architect's numbers, **checked, never used**:
  `price` (previous-session close), `atr` (Wilder ATR(14) at the previous
  session), `adv_dollars` (20-day), `spread` (stock), `sector`,
  `reference_level`, `signal_session`, `base_level` (momentum_pullback only,
  required there), optional `spread_source`, `source`, `as_of`. `provisional`
  is ignored: provenance comes from the Mac's own sources.
  `reference_level` by setup: catalyst_breakout = the breakout level;
  momentum_pullback = the continuation pivot the trigger clears;
  failed_breakdown = the reclaimed support; compression_expansion = the
  compression range high. `signal_session` = the breakout, pullback, reversal
  or expansion bar.
- `evidence.relative_volume` — the signal session's relative volume (checked).
- `option` — required for `call` / `put` / `debit_spread`: contract, expiration,
  bid, ask, open interest, volume (net / min across legs for a spread) and
  `underlying_stop`. For options, `entry.price` is the debit, `stop` the
  premium stop, and the target a premium.
- optional `book` (must match the engine's book), `drafted_at`, `notes`.

### Options contract (Ditka, 2026-09-25)

For options, the extension and stop-distance ATR are measured **on the
underlying**, with the Mac's ATR:

- extension = (underlying previous close − `reference_level`) / ATR
- stop distance = (underlying previous close − `option.underlying_stop`) / ATR

For stock: extension = (`entry.price` − `reference_level`) / ATR and stop
distance = (`max_buy_fill(entry.price)` − `stop`) / ATR. The setup gates also
use the underlying (`underlying_stop` for "stop below the reversal bar" and
"stop outside the compression range"). The option's bid/ask/OI/volume come
from the draft: the Mac has no options cache, so those are not recomputed (see
"Not yet recomputed" below).

## Red Team files (Red Team → engine)

Schema `docs/dragonfly/schemas/trade_redteam.schema.json`; example
`docs/dragonfly/examples/trade_redteam.json`. One file per draft, written
**after** the draft: `inbox/<date>/<trade_id>.redteam.json`.

```json
{"schema_version": "1.0.0", "trade_id": "DF-2026-0001", "as_of": "2026-09-28T08:14:00-05:00",
 "flags": {"crowded_options": false, "sector_lagging": true, "wide_spread_but_legal": false,
           "contradictory_filing": false, "valuation_extreme": false, "gap_history": false,
           "event_just_outside_window": false},
 "narrative": "The case against the trade ...",
 "draft_sha256": "<optional: pins the review to one draft version>"}
```

- All seven flags are required booleans. Optional: `draft_sha256` (if present
  and different from the draft's sha256, the file is invalid:
  `redteam_reviews_other_draft_version`), `flag_evidence`, `reviewer`, `warning_count`.
- **warning_count is derived by the engine** from the flags. A file's own
  `warning_count` is ignored; if it differs, that is logged and recorded
  (`engine.inputs.redteam.warning_count_claimed`).
- The Mac also measures **`gap_history`** itself (a gap |open − previous
  close| in the last 60 sessions larger than 1.5 × the planned stop distance;
  underlying stop for options). If the Mac finds one and the red team did not
  flag it, the engine adds it (`engine.inputs.warnings_added_by_engine`). It
  can add the warning, never remove one. If the Mac cannot measure it, the
  warning is counted (fail closed; it only tightens).
- `warning_count` goes into the existing `caps(warning_count)` /
  `size_stock` / `size_option` path. Two or more warnings in a normal regime
  pull the planned-loss and name-heat caps to cautious; the book heat cap is
  unchanged (`engine.inputs.warnings_tightened`).
- **Red Team never blocks or sizes.** Keys that try (`hard_blocks`, `blocks`,
  `block`, `decision`, `veto`, `sizing`, `size`, `units`, `risk_decision`,
  `max_fill`, `status`, `approve`, `approved`, `reasons`) are stripped before
  validation, logged, and recorded in `engine.inputs.redteam.ignored_fields`.
  The card's `red_team.hard_blocks` are the engine's; `red_team.decision` is
  `block` when the engine blocked, else `pass`; `warnings` and `narrative` come
  from the file.
- `red_team.decision: "pending"` is **removed** from `trade_card.schema.json`:
  the engine only cards after the red team file, so it is never needed.

## What the engine does with a draft

Each pass: `git ls-remote` (cheap); pull with rebase only if the remote ref
moved; list `inbox/<date>/*.draft.json`; record first-seen times of new drafts
and red team files; card every draft that is ready; commit and push
`handoff/<date>/cards/` (retrying a non-fast-forward with a rebase, up to 5
times); then DONE. **One engine pass per trade, no version-2 cards.**

In order:

1. **Unusable draft → reject record.** Not JSON, fails the draft schema, no
   usable `trade_id`, or a duplicate: a reject record
   (`engine_reject_record.schema.json`) with the reasons.
2. **Draft first seen after the cutoff → `late`** (`late_draft`), unsized.
3. **Pre-sized or invalid → rejected, never sized.** `draft_carries_sizing`,
   `draft_carries_risk_decision`, `draft_carries_max_fill`, `book_mismatch`,
   `trade_id_filename_mismatch`, `trade_id_year_mismatch`,
   `invalidation_not_machine_checkable`, `time_stop_invalid` (entry must be an
   NYSE session on or after the session date; exit must equal
   `risk_math.time_stop_session(entry, NYSE sessions)` from the static
   calendar), `calendar_not_covered` (a date outside the calendar tables).
4. **Stale book → `book_stale`, never sized.** See below. Applies to every
   draft, red team file or not.
5. **Red team gate.** No valid red team file yet: before the cutoff the draft
   waits (no card); after the cutoff it gets a `late` card with `late_redteam`
   (plus the file's problems, e.g. `redteam_schema_invalid: …`), unsized. A
   red team file counts as on time only if a pass scheduled at or before
   08:20:00 first saw it **valid**.
6. **After the window** (a pass later than 08:24): `engine_window_closed`.
7. **No regime snapshot yet:** before the cutoff the draft waits; after it, it
   is carded with mode `stand_down` and `regime_missing` (fail closed).
8. **Measure, gate, govern** (next sections): Mac measurements, setup gates,
   engine rules and `risk_math.structural_blocks` → any block = `status:
   "blocked"`, reasons in `risk_decision.reasons` and `red_team.hard_blocks`.
   Otherwise `size_stock` / `size_option` off `max_buy_fill(entry.price)` with
   the derived `warning_count`: approved = `status: "pending_human"`, a sizing
   reject = `status: "risk_rejected"`. Mode is `regime_to_mode()` tightened by
   `effective_risk_mode()` on the book's breaker inputs.
9. **Pending exposure.** Today's approved cards count as positions when the
   next draft is sized (heat, notional, cash, sector, setup), in carding order.
   Two approvals can never add up past a cap.

Every card carries an `engine` block: outcome, reasons, draft file and sha256,
first seen, cutoff, carded at, book, and the inputs used (red team file,
sha256, first seen / first valid, derived warning_count, Mac measurements with
sources, mismatches, gate details, structural inputs, sizing inputs). All
timestamps are America/Chicago with offset.

**Frozen.** Once `cards/<trade_id>.json` exists it is never rewritten, even if
the draft or its red team file changes (logged) or the local engine state is
lost. A fix needs a new `trade_id`.

**Fail closed.** Every card is validated before it is written. A card that
fails `trade_card.schema.json` is replaced by a reject record
(`card_schema_invalid`); if that also fails, the engine stops with an error.
A missing or invalid `book.json` is a loud error and nothing is written.

## NYSE calendar — `dragonfly/market_calendar.py`

Static tables from NYSE's published holiday calendar
(nyse.com/markets/hours-calendars): full-day closures for 2026, 2027 and
2028, and 1:00 p.m. ET early closes (2026-11-27, 2026-12-24, 2027-11-26,
2028-07-03, 2028-11-24). Used wherever sessions are counted: the engine's
session check (holiday = no-op), `time_stop_session` validation, the previous
session for the book rule and the measurements, the signal-age rule, and the
catalyst recency rule. A date outside the tables raises `CalendarNotCovered`
and fails closed. **Extend the tables before 2029.**

## Book freshness — `book_stale`

`book.json` `as_of` must be at or after the previous session's close: 16:00 ET
= **15:00 CT** on the previous NYSE session (12:00 CT after an early close;
e.g. the Monday after Thanksgiving week needs a mark at or after Friday
12:00 CT). Otherwise the engine fails closed on new risk: every draft gets a
`blocked` card with `book_stale` and nothing is sized
(`engine.inputs.book_freshness` records both times). This only tightens.

## Measurements — recomputed on the Mac (`dragonfly/engine/measure.py`)

Sources, read-only:

| Value | Source (first found wins) |
| --- | --- |
| bars | `state/live/cache/bars/<TICKER>.json` (the #266 cache), else a `bars` list on the ticker's row in `handoff/<date>/measurements.json` |
| sector, spread, spread_source | the ticker's row in `handoff/<date>/measurements.json`, else `dragonfly/watchlist.json` |
| provisional | `true` unless the bars come from the prep file and that row says `"provisional": false` |

Recomputed from bars: `price` (previous-session close), `atr` (Wilder
ATR(14) at the previous session), `adv_dollars` (20-day), relative volume on
the signal session (volume / prior 20-day average), all with
`dragonfly/bars.py`. Draft vs Mac, beyond tolerance = `measurement_mismatch`:

| Field | Tolerance |
| --- | --- |
| price | 0.5% of the Mac value |
| atr | 5% |
| adv_dollars | 5% |
| relative_volume (`evidence.relative_volume`) | 5%, at least 0.05× |
| spread (stock only) | $0.01 |
| sector | exact (case-insensitive) |

`measurement_unavailable` (fail closed) when the Mac cannot compute a required
value: no cache and no prep bars; the cache lacks the previous session's bar
("cache stale"); too little history for a calculation; no sector; no spread
(stock); momentum_pullback without `base_level`. The card lists each item in
`engine.inputs.measurements.details.unavailable`.

Engine rule `signal_session_stale`: `measurements.signal_session` must be one
of the last 5 NYSE sessions before the session date.

## Setup gates — structural blocks (`dragonfly/setup_gates.py`)

Computed on the Mac's bars through `signal_session`, with the Mac's ATR, and
recorded in `engine.inputs.measurements.details.gates`. Each failure is a
structural block on the card.

| Setup | Gate (operating plan §6) | Block code |
| --- | --- | --- |
| catalyst_breakout | breakout-session rvol ≥ 1.8× 20-day average | `breakout_rvol_low` |
| | breakout session closed above the named level | `breakout_not_confirmed` |
| | entry (stock: trigger; option: underlying close) within 1.0 ATR of the level | `breakout_entry_far` |
| momentum_pullback | 20-session return > 8%, **or** close > SMA20, SMA20 > SMA20 five sessions earlier, and SMA20 > SMA50 | `pullback_no_momentum` |
| | a swing high (highest high of the last 10 sessions) before the signal bar | `pullback_not_formed` |
| | pullback depth (swing high − close) between 0.4 and 1.5 ATR | `pullback_depth_out_of_range` |
| | no close below `base_level` since the swing high | `pullback_broke_base` |
| | mean pullback volume < impulse volume (mean of the 5 sessions ending at the swing high) | `pullback_volume_not_lower` |
| failed_breakdown | close above support before the window, then a low below support in the last 3 bars | `breakdown_not_found` |
| | reversal (signal) session closes back above support — broken and reclaimed within 2 sessions | `reclaim_not_confirmed` |
| | reversal-session rvol ≥ 1.5× | `reversal_rvol_low` |
| | stop (underlying stop for options) below the reversal bar's low | `stop_not_below_reversal_bar` |
| compression_expansion | 10-day range **or** ATR(14) in the lowest quartile of the trailing 60 sessions (mid-rank percentile ≤ 0.25, ties count half) | `no_compression` |
| | expansion range > 1.5× the prior 10-day average range | `expansion_range_small` |
| | expansion rvol ≥ 1.5× | `expansion_rvol_low` |
| | direction follows the expansion (long only: expansion close > prior close) | `expansion_not_up` |
| | stop below the compression range low (prior 10 sessions) | `stop_not_outside_compression` |
| all (catalyst record) | primary / secondary need a source URL and a source type | `catalyst_unsourced` |
| | primary / secondary need a timestamp (`observed_at`) | `catalyst_unsourced` |
| | primary: observed in the last 5 NYSE sessions (through the session date) | `catalyst_stale` |
| | not dated after the session date | `catalyst_date_invalid` |

Shared gates already in `risk_math` (unchanged): stop distance 0.4–2.0 ATR
(`stop_distance_atr`), expected R ≥ 1.5, stock entry ≤ 1.0 ATR past the level
(`extended`), catalyst quality per setup (`catalyst_insufficient`), earnings
in the window forbids stock, invalidation, sector / setup / position caps,
`provisional_source_live`; universe gates in `size_stock` (price ≥ $10, ADV ≥
$25M, spread ≤ max($0.05, 0.15%)) and option liquidity in `size_option`, both
fed the Mac's numbers. Time stop of 7 calendar days: `time_stop_invalid`.

### Qualitative conditions left to the Red Team narrative

Not machine-checkable from bars; the Red Team must address them in the
narrative, and they never change size except through the seven flags:

- The catalyst's **mechanism** and whether it can change near-term supply or
  demand; whether the source is real and supports the claim; primary vs
  secondary classification ("the price is up" is absent).
- momentum_pullback: "the continuation trigger is a price, not a feeling";
  an absent catalyst must be said so in the narrative.
- Whether the named level / support / breakout base is a meaningful level
  (the engine checks the price action against it, not its choice).
- `earnings_in_window` correctness (no earnings calendar on the Mac yet).
- Not halted (no halt feed).
- The flags other than gap_history: `crowded_options`, `sector_lagging`,
  `wide_spread_but_legal`, `contradictory_filing`, `valuation_extreme` (needs
  a cited number), `event_just_outside_window`.

### Not yet recomputed

Option bid / ask / open interest / volume come from the draft (the Mac has no
options cache and the engine does not fetch). `size_option` applies the
liquidity gates to the draft's numbers.

## Known Phase 1 behavior

- **No minimum size.** A 1-share (or 1-contract) approval is legal (Ditka,
  2026-09-25). Cautious caps plus pending heat can produce very small cards.
- Options are sized on `max_buy_fill(debit)`.

## DONE — `handoff/<date>/cards/DONE`

Schema `engine_done.schema.json`. Written on the first pass after the cutoff
once **every draft has a card** (sized, rejected, or late), even with zero
drafts:

```json
{"schema_version": "1.0.0", "marker": "DONE", "session_date": "2026-09-28",
 "as_of": "2026-09-28T08:21:00-05:00", "cutoff": "2026-09-28T08:20:00-05:00",
 "finalized_by": "cutoff", "revision": 1,
 "counts": {"drafts": 3, "sized": 1, "rejected": 1, "late": 1},
 "trade_ids": {"sized": ["DF-2026-0001"], "rejected": ["DF-2026-0002"], "late": ["DF-2026-0003"]},
 "unidentified": [], "withdrawn": []}
```

Never before the cutoff unless `--finalize`. The final 08:24 pass writes it if
nothing earlier did. If a late draft lands after DONE, the late card is
written and DONE is rewritten with `revision` + 1; sized and rejected entries
cannot change after the cutoff. `unidentified` lists draft files carded
without their own trade_id (counted in `rejected`); `withdrawn` lists on-time
drafts that vanished before carding (not counted). The loop exits non-zero if
the window ends without DONE.

## READY — `handoff/<date>/READY`

Schema `engine_ready.schema.json`. The **last** step of the 08:05 pre-open job,
after every other handoff file is committed:

```bash
# ... prep writes handoff/$D/* and commits them ...
/usr/bin/python3 -m dragonfly.engine ready --repo "$DRAGONFLY_PRIVATE_DIR"   # last
```

It refuses (exit 2) while anything under `handoff/<date>/` is uncommitted or
untracked, or if the folder is empty. It lists every file present (path,
bytes, sha256; not `cards/`), writes `as_of`, commits READY on its own, and
pushes. Any unpushed prep commits go up in the same push, ahead of READY.

## CLI

```
python3 -m dragonfly.engine run [--once] [--date YYYY-MM-DD] [--finalize]
    [--start 08:08] [--cutoff 08:20] [--end 08:24] [--poll-seconds 60]
    [--repo PATH] [--book PATH] [--state-dir PATH] [--bars-dir PATH] [--watchlist PATH]
    [--no-pull] [--no-push] [--now ISO]
python3 -m dragonfly.engine ready [--date D] [--repo PATH] [--no-pull] [--no-push]
```

Repo: `--repo`, else `$DRAGONFLY_PRIVATE_DIR`, else `~/projects/dragonfly-private`.
Book: `--book`, else `$DRAGONFLY_STATE_DIR/book.json`, else
`dragonfly/state/live/book.json`. Bars: `--bars-dir`, else
`<state dir>/cache/bars`. Watchlist: `--watchlist`, else
`dragonfly/watchlist.json`. `--now` shifts the clock for dry runs.
`--no-push` writes files only (no commit, no push). Exit codes: 0 ok (also a
non-session day), 1 loop ended without DONE, 2 engine error.

## Book state — `dragonfly/state/live/book.json`

Schema `engine_book.schema.json`, example `examples/engine_book.json`. Required:
`book`, `as_of` (must be at or after the previous session's close),
`equity`, `cash` (buying power, no margin), `positions` (trade_id, ticker,
sector, setup, instrument, heat, notional), `day_pnl_pct`, `week_pnl_pct`,
`drawdown_pct`, `consecutive_full_losses`. A missing breaker input is an
error, never a zero. The engine only reads it.

## Launchd (templates only)

`dragonfly/ops/com.dragonfly.engine.plist.template` (08:08 Mon–Fri, not at
load) and `dragonfly/ops/run_engine.sh.template` (weekday and 08:00–08:24
guard, because launchd runs a missed job on wake). The engine itself idles on
NYSE holidays. Nothing is installed or loaded.

## Dry run (Ditka, before any schedule)

Use a scratch clone and scratch state, never the live checkout:

```bash
git clone <dragonfly-private> /tmp/df-dry && cd ~/projects/ai-finance-tech-dashboard
/usr/bin/python3 dragonfly/test_engine.py
/usr/bin/python3 -m dragonfly.engine run --once --no-push --repo /tmp/df-dry \
  --book docs/dragonfly/examples/engine_book.json --state-dir /tmp/df-dry-state \
  --bars-dir dragonfly/state/live/cache/bars \
  --now "$(date +%F)T08:15:00-05:00"
# then the same with --now ...T08:21:00 to see late cards and DONE;
# inspect /tmp/df-dry/handoff/<date>/cards/
```

The example book is marked 2026-09-24 15:30 CT, so on any later date it is
`book_stale` by design; copy it and set `as_of` after the last close to see
sizing.

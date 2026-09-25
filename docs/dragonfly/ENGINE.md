# Dragonfly 7 — pre-open engine, READY and DONE

Private. Paper book. Code: `dragonfly/engine/`, `dragonfly/jobs/` (prep and
pre-open), `dragonfly/market_calendar.py`, `dragonfly/setup_gates.py`. Tests:
`python3 dragonfly/test_engine.py` and `python3 dragonfly/test_jobs.py`
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
| 15:30 prior session | **Prep job** (`python3 -m dragonfly.jobs prep`): watchlist, bars cache, measurements for the next session; marks a flat book **after the close** | `state/live/cache/bars/`, `state/live/book.json` (flat only), `handoff/<next session>/prep.json`, `measurements.json` |
| 08:05 | **Pre-open job** (`python3 -m dragonfly.jobs preopen`): requires the prep, checks `book_stale`, pre-market quotes. **Last step:** READY (`write_ready`) | `handoff/<date>/quotes.json`, `book.json`, then `READY` by ~08:07 |
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
    prep.json, measurements.json            15:30 prep job (prior session)
    quotes.json, book.json                  08:05 pre-open job
    READY                                   last file of the 08:05 job
    cards/
      DF-2026-0001.json                     one frozen card per trade_id
      unidentified/<draft-stem>.json        drafts with no usable / a duplicate trade_id
      DONE                                  engine finished for the day
  inbox/2026-09-28/
    regime_snapshot.json                    Market Read (regime_snapshot.schema.json)
    DF-2026-0001.draft.json                 Architect (trade_draft.schema.json)
    DF-2026-0001.redteam.json               Red Team (trade_redteam.schema.json)
Mac, gitignored (in the run clone ~/projects/dragonfly-run):
  dragonfly/state/live/book.json            live book (engine_book.schema.json)
  dragonfly/state/live/universe.json        prep's working copy of the NDX membership
  dragonfly/state/live/watchlist.json       prep's watchlist build (snapshot goes into prep.json)
  dragonfly/state/live/cache/quotes/<date>.json  pre-open quote cache (10 min)
  dragonfly/state/live/cache/bars/<T>.json  bars cache (#266), read-only here
  dragonfly/state/live/engine/<date>.json   engine's first-seen times (drafts, red team files)
```

## Drafts (Architect → engine)

Schema: `docs/dragonfly/schemas/trade_draft.schema.json`; example
`docs/dragonfly/examples/trade_draft.json`. A draft is a trade card minus
everything the engine owns. It carries **no** `sizing`, **no** `risk_decision`
and **no** `entry.max_fill` (any of those rejects the draft). It adds:

- `measurements`: the Architect's numbers. The engine **checks them but
  never uses them**. Only `signal_session` is always required (the breakout,
  pullback, reversal or expansion bar). `reference_level` is required for
  catalyst_breakout (the breakout level) and failed_breakdown (the reclaimed
  support). For momentum_pullback (continuation pivot) and
  compression_expansion (compression high) it is optional and informational.
  `base_level` is required for momentum_pullback (the prior breakout base).
  `price` (previous-session close), `atr` (Wilder ATR(14) at the previous
  session), `adv_dollars` (20-day), `spread` (stock) and `sector` are
  optional. Each one stated is compared with the Mac's value; one left out is
  not compared. `provisional` is ignored: provenance comes from the Mac's own
  sources.
- `evidence.relative_volume`: the Architect's figure. A difference from the
  Mac's value is recorded, not blocked, and the card carries the Mac's value.
- `catalyst`: `source_url` **or** `filing_accession` (an SEC accession such as
  `0001193125-26-123456`; an accession given in `source_url` also counts),
  `observed_at`, quality, summary, `earnings_in_window`.
- `option`: required for `call` / `put` / `debit_spread`. It holds contract,
  expiration, bid, ask, open interest, volume (net / min across legs for a
  spread) and `underlying_stop`. For options, `entry.price` is the debit,
  `stop` is the premium stop, and the target is a premium.
- `time_stop`: the Architect's dates. The card's dates are the engine's (see
  below).
- optional `book` (must match the engine's book), `drafted_at`, `notes`.

**Lenient on extra keys.** The schema is the Architect's contract, and its
`additionalProperties: false` still applies to producers. The engine is
lenient about keys the schema does not define, at any level. That includes
engine-owned keys a draft should not carry (`status`, `red_team`,
`human_decision`, ...). They are stripped before validation and recorded in
`engine.inputs.notes` (`draft_keys_ignored`), never copied, never a reject.

**Identity.** The trade_id in the draft body wins. If the file name differs,
that is recorded (`trade_id_filename_differs`) and the card is written under
the body's trade_id. A trade_id whose year differs from the session year is
recorded (`trade_id_year_differs`), not blocked.

**Time stop (plan §8).** The engine computes the card's dates:
- entry = the first NYSE session on or after the later of the draft's entry
  date and the session date
- exit = `risk_math.time_stop_session(entry, NYSE sessions)` over
  `max_calendar_days` (7)

If the draft stated other dates, the card carries the engine's dates and a
`time_stop_corrected` note. Only unparsable dates (`time_stop_invalid`) or
dates outside the calendar tables (`calendar_not_covered`) block.

### Options contract (Ditka, 2026-09-25)

For options, the extension and stop-distance ATR are measured **on the
underlying**, with the Mac's ATR:

- extension = (underlying previous close − `reference_level`) / ATR
- stop distance = (underlying previous close − `option.underlying_stop`) / ATR

For stock:
- extension = (`entry.price` − `reference_level`) / ATR
- stop distance = (`max_buy_fill(entry.price)` − `stop`) / ATR

With no `reference_level` (allowed outside A and C), extension is 0. The
setup gates also use the underlying: `underlying_stop` for "stop below the
reversal bar" and "stop outside the compression range". The option's
bid/ask/OI/volume come from the draft. The Mac has no options cache, so they
are not recomputed (see "Not yet recomputed" below).

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
3. **Pre-sized or unsafe → rejected, never sized.** `draft_carries_sizing`,
   `draft_carries_risk_decision`, `draft_carries_max_fill`, `book_mismatch`,
   `invalidation_not_machine_checkable`, `time_stop_invalid` (unparsable
   dates only), `calendar_not_covered`. Time stop dates are otherwise
   corrected, not rejected (see Drafts).
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

Every card carries an `engine` block with:
- outcome, reasons, draft file and sha256
- first seen, cutoff, carded at, book
- the inputs used: red team file, sha256, first seen / first valid, derived
  warning_count, Mac measurements with sources, mismatches, gate details,
  structural inputs, sizing inputs
- `notes`: non-blocking observations such as `draft_keys_ignored`,
  `trade_id_filename_differs`, `trade_id_year_differs`, `time_stop_corrected`,
  `signal_session_old`, `evidence_relative_volume_differs`, and
  `extended_not_applied`

All timestamps are America/Chicago with offset.

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

Recomputed from bars with `dragonfly/bars.py`:
- `price`: previous-session close
- `atr`: Wilder ATR(14) at the previous session
- `adv_dollars`: 20-day average dollar volume
- relative volume on the signal session: volume / prior 20-day average

A draft value outside tolerance is `measurement_mismatch`. Only fields the
draft states in `measurements` are compared:

| Field | Tolerance |
| --- | --- |
| price | 0.5% of the Mac value |
| atr | 5% |
| adv_dollars | 5% |
| spread (stock only; a draft `null` is not compared) | $0.01 |
| sector | exact (case-insensitive) |

`evidence.relative_volume` sits outside the measurements block. A difference
(5%, at least 0.05×) is recorded as `evidence_relative_volume_differs`; the
card's evidence carries the Mac's value.

`measurement_unavailable` fails closed when the Mac cannot compute a value it
needs:
- no cache and no prep bars
- the cache lacks the previous session's bar ("cache stale")
- the signal session is not in the bars
- too little history for a calculation
- no sector
- no spread (stock)
- momentum_pullback without `base_level`
- catalyst_breakout / failed_breakdown without `reference_level`

The card lists each item in `engine.inputs.measurements.details.unavailable`.

Signal age: there is no plan limit. A `signal_session` older than the last 5
sessions is only recorded (`signal_session_old`); the gates judge that bar.

## Setup gates — structural blocks (`dragonfly/setup_gates.py`)

Computed on the Mac's bars through `signal_session`, with the Mac's ATR, and
recorded in `engine.inputs.measurements.details.gates`. Each failure is a
structural block on the card. Policy (Jared, 2026-09-25): **no blocks beyond
the plan text in Phase 1.** Where the plan names a gate but leaves a
parameter open, the engine uses the most permissive reasonable reading
(marked *assumption*).

| Setup | Gate (plan §6) | Block code |
| --- | --- | --- |
| catalyst_breakout | breakout-session rvol ≥ 1.8× the 20-day average | `breakout_rvol_low` |
| | price confirmation: the breakout session traded above the named level (high > level; *assumption*, a close above is not required) | `breakout_not_confirmed` |
| | entry within 1.0 ATR of the level (stock: trigger; option: underlying close) | `breakout_entry_far` |
| | (governor) stock entry ≤ 1.0 ATR past the level, plan §5 and §6A: **catalyst_breakout only** | `extended` |
| momentum_pullback | move underway: 20-session return > 8%, **or** close > SMA20, SMA20 rising (above the prior session's SMA20, *assumption*), SMA20 > SMA50; true at the pullback bar **or** at the swing high (*assumption*) | `pullback_no_momentum` |
| | a recent swing high exists: any local high (high ≥ both neighbours) in the 20 sessions before the pullback bar (*assumption*); the gate passes if **any** candidate passes | `pullback_not_formed` |
| | pullback 0.4–1.5 ATR off the swing high, by close **or** by the pullback low (*assumption*) | `pullback_depth_out_of_range` |
| | no close back through the prior breakout base (`base_level`) since the swing high | `pullback_broke_base` |
| | pullback volume (mean since the swing high) below impulse volume (mean of the 5 sessions ending at the swing high, *assumption*) | `pullback_volume_not_lower` |
| failed_breakdown | broke the named support: a low below it on the reversal session or the 2 before it, the session before that low closing at or above support (*assumption*: an intraday break counts) | `breakdown_not_found` |
| | reclaimed within two sessions: reversal close at or above support | `reclaim_not_confirmed` |
| | reversal-session volume ≥ 1.5× the 20-day average | `reversal_rvol_low` |
| | stop (underlying stop for options) below the reversal bar's low | `stop_not_below_reversal_bar` |
| compression_expansion | 10-day range **or** ATR(14) in the lowest quartile of the trailing 60 sessions: at most 25% of the 60 values strictly below today's (*assumption*: ties count for compression), measured on the session before the expansion | `no_compression` |
| | expansion range > 1.5× the prior 10-day average range (expansion = true range, counting a gap, *assumption*; prior = mean high−low) | `expansion_range_small` |
| | expansion volume ≥ 1.5× (the 20-day average, *assumption*) | `expansion_rvol_low` |
| | direction follows the expansion: stock/call need an up session (close above the prior close or the open), put a down one; debit_spread not checked (*assumption*) | `expansion_direction_mismatch` |
| | stop outside the compression range (the 10 sessions before the expansion): below its low (above its high for a put) | `stop_not_outside_compression` |
| catalyst record (primary / secondary) | a source URL **or** filing accession | `catalyst_unsourced` |
| | a timestamp (`observed_at`) | `catalyst_undated` |
| | primary: in the last five sessions, i.e. at or after the close of the 6th NYSE session before the session date (*assumption*: after-hours news belongs to the next session) | `catalyst_stale` |
| | not future-dated: more than 5 minutes after the engine clock (*assumption*: clock skew) | `catalyst_date_invalid` |

**`extended` on non-breakout setups (Ditka, 2026-09-25).** `risk_math.structural_blocks`
applies `extended` to every setup, and risk_math is not edited here. So the
engine **filters the code out** of the governor's result for
momentum_pullback, failed_breakdown and compression_expansion. The computed
extension is still recorded (`extended_not_applied` note, plus
`engine.inputs.structural.extension_atr`). risk_math should scope `extended`
to catalyst_breakout once #269 lands, and then the filter can go.

Other shared gates in `risk_math` (unchanged), fed the Mac's numbers:
- stop distance 0.4–2.0 ATR (`stop_distance_atr`)
- expected R ≥ 1.5
- catalyst quality per setup (`catalyst_insufficient`)
- earnings in the window forbids stock
- invalidation
- sector / setup / position caps
- `provisional_source_live`
- universe gates in `size_stock`: price ≥ $10, ADV ≥ $25M, spread ≤ max($0.05, 0.15%)
- option liquidity in `size_option`

The 7-calendar-day time stop is computed by the engine (plan §8).

## Block audit (Phase 1 policy: no blocks beyond the plan)

Every code the engine or setup_gates can emit, with its basis.

| Code | Basis |
| --- | --- |
| `late_draft`, `late_redteam` (+ the red team file's problems as detail) | Ditka ruling 1: red team before sizing, 08:20 cutoff |
| `draft_carries_sizing`, `draft_carries_risk_decision`, `draft_carries_max_fill` | Ditka ruling: pre-sized draft reject; plan §7 "Sizing block copied from the governor, not typed by a model" |
| `draft_not_json_object`, `trade_id_missing`, `draft_schema_invalid: …` | Schema fail-closed (cannot size safely); plan §7 required card content, §9 Architect "a null required field" |
| `duplicate_trade_id` | Safety: one frozen card per trade_id (ruling 1 "one engine pass per trade"; plan §7 frozen cards) |
| `card_schema_invalid` | Safety: never write an invalid card |
| `book_mismatch` | Safety: a draft for the other book (plan §3.10 paper before live) |
| `invalidation_not_machine_checkable` | Plan §7: "`stop_hit` and `time_stop` are mandatory" (also a governor code) |
| `time_stop_invalid` | Schema/safety: unparsable dates only |
| `calendar_not_covered` | Ditka ruling 3 (static calendar; fail closed outside it) |
| `book_stale` | Ditka ruling 4 |
| `engine_window_closed` | Ditka timeline (engine 08:08–08:24, no post-open pass); plan §5 stale-marks rule |
| `regime_missing` (mode `stand_down`) | Plan §5 "the code, not the model, picks the mode"; §10 step 1 |
| `measurement_mismatch`, `measurement_unavailable` | Ditka ruling 5 |
| `catalyst_unsourced`, `catalyst_undated`, `catalyst_stale`, `catalyst_date_invalid` | Plan §6 "Catalyst quality"; Ditka (a) |
| `breakout_rvol_low`, `breakout_not_confirmed`, `breakout_entry_far` | Plan §6A |
| `pullback_no_momentum`, `pullback_not_formed`, `pullback_depth_out_of_range`, `pullback_broke_base`, `pullback_volume_not_lower` | Plan §6B |
| `breakdown_not_found`, `reclaim_not_confirmed`, `reversal_rvol_low`, `stop_not_below_reversal_bar` | Plan §6C |
| `no_compression`, `expansion_range_small`, `expansion_rvol_low`, `expansion_direction_mismatch`, `stop_not_outside_compression` | Plan §6D |
| `extended` (catalyst_breakout only) | Plan §5 "What the governor will not do", §6A; Ditka (c) |
| governor: `unknown_book`, `provisional_source_live` | Plan §5 |
| governor: `missing_field`, `unknown_setup` | Plan §7, §3.8 |
| governor: `instrument_not_allowed`, `short_stock_forbidden`, `direction_not_long`, `earnings_stock_forbidden` | Plan §6 Instruments |
| governor: `catalyst_insufficient` | Plan §6A, §6C |
| governor: `sector_occupied`, `setup_cap`, `position_cap`, `heat_exhausted` and the other caps | Plan §5 Caps / Other ceilings |
| governor: `stand_down`, `regime_stand_down`, `day_halt`, `week_halt`, `drawdown_halt`, `drawdown_cautious`, `streak_cautious` | Plan §5 Circuit breakers / Regime to mode |
| governor: `stop_distance_atr`, `reward_risk_below_minimum` | Plan §5, §6 shared gates |
| governor: `price_below_minimum`, `adv_below_minimum`, `spread_unavailable`, `spread_too_wide`, `option_open_interest`, `option_volume`, `option_spread_too_wide` | Plan §6 Universe |
| governor: `atr_missing`, `stop_not_below_entry`, `option_stop_invalid` | Safety: cannot size |

Removed or downgraded on 2026-09-25 (now recorded notes, or loosened):
- `signal_session_stale` (5-session limit): removed; recorded as a
  `signal_session_old` note.
- `time_stop_invalid` for a wrong exit date, a holiday entry, or an entry
  before the session date: the engine computes the dates (plan §8) and notes
  `time_stop_corrected`.
- `trade_id_filename_mismatch` → `trade_id_filename_differs` note (the body
  wins).
- `trade_id_year_mismatch` → `trade_id_year_differs` note.
- `measurement_mismatch` on `evidence.relative_volume`: downgraded to a note
  (it is not in the measurements block).
- `measurement_mismatch` when the draft omits a measurement: the draft's
  price/atr/adv/sector/spread are optional; only stated values are compared.
- Draft schema strictness: unknown or engine-owned keys are stripped and noted
  instead of rejected. `reference_level` is required only for
  catalyst_breakout and failed_breakdown.
- `catalyst_unsourced` for `source_type: "none"`: removed (not plan text). A
  filing accession now counts as a source. An undated record is now its own
  code (`catalyst_undated`).
- `catalyst_stale`: the window now opens at the 6th previous session's close.
- `catalyst_date_invalid`: now "after the engine clock + 5 min" (was "after
  the session date").
- `extended` on momentum_pullback, failed_breakdown and compression_expansion:
  filtered out.
- Gate definitions loosened:
  - breakout confirmation by the high, not the close
  - SMA20 "rising" over 1 session, not 5
  - momentum at the pullback bar or the swing high
  - swing high: any local high in 20 sessions (any candidate may pass), not
    the 10-session maximum
  - pullback depth by close or low
  - failed_breakdown: the "above support before" check is anchored to the
    first break bar, and a close at support counts as a reclaim
  - quartile ties favour compression (were half)
  - expansion range = true range
  - `expansion_not_up` → `expansion_direction_mismatch` (puts follow a down
    expansion; debit spreads unchecked)

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
- Modeled spreads (#269): with the modeled $0.025 half-spread, a paper entry
  at the trigger on any name under $16.67 always exceeds the 0.15% max-fill
  limit, so it can never fill. No current watchlist name is that cheap (the
  lowest is about $21). Revisit if one enters the list. (The fill code lives
  in risk_math / #269; nothing changed here.)

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
    [--dry-run-roots | --handoff-root NAME --inbox-root NAME]
python3 -m dragonfly.engine ready [--date D] [--repo PATH] [--no-pull] [--no-push] [--now ISO]
    [--dry-run-roots | --handoff-root NAME --inbox-root NAME]
```

Repo: `--repo`, else `$DRAGONFLY_PRIVATE_DIR`, else `~/projects/dragonfly-private`.
Book: `--book`, else `$DRAGONFLY_STATE_DIR/book.json`, else
`dragonfly/state/live/book.json`. Bars: `--bars-dir`, else
`<state dir>/cache/bars`. Watchlist: `--watchlist`, else
`dragonfly/watchlist.json`. `--now` sets a simulated clock (see Dry run).
Roots: `--dry-run-roots` (`handoff-dryrun/` + `inbox-dryrun/`), else
`--handoff-root` / `--inbox-root`, else `$DRAGONFLY_HANDOFF_ROOT` /
`$DRAGONFLY_INBOX_ROOT`, else `handoff` / `inbox`. Roots are single folder
names and must be paired (both default or both custom), so a dry run can
never write into `handoff/` or read `inbox/`. With custom roots the engine
keeps separate local state (`state/live/engine/<date>.<handoff-root>.json`),
so a dry run never leaks first-seen times into the real run for that date. A
`run` loop for a `--date` that is not today refuses (exit 2) unless `--now`
is given.
`--no-push` writes files only (no commit, no push). Exit codes: 0 ok (also a
non-session day), 1 loop ended without DONE, 2 engine error.

## Book state — `dragonfly/state/live/book.json`

Schema `engine_book.schema.json`, example `examples/engine_book.json`. Required:
`book`, `as_of` (must be at or after the previous session's close),
`equity`, `cash` (buying power, no margin), `positions` (trade_id, ticker,
sector, setup, instrument, heat, notional), `day_pnl_pct`, `week_pnl_pct`,
`drawdown_pct`, `consecutive_full_losses`. A missing breaker input is an
error, never a zero. The engine only reads it. The prep job re-stamps a flat book's
`as_of` after the close (see Prep job); nothing else writes it in Phase 1.
Path: the run clone's `dragonfly/state/live/book.json`, or `--book` /
`$DRAGONFLY_BOOK` (jobs) / `--book` / `$DRAGONFLY_STATE_DIR` (engine).

## Launchd (templates only)

| Template | Schedule | Wrapper wake guard |
| --- | --- | --- |
| `com.dragonfly.prep.plist.template` + `run_prep.sh.template` | 15:30 Mon–Fri | 15:25–18:00 CT |
| `com.dragonfly.preopen.plist.template` + `run_preopen.sh.template` | 08:05 Mon–Fri | 08:00–08:15 CT |
| `com.dragonfly.engine.plist.template` + `run_engine.sh.template` | 08:08 Mon–Fri | 08:00–08:24 CT |

None runs at load. The guards exist because launchd runs a missed calendar
job when the Mac wakes. The prep and pre-open wrappers refuse to run from the
pipeline checkout, `cd` into the run clone and `git pull --ff-only origin
main` first (a non-ff state aborts). NYSE holidays are decided by the jobs
themselves. **Nothing is installed or loaded**; Ditka gives an explicit go
before anything loads.

## Where the jobs run on the Mac — the run clone

Dragonfly never runs from the pipeline checkout
`~/projects/ai-finance-tech-dashboard`: the site daemon autostashes and pulls
that tree. The jobs and the engine run from a **separate clone**:

| Path | What |
| --- | --- |
| `~/projects/dragonfly-run` | clone of ai-finance-tech-dashboard (`main`); wrappers `git pull --ff-only` at job start. `__REPO__` in the templates |
| `~/projects/dragonfly-run/dragonfly/state/live/book.json` | live book (gitignored). Override: `--book` or `$DRAGONFLY_BOOK`; state dir: `$DRAGONFLY_STATE_DIR` |
| `~/projects/dragonfly-run/dragonfly/state/live/cache/bars/` | bars cache the prep refreshes and the engine reads |
| `~/projects/dragonfly-private` | clone of the private repo (`$DRAGONFLY_PRIVATE_DIR`); pushes with the Mac's own git credentials (osxkeychain) |

The run clone stays clean (every job output is gitignored state or goes to
dragonfly-private), so the ff-only pull never conflicts. The load guards
still read the pipeline's lock files in the pipeline checkout
(`$DRAGONFLY_PIPELINE_LOCK`, set by the templates); they never write there.

## Prep job — `python3 -m dragonfly.jobs prep` (15:30 CT)

1. Target session: `--date`, else `market_calendar.next_session(today)`
   (Friday preps Monday; the day before a holiday preps the next session). A
   non-session `--date` is refused. The previous session must have closed.
2. Load guards (`guards.preflight`, real clock): no daemon window, bounded
   wait on the pipeline lock. 15:30 is outside every window. One prep at a
   time (job lock `state/live/jobs/prep.lock`).
3. Pull dragonfly-private. Refuses if `<root>/<date>/READY` already exists.
4. Watchlist through the existing gates (`build_watchlist.build`, modeled
   mid). Universe membership is re-fetched only when 7+ days old. Works on
   `state/live/universe.json` / `state/live/watchlist.json`.
5. Bars cache for each admitted name, refetched if the cache predates the
   previous close + 5 min or lacks the previous session's bar.
6. `measurements.json` (the engine's contract, `measure.load_prep`):
   `{"schema": "dragonfly.prep_measurements/1", "session_date", "previous_session",
   "as_of", "names": [row, ...]}`. Each row: `ticker`, `sector`, `spread`,
   `spread_source`, `provisional` (true), `bars` (last 130 bars through the
   previous session), plus `price`, `atr`, `adv_dollars`, `relative_volume`,
   `bar_date` from `setup_gates.core_measurements` (informational; the engine
   recomputes), `mid`, `mid_source`, `bid`, `ask`, `quote_time`, `origin`,
   `market_cap`, `sector_rank`. A name that cannot be measured carries
   `unavailable`; none measurable fails the job.
7. `prep.json`: `session_date`, `previous_session`, `previous_close`,
   `as_of`, `tickers` (admitted), `measurement_problems`, and the watchlist
   snapshot (funnel, gates, universe, excluded, per-name summary).
8. Commit both files and push.
9. Book mark (real runs only, never with dry-run roots): a **flat** book
   (no positions) is re-stamped `as_of` = now, numbers unchanged
   (equity = cash; nothing to price). A book with open positions is **not**
   marked (Phase 1 has no fill ledger), so the next pre-open fails
   `book_stale` until it is marked by hand.

## Pre-open job — `python3 -m dragonfly.jobs preopen` (08:05 CT)

1. Session: `--date`, else today. Non-session day: log, exit 0. A `--date`
   that is not today needs `--now`.
2. Load guards (real clock) and job lock; pull dragonfly-private.
3. Requires `<root>/<date>/prep.json` and `measurements.json`, committed and
   for this `session_date`. Missing: **PREP MISSING**, exit 2, no READY.
4. Loads and validates the book (`engine_book.schema.json`) and applies the
   `book_stale` rule. Stale, missing or invalid: exit 2, no READY.
5. Pre-market quotes for the prep's admitted tickers only, cache first
   (`state/live/cache/quotes/<date>[.<root>].json`, reused for 10 min), one
   guarded yfinance info call per name. The last trade is the freshest of the
   pre-market, regular and post-market prints; the quote is resolved with
   `risk_math.resolve_quote` (Yahoo bid/ask if it passes the gate, else the
   modeled $0.05 mid; paper only). Zero usable quotes: exit 2, no READY.
6. Writes `quotes.json` (`dragonfly.preopen_quotes/1`: per name `bid`, `ask`,
   `mid`, `spread`, `spread_source`, `mid_source`, `last_trade`,
   `last_source`, `quote_time`, `previous_close`, `gap_pct`, `usable`) and
   `book.json` (`dragonfly.book_snapshot/1`: `freshness`, `summary`, and the
   full book), commits and pushes them, then calls `write_ready()` as the
   **last** step.

Market Read: this document names no Mac-side input for Market Read beyond
the handoff files. `quotes.json` carries a best-effort `market_context`
block (SPY, QQQ, ^VIX); it is not a contract input and never blocks READY.

```
python3 -m dragonfly.jobs {prep,preopen} [--date D] [--now ISO] [--dry-run-roots]
    [--repo PATH] [--book PATH] [--state-dir PATH] [--no-pull] [--no-push] [-v]
    [--no-mark-book]   (prep only)
```

`--now` moves the job's session clock (dates, `as_of`); the load guards
always use the real wall clock. Exit codes: 0 ok (also a non-session day),
2 failure. Tests: `python3 dragonfly/test_jobs.py` (offline).

## Dry run (Ditka, before any schedule)

**Real session date, separate folders.** Tonight's dry run uses session date
2026-09-28 under `handoff-dryrun/2026-09-28/` and `inbox-dryrun/2026-09-28/`
in dragonfly-private, so the real `handoff/2026-09-28/` stays clean for
Monday. Box agents write their regime snapshot, drafts and red team files to
`inbox-dryrun/2026-09-28/`; the Mac prep (if any) goes to
`handoff-dryrun/2026-09-28/`.

`--now` is a simulated clock. It reads the given time at launch and then
advances in real time. So a Friday-evening loop started with
`--now 2026-09-28T08:07:00-05:00` runs the real schedule: first pass at
simulated 08:08, 60 s polls, the 08:20 cutoff, DONE after 08:20, and the loop
ends at 08:24 (about 17 minutes of wall time). The book rule uses the
simulated session: a book marked after Friday's 15:00 CT close is fresh for
2026-09-28.

```bash
cd ~/projects/dragonfly-run          # the run clone, never the pipeline checkout
export DRAGONFLY_PRIVATE_DIR=~/projects/dragonfly-private
export DRAGONFLY_PIPELINE_LOCK="$HOME/projects/ai-finance-tech-dashboard/pipeline/state/auto_pipeline.lock:$HOME/projects/ai-finance-tech-dashboard/pipeline/auto_pipeline.lock"
# prep (Friday's close) and pre-open (READY last) into handoff-dryrun/2026-09-28/
/usr/bin/python3 -m dragonfly.jobs prep --date 2026-09-28 --dry-run-roots
/usr/bin/python3 -m dragonfly.jobs preopen --date 2026-09-28 --dry-run-roots \
  --now 2026-09-28T08:05:00-05:00
# (READY alone, if the handoff files were committed some other way:)
/usr/bin/python3 -m dragonfly.engine ready --dry-run-roots --date 2026-09-28 \
  --now 2026-09-28T08:06:30-05:00
# the engine loop on a simulated Monday morning, separate local state
/usr/bin/python3 -m dragonfly.engine run --dry-run-roots --date 2026-09-28 \
  --now 2026-09-28T08:07:00-05:00 --state-dir /tmp/df-dry-state
# same, pinned: DRAGONFLY_HANDOFF_ROOT=handoff-dryrun DRAGONFLY_INBOX_ROOT=inbox-dryrun
```

Single passes (no waiting) against a scratch clone, writing locally only:

```bash
git clone <dragonfly-private> /tmp/df-dry && cd ~/projects/dragonfly-run
/usr/bin/python3 dragonfly/test_engine.py
/usr/bin/python3 -m dragonfly.engine run --once --no-push --dry-run-roots --repo /tmp/df-dry \
  --date 2026-09-28 --state-dir /tmp/df-dry-state --bars-dir dragonfly/state/live/cache/bars \
  --now 2026-09-28T08:15:00-05:00
# then --now 2026-09-28T08:21:00-05:00 to see late cards and DONE;
# inspect /tmp/df-dry/handoff-dryrun/2026-09-28/cards/
```

The example book (`docs/dragonfly/examples/engine_book.json`) is marked
2026-09-24 15:30 CT, so on any later session it is `book_stale` by design.
Copy it and set `as_of` after the last close to see sizing.

# Dragonfly 7 — pre-open engine, READY and DONE

Private. Paper book. Code: `dragonfly/engine/`. Tests: `python3 dragonfly/test_engine.py`
(offline). Python 3.9 compatible (the Mac runs `/usr/bin/python3` 3.9.6); needs
`jsonschema` (`dragonfly/requirements.txt`). Without it the engine refuses to
write anything.

The Mac is the engine of record. The engine reads the live book from
`dragonfly/state/live/book.json` (gitignored) and exchanges files with box
agents through a local checkout of the private repo `dragonfly-private`:

- `handoff/YYYY-MM-DD/` — written by the Mac (prep bundle, READY, and the engine's `cards/`).
- `inbox/YYYY-MM-DD/` — written by box agents (regime snapshot, drafts, red team, brief).

## Timeline (America/Chicago, one session per day)

| CT | Step | Writes |
| --- | --- | --- |
| 15:30 prior day | Mac prep (built separately): marks the book, prep data | `state/live/book.json`, `handoff/<date>/…` |
| 08:05 | Pre-open job (built separately). **Last step:** `python3 -m dragonfly.engine ready` | `handoff/<date>/READY` by ~08:07 |
| 08:07–08:12 | Market Read (box) | `inbox/<date>/regime_snapshot.json` |
| 08:12–08:18 | Trade Architect (box) | `inbox/<date>/<trade_id>.draft.json` |
| 08:08–08:24 | **Engine** (Mac), polls every 60 s; **draft cutoff 08:20** | `handoff/<date>/cards/<trade_id>.json`, `cards/DONE` |
| 08:18–08:25 | Red Team (box) | inbox (separate files; frozen cards are not edited) |
| 08:25–08:29 | Ditka's brief | inbox |

08:08–08:24 sits outside every pipeline daemon window, and the engine makes no
market-data calls, so it never calls the load guards (`dragonfly/guards.py`).
A held pipeline lock does not block it (tested).

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
Mac, gitignored:
  dragonfly/state/live/book.json            live book (engine_book.schema.json)
  dragonfly/state/live/engine/<date>.json   engine's first-seen times per draft
```

## Drafts (Architect → engine)

Schema: `docs/dragonfly/schemas/trade_draft.schema.json`; example
`docs/dragonfly/examples/trade_draft.json`. A draft is a trade card minus
everything the engine owns. It carries **no** `sizing`, **no** `risk_decision`,
**no** `entry.max_fill`, and no status, red team, human decision, watcher, or
timestamps the engine sets. It adds:

- `measurements` — governor inputs: `price`, `atr`, `adv_dollars`, `spread`
  (null = not observed, fails closed), `sector`, `reference_level` (the setup's
  named level; extension is measured from it in ATR), optional `spread_source`,
  `provisional` (missing counts as provisional), `source`, `as_of`.
- `option` — required for `call` / `put` / `debit_spread`: contract, expiration,
  bid, ask, open interest, volume (net / min across legs for a spread) and
  `underlying_stop` (for the stop-distance ATR block). For options, `entry.price`
  is the debit, `stop` the premium stop, and the target a premium.
- optional `book` (must match the engine's book), `drafted_at`, `notes`.

Name drafts `<trade_id>.draft.json`. The engine never fetches prices: it reads
`measurements` from the draft, **except** that when the Mac prep writes
`handoff/<date>/measurements.json` (`{"names": {"XYZ": {...}}}` or a list with
`ticker`) and it carries the ticker, the prep values replace the draft's copy
(`price`, `atr`, `adv_dollars`/`adv20_dollars`, `spread`, `spread_source`,
`provisional`, `sector`). Each card records which source it used
(`engine.inputs.measurements.measurements_source`).

## What the engine does with a draft

Each pass: `git ls-remote` (cheap); pull with rebase only if the remote ref
moved; list `inbox/<date>/*.draft.json`; record the first-seen time of any new
draft; card every uncarded draft; commit and push `handoff/<date>/cards/`
(retrying a non-fast-forward with a rebase, up to 5 times); then DONE.

1. **First seen after the cutoff → `late`.** Written as a card with
   `engine.outcome: "late"`, `status: "blocked"`, zero sizing, and
   `risk_decision: null`. Never sized. There is no post-open pass.
2. **Pre-sized → rejected.** A draft carrying `sizing`, `risk_decision`, or
   `entry.max_fill` is rejected (`draft_carries_sizing`, …). The model's numbers
   are never copied: sizing is zero units with the governor's caps.
3. **Invalid → rejected.** Not JSON, fails the draft schema, or no usable
   `trade_id`: a reject record (`engine_reject_record.schema.json`,
   `record: "engine_reject"`, `status: "blocked"`) with the schema errors as
   reasons. Other pre-governor rejects: `book_mismatch`,
   `trade_id_filename_mismatch`, `trade_id_year_mismatch`, `time_stop_invalid`
   (exit must be a weekday, after entry, within 7 days; entry not before the
   session), `duplicate_trade_id`.
4. **Otherwise the governor decides.** `risk_math.structural_blocks` (book from
   `book.json`, `provisional_data` from measurements, so a live book blocks
   provisional data as `provisional_source_live`), then `size_stock` or
   `size_option`, sized off `max_buy_fill(entry.price)`. Mode is
   `regime_to_mode()` on today's regime snapshot tightened by
   `effective_risk_mode()` on the book's breaker inputs. Red-team warnings are
   not known yet, so `warning_count` is 0.
   - Approved: `status: "pending_human"`, `risk_decision.decision: "APPROVED"`,
     `red_team.decision: "pending"`.
   - Structural block: `status: "blocked"`, reasons copied to
     `risk_decision.reasons` and `red_team.hard_blocks`.
   - Sizing reject: `status: "risk_rejected"`.
5. **Pending exposure.** Today's approved cards count as positions when the
   next draft is sized (heat, notional, cash, sector, setup), in first-seen
   order. Two approvals can never add up past a cap.
6. **No regime snapshot yet** (`inbox/<date>/regime_snapshot.json`, else
   `handoff/<date>/regime_snapshot.json`, validated, `session_date` = today):
   governor-bound drafts wait. After the cutoff they are carded anyway with
   mode `stand_down` and reason `regime_missing` (fail closed).
7. **After the window** (a pass later than 08:24), nothing is sized; any
   on-time draft still uncarded is rejected `engine_window_closed`.

Every card carries an `engine` block (optional in `trade_card.schema.json`, so
older cards still validate): outcome, reasons, draft file and sha256, first
seen, cutoff, carded at, book, and the inputs used. All timestamps are
America/Chicago with offset.

**Frozen.** Once `cards/<trade_id>.json` exists it is never rewritten, even if
the draft changes (logged once per new draft hash) or the local engine state
is lost. A rejected card is never re-sized. A fix needs a new `trade_id`.

**Fail closed.** Every card is validated before it is written. A card that
fails `trade_card.schema.json` is replaced by a reject record
(`card_schema_invalid`); if that also fails, the engine stops with an error.
A missing or invalid `book.json` is a loud error and nothing is written.

**Cutoff.** A draft is on time if the pass that first sees it is scheduled at
or before 08:20:00. The loop always runs a pass at exactly 08:20:00, so a
draft pushed before 08:20 is on time; one first seen at 08:21 is late.

## DONE — `handoff/<date>/cards/DONE`

Schema `engine_done.schema.json`. Written on the first pass after the cutoff
once every on-time draft has a card, even with zero drafts:

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
    [--repo PATH] [--book PATH] [--state-dir PATH] [--no-pull] [--no-push] [--now ISO]
python3 -m dragonfly.engine ready [--date D] [--repo PATH] [--no-pull] [--no-push]
```

Repo: `--repo`, else `$DRAGONFLY_PRIVATE_DIR`, else `~/projects/dragonfly-private`.
Book: `--book`, else `$DRAGONFLY_STATE_DIR/book.json`, else
`dragonfly/state/live/book.json`. `--now` shifts the clock for dry runs.
`--no-push` writes files only (no commit, no push). Exit codes: 0 ok, 1 loop
ended without DONE, 2 engine error.

## Book state — `dragonfly/state/live/book.json`

Schema `engine_book.schema.json`, example `examples/engine_book.json`. Required:
`book`, `as_of`, `equity`, `cash` (buying power, no margin), `positions`
(trade_id, ticker, sector, setup, instrument, heat, notional), `day_pnl_pct`,
`week_pnl_pct`, `drawdown_pct`, `consecutive_full_losses`. A missing breaker
input is an error, never a zero. The engine only reads it.

## Launchd (templates only)

`dragonfly/ops/com.dragonfly.engine.plist.template` (08:08 Mon–Fri, not at
load) and `dragonfly/ops/run_engine.sh.template` (weekday and 08:00–08:24
guard, because launchd runs a missed job on wake). Nothing is installed or
loaded.

## Dry run (Ditka, before any schedule)

Use a scratch clone, never the live checkout:

```bash
git clone <dragonfly-private> /tmp/df-dry && cd ~/projects/ai-finance-tech-dashboard
/usr/bin/python3 dragonfly/test_engine.py
/usr/bin/python3 -m dragonfly.engine run --once --no-push --repo /tmp/df-dry \
  --book docs/dragonfly/examples/engine_book.json --state-dir /tmp/df-dry-state \
  --now "$(date +%F)T08:15:00-05:00"
# then the same with --now ...T08:21:00 to see DONE; inspect /tmp/df-dry/handoff/<date>/cards/
```

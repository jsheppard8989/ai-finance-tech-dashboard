# Dragonfly 7 Operating Plan

Version 1.0 — 25 September 2026

Private book. Implementation contract for Ditka89, Grokbot Chief of Staff.

Jared holds human approval, any written override, and the go-live decision. Tony B still gates any merge to `main` and any Pages-facing `site/` ship. This plan does not replace the public research site.

Normative risk math: `dragonfly/risk_math.py`. Vectors: `dragonfly/test_risk_math.py`. If this prose and that module disagree, the module and the tests win, and this prose gets patched in the same change.

## 1. How to use this document

Ditka89 implements Phase 1 from this plan and from `docs/dragonfly/COS_STANDING_ORDER.md`. The standing order is the operating prompt. This document is the constitution behind it.

The unit of work is a Trade Card, not a company. The successful output of a session includes `NO_TRADE`.

## 2. Mandate

Find 7-day price dislocations where a named setup, a catalyst when the setup requires one, positioning, and the market regime line up. Express the idea with defined or heat-adjusted risk. Exit by the stop, the target, or the clock. Measure which setups actually produce positive net expectancy.

The book is not trying to find great companies, beat the market, or predict prices. It rides a short wave and gets off.

Starting equity for the design: **$100,000**. Caps below are percentages of current equity, so they scale after the book is live. Equity means cash plus the marked value of open long stock and long options.

## 3. Locked decisions

These are the dials applied to the outline. Ditka89 implements this list. A change is a written amendment from Jared, then a version bump of this plan.

1. **The weekly dollar figure is an aspiration, never a quota.** A flat week is a successful week. No agent is told how many dollars the book is "behind."
2. **Two different risk numbers.** Planned loss is the stop distance in dollars, and it is the denominator of R. Portfolio heat is the loss the book must be able to survive. For overnight stock, heat = 1.5 × planned loss, because a stop is not a guaranteed fill. For long options and debit spreads, heat = the full debit, even when the planned stop is tighter.
3. **One name cannot take the whole book.** In a normal regime the cap on a single name's heat is 1% of equity, and the cap on the whole book is 2%. Cautious mode halves both. That is tighter than "risk 1% and call the stop the heat."
4. **Size the buy stop off the worst acceptable fill,** which is 0.15% through the trigger. A fill worse than that invalidates the card. There is no chase.
5. **The risk governor is code.** It returns `APPROVED` or `REJECTED` with reason codes. No model, including the Chief of Staff and the red team, can clear a reject or raise a size.
6. **Red team does not have a free veto.** It fills a closed warning checklist and writes the case against the trade. Two or more warnings force cautious name caps. Hard blocks come from the engine.
7. **Positioning is part of Price and Flow,** not a tenth permanent model. Split it later only if the journal shows flow work is being skipped.
8. **Four setups, one tag each, one full-size target in Phase 1.** No invented strategies, no scale-ins, no second target until Phase 2.
9. **The public site stays the research site.** The cockpit is local. Live positions, fills, and account identifiers stay out of git (`dragonfly/state/live/`).
10. **Paper before live.** Phase 1 places no orders. Jared can waive the paper gate in writing. He cannot waive the governor.
11. **The coach proposes rule changes. It does not install them.**
12. **Human rights run one direction.** Jared may reject a card, cut the size, or exit early. He may not loosen a reject, extend the clock, average down, or override a hard block.

## 4. Economics

The aspiration is an average of about 1% of equity per week over a large sample. One percent a week is 52% simple and about **67.8%** compounded. That number is a description of the aspiration. It is not a weekly invoice.

The design hypothesis, carried over from the outline and then haircut for friction:

| Piece | Value |
| --- | --- |
| Win rate | 45% |
| Average winner | +2R |
| Average loser | −1R |
| Gross expectancy | +0.35R |
| Planning friction | 0.08R per trade |
| Net hypothesis | +0.27R |

Friction here is a planning haircut for spread, slippage, and commissions. Live expectancy uses measured net R, not this constant. `design_expectancy_r()` returns these figures so nobody has to re-derive them in a prompt.

Under the heat rules, a full normal-regime stock trade risks about **0.66%** of equity in planned loss (the canonical card below is $663.48 on $100,000). Heat on that card is $995.22, just under the 1% name cap.

| Week, if the hypothesis is true | Approximate result on $100,000 |
| --- | --- |
| 2 sequential full stock trades at +0.27R | about +0.36%, about $358. Compounds near 20% a year |
| 3 sequential full stock trades at +0.27R | about +0.54%, about $538. Compounds near 32% a year |
| 3 sequential full stock trades at +0.50R | about +1.0% |

So a $1,000 week shows up when the measured edge is near +0.50R and the tape actually offers about three non-overlapping full-size trades. It does not show up by raising size, lowering the R minimum, or forcing a trade on a dull day. Trades in the same week are often correlated. The sum of trade R is not a portfolio forecast. Report both.

A book that nets +0.27R at this heat and does it with discipline is a success even when the week is a few hundred dollars. The coach says that in those words.

## 5. Risk constitution

All figures below are implemented in `dragonfly/risk_math.py`. Equity `E` is marked at decision time. If marks are older than 15 minutes during the regular session, the governor rejects new risk (fail closed). That staleness check is a Phase 1 wiring task around the pure function.

### Caps

| Mode | Planned-loss cap | Name heat cap | Book heat cap | New entries |
| --- | --- | --- | --- | --- |
| normal | 1.0% of E | 1.0% of E | 2.0% of E | yes |
| cautious | 0.5% of E | 0.5% of E | 1.0% of E | yes |
| stand_down | 0 | 0 | 0 new | no |

At $100,000 in a normal regime those caps are $1,000, $1,000, and $2,000.

Stock heat = planned loss × **1.5**. Option heat = full debit × contracts × 100. The binding stock budget is the smallest of the planned-loss cap, the name-heat cap divided by 1.5, and the remaining book heat divided by 1.5. On an empty $100,000 book that budget is **$666.66** of planned loss.

Two or more red-team warnings, while the regime is normal, pull the planned-loss cap and the name-heat cap down to the cautious levels. The book heat cap stays at the regime's book cap.

Other ceilings, all binding:

- Position notional ≤ 20% of equity.
- Gross long stock notional ≤ 100% of equity. No margin.
- Shares ≤ 2% of 20-day average share volume. At a $100,000 book and the liquidity floor below, the notional cap usually binds first. The participation cap matters as the book grows.
- At most 4 open positions.
- At most 1 open position per sector.
- At most 2 open positions with the same setup tag.
- Debit must be fully funded in cash. Buying power is cash, not margin.

### Circuit breakers

The tightest condition wins. These are evaluated before any card is sized.

| Condition | Effect |
| --- | --- |
| Day P&L ≤ −1% of equity at the day's start | stand down for new risk |
| Week P&L ≤ −2% of equity at the week's start | stand down for new risk |
| Drawdown from the equity high-water mark ≥ 12% | stand down until Jared resets it in writing |
| Drawdown ≥ 8% and < 12% | at least cautious |
| 4 closed trades in a row at −1R or worse | at least cautious for the next entries |

Open positions are still managed to their cards while new risk is stood down.

### Regime to mode

The regime role emits four enums and the evidence for each. The code, not the model, picks the mode.

| Input | Allowed values |
| --- | --- |
| trend | up, down, range |
| risk_appetite | risk_on, neutral, risk_off |
| volatility | low, normal, high |
| persistence | persistent, mixed, mean_reverting |

`regime_to_mode()`:

- High volatility and risk-off → stand_down.
- High volatility, or risk-off, or mean-reverting, or a range that is not persistent → cautious.
- Otherwise → normal.

### R

`R = net_pnl / initial_risk`.

`initial_risk` is the planned dollar loss locked when the fill is accepted. Net P&L is after commissions and fees. A gap through the stop can print worse than −1R. Record it. Do not cap it at −1.

The heat multiplier is a portfolio constraint. It is not the R denominator. A stock trade that makes $1,000 on $663 of planned risk is about +1.5R even though it consumed about $995 of heat.

### Canonical card

Trigger $84.50, worst acceptable fill $84.63, stop $80.75, target $91.00, ATR $4, empty book, normal regime, no warnings. The governor's answer:

| Field | Value |
| --- | --- |
| Shares | 171 |
| Planned loss | $663.48 |
| Heat | $995.22 |
| Notional | $14,471.73 |
| Expected reward at the target, using the worst fill | $1,089.27 |
| Expected R | 1.64 |

The outline's version of this trade risked $1,000 and showed 1.73R off the trigger. The constitution sizes off $84.63 so a bad-but-legal fill still fits under the $1,000 name-heat cap. Reward/risk stays above the 1.5 minimum. If the fill is the trigger itself, dollar risk comes in lower ($641.25 on 171 shares) and that lower number becomes `initial_risk`.

A second full name does not fit beside this one. With $1,500 of heat already open, the same trade sizes to 85 shares, $329.80 planned, $494.70 heat.

### Option shape

Long call, long put, or debit spread. Example: $2.50 debit, planned exit if premium falls to $1.50, target premium $4.00, legal spread and open interest. Result on an empty normal book: **4 contracts**, planned loss **$400**, heat **$1,000** (the full debit). Expected R at the target is 1.50. If the option goes to zero, the result is **−2.5R**, and that is the number the journal keeps. Heat was the debit. R uses the tighter planned stop.

### What the governor will not do

It will not round a budget up through a cap. It will not approve a trade with reward/risk under 1.5. It will not approve a stop closer than 0.4 ATR or farther than 2.0 ATR. It will not approve a stock entry more than 1.0 ATR past the breakout level. It will not approve stock when an earnings print still sits inside the hold window. It will not approve a card on the live book whose data is provisional or of unknown provenance (`provisional_source_live` from `structural_blocks(book="live", provisional_data=...)`). Phase 1 data is Yahoo via yfinance and is stamped provisional, so it can drive paper cards only.

## 6. Universe, instruments, setups

### Universe

US listed common stock.

- Price ≥ $10.
- 20-day average dollar volume ≥ $25,000,000.
- Not halted.
- Stock spread ≤ the wider of $0.05 and 0.15% of price.
- Options, when used: open interest ≥ 100, volume ≥ 50, bid > 0, and (ask − bid) / mid ≤ 10%.

Phase 1 may scan a smaller liquid watchlist if a full universe feed is not wired yet. The gates stay. A shorter list is allowed. A softer gate is not.

The Phase 1 watchlist is `dragonfly/watchlist.json`, built by `dragonfly/build_watchlist.py` with these gates via `risk_math.universe_reasons`. For the paper book, a name whose Yahoo bid/ask is unusable or fails the spread gate is admitted on a modeled $0.05 spread around the quote mid or last trade (provisional, live-blocked); a name with no usable mid and no usable last trade is excluded. In strict mode (`--spread-mode exact`) a name whose spread was never measured, or whose bid/ask could not be fetched, is excluded, never admitted. Depositary receipts (ADRs, ADSs) are not common stock and are excluded, as is any name whose security type cannot be determined. See `docs/dragonfly/PHASE1_DATA.md`.

### Instruments

Allowed: long stock, long call, long put, debit spread.

Not allowed: short stock, naked options, credit spreads, calendars, undefined risk, margin, averaging down, and any add that was not on the original card. Phase 1 cards have one entry and one target.

Earnings still ahead inside the hold window: stock is forbidden. The expression has to be a defined-risk option whose heat is the debit. Once the print is out, stock is allowed again and the event can be the catalyst.

### Setups

Every card carries exactly one.

**A. `catalyst_breakout`.** A primary catalyst plus price and volume confirmation. Relative volume on the breakout session ≥ 1.8× the 20-day average. The architect names the breakout level. Entry is within 1.0 ATR of that level. Catalyst quality must be `primary`.

**B. `momentum_pullback`.** The move is already underway: 20-session return > 8%, or price above a rising 20-day average that is itself above the 50-day. The pullback is between 0.4 ATR and 1.5 ATR off the recent swing high and does not close back through the prior breakout base. Pullback volume is below the impulse volume. The continuation trigger is a price, not a feeling. Catalyst may be `absent`. Absent catalyst does not block this setup. The red team still has to say so in the narrative.

**C. `failed_breakdown`.** Price broke a named support and reclaimed it within two sessions. Reversal-session volume ≥ 1.5× the 20-day average. Stop goes below the reversal bar. Catalyst quality is `primary` or `secondary`.

**D. `compression_expansion`.** The 10-day range or ATR is in the lowest quartile of the trailing 60 sessions. The expansion session's range is > 1.5× the prior 10-day average range, with volume ≥ 1.5×. Stop goes outside the compression range. Direction follows the expansion. Catalyst may be `absent`.

Shared gates for every setup: stop distance 0.4–2.0 ATR, expected R ≥ 1.5, time stop of 7 calendar days, machine-checkable invalidation.

Catalyst quality:

| Quality | Meaning |
| --- | --- |
| primary | A dated, sourced event in the last five sessions that can change near-term supply or demand |
| secondary | A sector or peer event, indirect |
| absent | Nothing found. "The price is up" is absent |

A catalyst record needs a source URL or filing accession, a timestamp, and one sentence on the mechanism. The catalyst role may not invent one.

## 7. Trade card and states

The card is the object. Schema: `docs/dragonfly/schemas/trade_card.schema.json`. A filled example, using the canonical numbers: `docs/dragonfly/examples/trade_card.json`.

Required content, in plain language:

- Identity: id `DF-YYYY-NNNN`, version, status, ticker, one setup, direction `long`, one instrument.
- Catalyst object, including `earnings_in_window`.
- Why now, in one paragraph.
- Entry trigger (`buy_stop`, `buy_limit`, or `market_on_close_above`), trigger price, and `max_fill`.
- Stop, one target with fraction 1, time stop dates.
- Sizing block copied from the governor, not typed by a model.
- Invalidation drawn only from `stop_hit`, `level_lost`, `time_stop`, `catalyst_retracted`. `stop_hit` and `time_stop` are mandatory.
- Evidence links and the measurements that passed the gates.
- Red-team decision, hard-block codes (must match the engine), warning flags, narrative.
- Risk decision: `APPROVED` or `REJECTED`, reasons, mode.
- Human decision, null until Jared acts.
- Watcher state, null until the position is active.

Once status is `approved`, the card is frozen. `frozen_at` is set. Any change creates the next version, status returns to `candidate`, and the new version has to clear the engine and Jared again. The old version stays on disk.

### States

| Status | Meaning |
| --- | --- |
| candidate | Drafted, not yet cleared |
| blocked | Engine hard block |
| risk_rejected | Governor rejected the size or the heat |
| pending_human | Governor approved. Waiting on Jared |
| approved | Jared approved. Not filled |
| active | Filled inside `max_fill` |
| closed | Out by stop, target, time, invalidation, or a human tighten |
| invalidated | Trigger failed, chase beyond `max_fill`, or catalyst retracted before the fill |
| expired | Time stop arrived and the order never filled |
| breached | Still open after the time-stop session. Process failure |

Legal path for a trade that happens: candidate → pending_human → approved → active → closed.

Jared's `tighten` reduces units below the approved size and produces a new version that the governor must still approve. It cannot increase units.

## 8. Clock and exits

The clock is a maximum, not a prompt to invent a new thesis on day 4.

- Entry session is day 0. The session date is the NYSE date of the fill.
- The deadline is the entry session date plus 7 calendar days.
- The exit session is the last NYSE session after entry and on or before that deadline. `time_stop_session()` is the implementation.
- The position is flat by 15:55 America/New_York on that session unless a stop or target already closed it.
- If the deadline is not a session, the prior session is the exit. There is no silent extra day.

Worked dates from the tests: a Friday 25 September 2026 entry exits Friday 2 October 2026. If that Friday is not a session, the exit moves to Thursday 1 October, not to the following Monday.

Three exits, all chosen before entry:

| Exit | Meaning |
| --- | --- |
| Hard stop | Thesis is wrong. Stock: the stop price. Option: the planned premium stop. Structural max loss remains the debit |
| Target | The single target on the card. Full exit |
| Time | Exit session, above |

Human tighten is a fourth way out. It is allowed, it is labeled `human_tighten` on the journal, and it is not a new target invented mid-trade.

The day-by-day watchlist (momentum on day 1, follow-through on day 2, and so on) is observational. It can turn the watcher yellow. It does not add an exit.

Watcher, once a position is active:

| State | Rule |
| --- | --- |
| RED | Stop traded, time-stop session reached, close through `invalidation_level`, or a sourced catalyst retraction |
| YELLOW | Open loss of 0.5R or worse with half the calendar window gone; volume pace under 0.6× after day 2; or VWAP lost when the card said the thesis required holding VWAP |
| GREEN | Otherwise |

RED means flatten this session. In Phase 1 the Chief of Staff alerts Jared. If the position is still open after that close, status becomes `breached`.

## 9. Team and decision rights

Nine roles and one engine.

| Role | Kind | Owns | Does not own |
| --- | --- | --- | --- |
| Chief of Staff (Ditka89) | Orchestrator | The day's sequence, the brief, `NO_TRADE`, the alert when a watcher goes red | Sizing, clearing a reject, editing a frozen card, inventing a setup |
| Market Regime | Model for the four enums | Evidence and the classification | The mode, and any ticker pick. Mode comes from `regime_to_mode()` plus the circuit breakers |
| Wave Scanner | Measurements in code | The candidate list and the rank key | A recommendation to buy |
| Catalyst | Model, sources required | Quality, link, timestamp, mechanism, earnings flag | A catalyst with no source |
| Price and Flow | Model | Trend, VWAP, levels, gap structure, ATR, volume, relative strength, breakout and pullback quality, options, short interest, sector flow | Position size |
| Trade Architect | Model, schema-bound | A complete card with one setup and one instrument | Submitting a card with a null required field |
| Red Team | Model, closed checklist | The warning flags and the written case against the trade | A veto the engine did not already code |
| Risk Governor | `dragonfly/risk_math.py` | `APPROVED` or `REJECTED` | Persuasion |
| Trade Watcher | Rules, short note | green / yellow / red on open cards only | A new thesis or a longer clock |
| Performance Coach | Model reading deterministic stats | The weekly note and at most one proposed amendment | Installing the amendment |

Scanner rank key, when more than 15 names pass the mover screen: relative volume × absolute percent move, descending. Deep dives stop at 15. That is an attention cap, not a quota of trades.

Red-team warning flags, each true or false, from evidence:

`crowded_options`, `sector_lagging`, `wide_spread_but_legal`, `contradictory_filing`, `valuation_extreme`, `gap_history`, `event_just_outside_window`.

`gap_history` is true when a gap in the last 60 sessions exceeded 1.5× the planned stop distance. `valuation_extreme` requires a cited number. Free-text worry does not count as a warning and does not change size.

## 10. The day

Timezone for the operator's brief: America/Chicago. The exit clock uses the NYSE session calendar.

1. Mark the book. Run circuit breakers and the regime map. If new entries are stood down, say so in the first line and skip to step 7 for anything new. Open cards still get a watcher pass.
2. Scan. Emit measurements, not recommendations.
3. Take at most 15 names into catalyst and price/flow.
4. Architect a card only when a setup's gates are actually met.
5. Run `structural_blocks()` and `size_stock()` or `size_option()`. Copy the result into the card. Do not retype it.
6. Red team fills the checklist and the narrative.
7. Publish the daily brief, including on days with nothing to do. Schema: `docs/dragonfly/schemas/daily_brief.schema.json`.

`recommendation` is `REVIEW` only when at least one card is `pending_human`. Otherwise it is `NO_TRADE`.

The brief records the funnel with the schema's keys: `universe`, `unusual`, `deep_dives`, `setup_passes`, `catalyst_passes`, `architected`, `red_team_passes`, `risk_passes`. `red_team_passes` counts cards with no engine hard block. Warnings stay in that count and tighten size. The outline's 5,000 → 1 picture is a description of taste. The machine reports the counts it actually got.

Hypothetical fills in the paper book use a modeled $0.05 spread (Jared, 2026-09-25): buys fill at mid + $0.025 and sells at mid − $0.025, rounded adversely to the cent, labeled `fill_type: hypothetical`, with commissions recorded even when they are zero. For a buy-stop entry the mid defaults to the trigger. On the canonical trigger of $84.50 that paper fill is $84.53, which is inside the $84.63 max fill. Below a $16.67 trigger, $0.025 is more than the 0.15% max-fill band, so an at-trigger paper entry there is invalidated. A modeled spread is paper only: a live card using one is blocked (`provisional_source_live`). A buy fill above `max_fill` invalidates the card. Live fills later replace the hypothesis. R is recomputed from the real fill and the original stop.

## 11. Journal and coach

Schema: `docs/dragonfly/schemas/journal_entry.schema.json`.

Every closed, invalidated, expired, or breached card gets an entry. The numbers are computed: prices, exit reason, initial risk, net P&L, R, MAE in R, MFE in R, hold in sessions, regime at entry, fill type. The model writes the prose around those numbers and picks one mistake tag.

Mistake tags: `none`, `chased`, `late`, `early_exit`, `stop_too_tight`, `ignored_red_team`, `size_error`, `catalyst_wrong`, `regime_conflict`, `time_stop_missed`.

`would_repeat`: `yes`, `no`, or `only_if`.

Weekly scoreboard, from `weekly_scoreboard()`:

- Trade count, sum of R, expectancy per trade.
- Net dollars and percent, translated from the fills.
- No field for "dollars behind the $1,000 target." The function does not have one. A test locks that.

The coach answers these seven questions and then stops:

1. Which setup has the best and worst mean net R, and what is n?
2. What is the average MAE on winners?
3. What is the average MFE on losers?
4. Did any RED alert fail to flatten the same session?
5. How many `NO_TRADE` days were there, and what did SPY do?
6. Did the book violate a rule?
7. One proposed amendment, or "none."

A setup is eligible for a retirement proposal only after 40 closed trades in that setup, and only when mean net R is ≤ 0. Before that, the coach may flag it and may not demand that it die. Jared decides. SPY is reported beside the book so a rising tape is not mistaken for an edge. Beating SPY is not the mandate.

## 12. Cockpit

Local, private, generated from the state files. It is not a new public homepage.

Views:

1. **Book.** Equity, day, week, month, year-to-date percent, heat versus cap, open trades as R and day count.
2. **Today.** Regime, mode, funnel, `NO_TRADE` or `REVIEW`, cards waiting on Jared.
3. **Trade.** The card, version history, watcher state.
4. **Journal.** One case study per closed trade, using the journal fields.
5. **Performance.** Win rate, average winner, average loser, expectancy, R distribution, max drawdown, average hold, MAE, MFE, by setup, by regime, by weekday. All of these are queries over the journal, not model estimates.

Phase 1 does not publish this under `site/`. If a later phase puts it on Pages, Tony B reviews the ship, and the page still cannot contain live positions until Jared says the track record is public.

## 13. Phases and acceptance

### Phase 1 — paper book

Build the nine roles around the engine that already exists. Persist cards, briefs, and journal entries under `dragonfly/state/live/` (gitignored). Render the local cockpit.

Phase 1 is done when all of the following are true:

- `python3 dragonfly/test_risk_math.py` passes.
- A session can end in a valid `NO_TRADE` brief.
- A card can travel candidate → pending_human → approved → active → closed, and an edit after approval creates a new version instead of a silent change.
- Hypothetical fills never exceed `max_fill`.
- The cockpit renders book, today, and journal from local state.
- No broker connection exists.
- Live state is not in git.

Paper gate before any live order: 20 hypothetical trades journaled, or 10 sessions including at least 3 `NO_TRADE` days, whichever comes later, plus the tests above. Jared may waive this gate in writing. The waiver is stored next to the book.

### Phase 1b — live, human execution

Jared places the orders. The first 20 live trades use cautious caps no matter what the regime says. Alerts on RED are mandatory. A missed time stop is `breached`, not a quiet hold.

Go-live requires the Phase 1 acceptance list, the paper gate or its written waiver, and a one-line written go-live from Jared.

### Phase 2 — after 100 closed trades

Identify the setups with positive measured net R. Propose retirement of the ones that qualify under the rule in section 11. Only then consider a second target, scale-in rules, regime-specific setup permissions, and adaptive size inside the existing caps. The caps do not get looser in order to chase the aspiration.

### Phase 3 — after the edge is measured live

Broker integration, automated alerts, richer options work, and a public track record wait until at least 100 live trades show positive net expectancy after costs. The public research site is still a separate decision. Naked and undefined risk stay out.

## 14. Handoff

Ditka89 starts at `docs/dragonfly/COS_STANDING_ORDER.md`, implements against `dragonfly/risk_math.py`, and validates every card and brief with the schemas in `docs/dragonfly/schemas/`.

Do not widen the universe gates, do not add a fifth setup, and do not put the $1,000 week into a prompt as something to go get. When the ocean is flat, publish `NO_TRADE` and close the session.

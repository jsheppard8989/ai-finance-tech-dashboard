# Nov 5 original-entry correction

Original saved Oct 29 bid/asks only; no current quote was fetched or substituted. This is a modeled paper-entry correction, not a record of execution. All four put spreads remain held to expiry.

## Evidence and arithmetic

Source audit: `/workspace/cos/runs/2026-11-05-entry-fill-audit.md`.
ASTS/FRMI/TSAT: `/workspace/cos/trapmap/row_trades_2026-10-29.md`, lines 2 and 11–13, Oct 29 about 1:57 PM CT.
MU: `/workspace/cos/research/mu_data/rerate/opt_open_2028-12-15.json`, Oct 29 8:32 AM CT; the saved raw bid/asks and previous-day last trades were independently checked.

Buy = ask − (ask−bid)/3; sell = bid + (ask−bid)/3. Exact fractions are used through cost/max-profit calculations; only final dollar totals are rounded to cents. Entry quote inputs and modeled leg fills are embedded in each row under `entry_pricing`. Existing `mark`, `value`, `quoted`, `mid_time` and `mid_source` fields continue to describe subsequent marks, not entry evidence.

| Row (spreads) | Original long bid/ask; short bid/ask | Debit/share, before → after | Entry cost = max loss, before → after | Expiry breakeven, before → after | Current value (unchanged) | Dollar return, before → after | Return %, before → after |
|---|---|---|---|---|---|---|---|
| ASTS (7) | 3.30/3.60; 1.03/1.28 | $2.295000 → $2.386667 | $1,606.50 → $1,670.67 | $40.705 → $40.613333 | $2,916.69 | $+1,310.19 → $+1,246.02 | +81.56% → +74.58% |
| FRMI (60) | .35/.45; .15/.20 | $0.225000 → $0.250000 | $1,350.00 → $1,500.00 | $2.775 → $2.750000 | $2,500.20 | $+1,150.20 → $+1,000.20 | +85.20% → +66.68% |
| TSAT (5) | 5.80/6.60; 3.00/3.50 | $2.950000 → $3.166667 | $1,475.00 → $1,583.33 | $37.050 → $36.833333 | $1,433.35 | $-41.65 → $-149.98 | -2.82% → -9.47% |
| MU (1) | 108/128; 40/60 | $68.000000 → $74.666667 | $6,800.00 → $7,466.67 | $632.000 → $625.333333 | $8,455.00 | $+1,655.00 → $+988.33 | +24.34% → +13.24% |

MU maximum net profit: $13,200 → $12,533.33; maximum gross payout stays $20,000. The exact modeled MU breakeven is $625.333333… ($625.33 displayed). The expiry result is zero at that exact breakeven; the full debit is lost at or above $700.

## Portfolio and S&P comparison

| Metric | Before | After |
|---|---:|---:|
| Allocated | $39,828.17 | $40,817.34 |
| Current value | $42,777.11 | $42,777.11 |
| Dollar return | $2,948.94 | $1,959.77 |
| Same money in SPY | $40,150.00 | $41,135.88 |
| Return | +7.4042% | +4.8013% |
| SPY return | +0.8080% | +0.7804% |
| Value above SPY | $2,627.11 | $1,641.23 |

The Oct 29 SPY lot remains on its original date at the saved $769.36 close. Dollars: $11,231.50 → $12,220.67; shares: 14.59850 → 15.88420 (existing five-decimal share convention). Other lots and the saved $766.81 current SPY close are unchanged.

## Reproduction (Python 3.11)

From the fresh clone root, with pytest, markdown, matplotlib and the existing pipeline test dependencies installed:

```bash
export WORKSPACE_ROOT="$PWD"
python3.11 scripts/reprice_entry_fills_1105.py
python3.11 docs/research/mu/chart2.py
python3.11 docs/research/mu/chart3.py
python3.11 scripts/build_mu_research.py
python3.11 pipeline/build_trap_map.py --check
python3.11 pipeline/trap_map_check.py
python3.11 pipeline/publish_guard.py
python3.11 -m pytest pipeline -q --tb=short
```

The entry correction script checks audited totals and original row structure before mutation and updates only the four entries plus their original benchmark lot. It delegates row changes, totals, HTML and homepage generation to the existing Trap Map builder. It never opens a database or fetches quotes.

MU chart sources and the historical CSV inputs are preserved under `mu/`, adapted from the saved original chart scripts. Chart 1 is unchanged. `mu/mu_page.md` and `mu/mu_summary.md` are the research text sources; `mu/page_shell.html` supplies layout and chart captions/alt text to the existing markdown converter.

## Verification

- Eight new regression cases were observed failing before the fix and passing afterward.
- Full baseline: 781 passed, 3 failed. Full corrected run: 789 passed, the same 3 baseline failures (no test weakening).
- Baseline failures: `test_sweep_1103_followup.py::test_guest_list_rename_live_and_scoped`; `test_trap_map.py::TestValidator::test_healthcare_stop_is_fixed`; `test_trap_map.py::TestMidpointLabel::test_prices_labeled` (unchanged CEG current-value expectation).
- Build output check, Trap Map validator and unchanged publish guard pass; the guard reports existing informational wrong-if/backlog and stale-ticket warnings.
- Current quote timestamps/values and all unrelated rows are unchanged. No `dragonfly/` or guard modifications, and no real database writes.
- This PR is preview-only and must not be merged without Jared’s approval.

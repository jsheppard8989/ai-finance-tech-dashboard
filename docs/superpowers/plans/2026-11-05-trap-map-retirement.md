# Trap Map Retirement Implementation Plan

> **For agentic workers:** Execute inline with executing-plans. No cloud agent; the owner explicitly requested Shell + git + gh.

**Goal:** Remove the public Trap Map without losing historical records or altering the remaining site.

**Architecture:** Preserve byte-identical JSON, rendered page, full pre-removal home page and source snapshots under pipeline/private_archive/trap_map. Repoint internal render/validation tools there. Replace the missing-public-page guard bypass with fail-closed archive-integrity and no-public-leak checks. Remove only the home navigation link and generated strip; research pages already contain no Trap Map links.

**Tech Stack:** Python 3.11, pytest, static HTML/JS, GitHub Actions, git/gh.

## Global Constraints
- No real dashboard.db writes; no dragonfly changes; fresh clone /workspace/tmp/trapoff1105.
- Keep podcast filtering, scripts, research pages, original records and totals. G's final ruling: public paper expressions must be historical, paper-only and dated; remove current portfolio framing and rollups. Freeze portfolio.json bytes and keep qqq-filter.html completely untouched.
- No private repository claim: the repository is public, although archive paths are outside Pages.
- No new internal strategy site, paid service, orders, funding or unrelated publication.

### Task 1: Red tests and preservation
- [x] Add tests that require an archive manifest, byte-identical snapshot hashes, no public route/data/link/strip, and default builds only outside site/.
- [x] Run `WORKSPACE_ROOT=$PWD /workspace/tmp/trapoff1105-venv/bin/python3.11 -m pytest pipeline/test_trap_map_retirement.py -q`; expect failures on missing archive and still-public surfaces.
- [x] Copy current public JSON, page and home plus original generator/fetch/validation/sync/repricing source text into the archive, with source commit and SHA-256 manifest; remove the public page/data via moves, not destruction.

### Task 2: Archive-only build and fail-closed guard
- [x] Set build DATA/PAGE/INDEX and validator DATA to pipeline/private_archive/trap_map paths; reject output overrides inside site/.
- [x] Add trap_map_archive.py validation of recorded file hashes, required record/totals schema, baseline row preservation and zero public Trap Map references.
- [x] Call that validator from publish_guard when retired, preserving all existing checks for historical fixtures and all other guards.
- [x] Keep the original fetcher functions for internal tests; its CLI refuses to refresh the frozen archive.

### Task 3: Public removal and workflow cleanup
- [x] Remove only the Trap Map home navigation anchor and the TRAP_STRIP marker block; leave all scripts and podcast filtering untouched.
- [x] Replace the deploy build check with archive-integrity/public-absence validation.
- [x] Remove the retired market-data pull, its staging paths and its fail-run step; retain GPU index, forward curve, Treasury refresh, validation, PR/merge and Pages dispatch.
- [x] Repoint historical data/page tests to archive paths; preserve all math, stop, fill-rule, modeled-label and rendering assertions. Add guard regressions for missing/corrupt archives and resurrected public content.

### Task 4: Verify and ship
- [x] Run the full pipeline suite and all legacy test files in isolated processes; only the existing Healthcare snapshot failure is permitted.
- [x] Run publish_guard and archive build --check; compare every unrelated public file and home script byte-for-byte with main.
- [x] Check all public files for dangling routes, run static JS syntax/runtime checks where supported, and disclose unavailable real-browser console verification.
- [ ] Create a clean PR describing all test adaptations, archive locations, repository privacy caveat and exact scope. Check merge readiness; squash merge; wait for Pages deployment.
- [ ] Verify live page and data endpoints return 404, home/research endpoints remain 200 and link-free, archive exists in the merged repo, and report evidence.

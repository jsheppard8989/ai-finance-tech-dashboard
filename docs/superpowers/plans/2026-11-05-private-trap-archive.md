# Private Trap Map Archive Correction Implementation Plan

> **For agentic workers:** Execute inline: the owner explicitly requested normal local clone/commit/push operations. Use executing-plans task by task.

**Goal:** Remove every archived record from the public branch only after preserving and verifying the complete byte-identical archive in the confirmed-private repository.

**Architecture:** The private repository and ops-box directory hold the original snapshot unchanged. The public repository holds only a locator document and a metadata/checksum-only JSON locator. Public publish checks require that pointer and reject public record files, without opening private files or using private network access. Local record assertions use an external archive path and skip explicitly if unavailable; synthetic math/validator coverage continues in public CI.

**Tech Stack:** Python 3.11, pytest, git/gh, static GitHub Pages.

## Global constraints
- Private destination: jsheppard8989/dragonfly-private, main, trap_map_archive_2026-11-05/.
- Ops copy: /workspace/cos/trap_map_archive_2026-11-05; preserve every file byte-identically and keep manifest SHA-256 validity.
- No record payloads, record ids, marks or totals in public locator files.
- No public site, QQQ filter, podcast/filter or financial record changes.
- No private CI network access, no historical source deletion, no real dashboard database writes, no Dragonfly code changes.
- Do not rewrite public git history or force-push; report the exposure window and surviving history.

### Task 1: Preserve and verify before public removal
- [x] Confirm destination visibility PRIVATE, clone normally, copy all 27 files unchanged and verify all 25 original manifest file hashes.
- [x] Commit and push private main; verify records through authenticated gh api at the resulting commit.

### Task 2: Public pointer and offline-safe guards/tests
- [x] Add failing public-absence, pointer-only, outside-repository path and no-private-read guard regressions.
- [x] Add pipeline/TRAP_MAP_RETIREMENT.md plus a checksum-only locator pinned to the private commit; remove the public archive directory only after Task 1.
- [x] Repoint builder/validator/legacy updater, publish guard, existing record tests and the prior retirement plan. Keep pure/synthetic tests running and explicitly skip only external-record assertions when no local archive exists.
- [x] Run both with-local-private and absent-private test modes. Public guard must reject missing/bad pointers and accidentally copied public record files.

### Task 3: Verify and ship
- [x] Run all test modules in isolated Python 3.11 processes with WORKSPACE_ROOT set to the fresh clone; record all passes/skips and the one known healthcare failure.
- [x] Verify private hashes, public guard, no public site diff and no records in the new public branch tree.
- [ ] Open and squash-merge the follow-up PR; wait for the exact Pages run.
- [ ] Verify raw main archive URL 404, home/research 200, private gh api readability; report exact merge timestamps in CT and unrevised public-history exposure.

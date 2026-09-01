# Ops Orchestration & RACI

> **Last verified:** 2026-08-31 evening (America/Chicago)

## Roles

| Person | Role | Scope |
|--------|------|-------|
| **Tony B** (Grok Bot shipping) | Owns Pages/workflows/protection/merge discipline | Must be in the loop for any merge to `main` or Pages-facing `site/` ship |
| **G(ai)ndolf** | Website/content admin | Draft PRs and investigation OK; ping Tony B before ship |
| **Ditka89** | Chief of Staff | Accountable for ops orchestration; weekday CoS pulse |
| **Jared** | Human gates | Debate script approval, credentials, final authority |

## Cursor Ops Shipping Freeze

**Effective policy:** No merge to `main` and no Pages-facing `site/` ship without Tony B approval.

- Cursor draft PRs: ✅ allowed
- Cursor investigation/research: ✅ allowed
- Cursor merge to `main`: ❌ blocked until Tony B reviews
- Cursor `site/` deploy: ❌ blocked until Tony B reviews

## Compute Location

Pipeline LaunchAgents (`com.scarcity.pipeline.*`, `com.scarcity.whisper-worker`, etc.) run on **Jared's Mac** via launchd.

The Grok Bot box does **not** run these LaunchAgents.

An always-on migration is not yet decided.

## Branch Protection

GitHub repository ruleset (id `21978893`, name "Protect main (PR required)") on `refs/heads/main`:

- Requires pull request before merge
- Required approving review count: **0** (self-merge allowed after PR)
- No required status checks
- No signed commits or linear history requirement

Note: The classic branch protection API still reports `main` as unprotected because protection is enforced via rulesets, not the legacy API.

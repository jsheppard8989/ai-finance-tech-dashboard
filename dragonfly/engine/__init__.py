"""Dragonfly 7 pre-open engine (private; paper book).

Polls Architect drafts in the private handoff repo, runs the deterministic
governor (dragonfly/risk_math.py) on each, and writes frozen trade cards plus
the DONE marker. Also hosts the READY marker helper for the 08:05 CT job.

No market-data network calls: every price comes from the draft or from the
Mac's handoff prep data. See docs/dragonfly/ENGINE.md.
"""

ENGINE_VERSION = "dragonfly-engine/1"

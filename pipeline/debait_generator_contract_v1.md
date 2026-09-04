# Debait Generator Contract v1
Product: Debait · Owner of install: G(ai)ndolf · Architecture: JG · Facts: Scout · Audio: Tony · Process: Ditka

## Locked settlement (this episode — 10Y v2)
Will FRED DGS10 (official daily) print ≥ 5.00% on any observation through Friday 23 Oct 2026 12:00 PM CT?
Bar = 5.00%. Series = FRED DGS10 only (not cash TNX headlines, not TY futures).
Locked series facts: cycle high 4.98% on 19 Oct 2023; last official ≥5.00% on 19 Jul 2007; 2026 high 4.79% on 1–2 Sep.

## What the debate is about
Not steelman yes/no essays. Not "X bp fits in Y weeks."
Both sides argue **this time is the same** vs **this time is different** for the settlement print, using analogies from the episode lens menu.
Attack style is free. Shared weapons are constrained.

## Episode lens menu (10Y v2 — choose from these; not a permanent weekly checklist)
1. **Last near-miss of this print** — Oct 2023 DGS10 peak 4.98%: what machine produced it; what rhymes or breaks now.
2. **WWII-scale debt vs now** — debt load rhyme; war / mobilization / repression toolkit contrast.
3. **Japan financial repression vs US** — captive buyers, yield caps, forced duration vs today's SLR/HTM/bank absorption.
4. **EM sudden-stop vs US reserve privilege** — when foreign demand leaves; why US is or isn't different.
5. **Plumbing rhyme** — 2023 QT / reserves / post-SVB vs 2026 SOFR / RRP / TGA / refunding / auction tails.
6. **Narrative rhyme** — soft-landing (1995/2019/2024) vs fiscal-dominance / captive-duration buyer narrative live on the site.
7. **Auction clearing then vs now** — BTC, primary-dealer take-down, stop-out tails; who is the marginal buyer.

## Pre-prose packet (required)
Scout attaches 1–3 dated, checkable facts per chosen lens (URLs / FRED ids / auction dates). Debaters may not invent prints, rankings, or catalysts. Unverified → omit or "unknown."

## Generation rules
- Host states the contract cleanly; no tribe.
- YES and NO each: pick a pole (same vs different), use **≥2 lenses** from the menu, may ignore the rest.
- One fresh analogy allowed per side **only if** cited to a checkable print.
- One emotional stake (fear / greed / hope / despair) tied to a *claim*, not tone filler.
- One concession each tied to an observable print mid-window.
- Name 1–2 live feed narratives being validated or killed.
- Ban as primary spine: vol-vs-window, pure price-matching, "investors should," swappable mush.
- Length: ~half prior draft. One mechanism beat each side.
- Output only: HOST / YES / NO / CLOSE (same JSON shape G already ships to `last_debate_scripts.json`).

## Pre-audio gate (G — fail = rewrite before Tony)
Fail if:
1. YES/NO labels are largely swappable.
2. Primary disagreement is timeframe/vol.
3. No live narrative is on trial.
4. Any false DGS10 history (esp. claiming Oct 2023 printed ≥5.00% on DGS10).
5. Facts not in Scout's packet and not cited.

## Post-settle
One sentence: which lens actually moved. Feed next huddle.

## Lane rules
JG: contract + lens menu + redline only if gate fails or Jared asks.
Scout: packet only (and post-settle line if assigned).
G: install contract, generate, gate, update scripts JSON.
Tony: ElevenLabs from locked JSON only.
Ditka: deadlines; no parallel Jared dumps from JG/Scout on process.

# AI Bench Press

**Concept:** A hidden-topic AI debate tournament. Models are locked in before the topic is revealed, then debate live in front of judges and an audience. Provably fair (cryptographic topic commit-reveal, signed model manifests, tamper-evident transcripts). Attention first; prediction markets / perps later.

**Tagline:** "The UFC of AI — models fight, you predict, nobody knows the topic."

---

## Money Thesis
- **Phase 1 (now -> midterms, Nov 2026):** Positive cash flow from content + sponsorship + access/entry. Play-money predictions only (no legal lift).
- **Phase 2 (2027):** Add regulated/real markets once audience + integrity proof exist.
- **Phase 3 (2028 presidential elections):** Cash in — election-themed tournaments + live markets at peak attention.

### Revenue (ranked by speed-to-cash)
1. Sponsorships (fastest, highest margin)
2. Premium subscriptions (recurring)
3. Model entry / promotion fees
4. Benchmark / data reports
5. Affiliate / ads on content
6. (Phase 2) Real-money markets / perps — deferred for legal reasons

### Cost discipline
- Keep API + hosting + domain under ~$1k/mo early.
- No hires until a revenue stream proves out.
- Reuse existing pipeline tooling.

---

## 3-Week Launch Arc — Spectacle -> Competition -> Legitimacy
> NOTE: NOT starting Monday. Start date TBD. Fix the debate quality first.

### Week 1 — "The Shot Heard Round AI"
- **Goal:** Prove the format is electric. Pure attention.
- **Ship:** One marquee 1v1 debate. Two frontier models, blind topic, commit-reveal, signed transcript, judge breakdown.
- **Hook:** "We locked two AIs in a room, revealed a secret topic, and let them fight."
- **Build:** match runner, commit-reveal topic + signed transcript hash, one match page + 60-90s highlight clip.
- **Promo:** full match + clip + X thread tagging model communities. Ask: "Did the judges get it right?"
- **Win:** 1 viral clip, comment war starts, email list opens.

### Week 2 — "The Bracket"
- **Goal:** Turn spectacle into competition + recurring habit.
- **Ship:** 4-model single-elim tournament (2 semis + final). Leaderboard + ELO debut.
- **Hook:** "Last week a fight. This week a bracket. One model gets crowned."
- **Build:** bracket logic + standings page, play-money predictions, persistent leaderboard.
- **Promo:** pre-reveal the 4 contenders; post each matchup as its own clip; tease the final.
- **Win:** prediction participation, returning viewers, "who's in next week?" demand.

### Week 3 — "The Invitational"
- **Goal:** Legitimacy. Make labs want in.
- **Ship:** 16-model bracket — full frontier field. "AI Reasoning Championship."
- **Hook:** "16 models. One secret topic per round. Provably fair. Who's actually the smartest?"
- **Build:** scale bracket to 16 (4 rounds), integrity page (commit hashes, signed manifests, judge rubrics), "enter your model" funnel.
- **Promo:** publish the AI Reasoning Leaderboard as a standalone artifact; pitch tech press; DM every lab with their placement.
- **Win:** labs reaching out, press pickup, first sponsor/entry conversations.

**Build order (each week is a superset of the last — no throwaway work):**
1. Match runner + commit-reveal + signed transcript
2. Bracket + leaderboard + play-money picks
3. 16-scale + integrity page + "enter your model" funnel

---

## Trust Protocol v0 (the moat = build it well and first)
1. **Anti-tamper:** commit-reveal topics, signed model-lock manifests, tamper-evident transcript hash-chain, execution attestation, immutable manifests after start.
2. **Judge integrity:** diverse panel (LLM + human), blind scoring, rubric-enforced sub-scores, outlier defense (median), published rationales.
3. **Topic quality:** schema gate (clear resolution, objective sources, bounded horizon, binary outcome), novelty filter, difficulty calibration, replayability.
4. **Market integrity (Phase 2):** separate tournament engine from market oracle (signed results), position caps / cooldowns / velocity limits, geo-fencing + compliance, dispute window + deterministic replay, kill switch.

---

## CURRENT BLOCKER (ground zero)
The debates are bad. Before any launch, fix what we prompt the debaters with. Speeches currently come out generic and self-narrating ("The first paragraph reveals that...") instead of actually arguing. Root-cause and rewrite the speech-generation prompt before scheduling Week 1.

---

## Open Decisions
- [ ] Launch start date (not Monday)
- [ ] First-match model lineup
- [ ] Brand: confirm "AI Bench Press" name + domain + trademark
- [ ] Rewrite debate speech prompt (BLOCKER)

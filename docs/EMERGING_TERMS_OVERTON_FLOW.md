# Emerging Terms → Overton Window: Current Setup & Flow

> **Last updated:** 2026-09-01 (novelty-aware ranking overhaul)

## Overview

The Overton Window surfaces recurring ideas from podcast/newsletter feeds. Terms must be
mentioned across **multiple episodes** before appearing on the main board.

### Key changes in this version
- **Novelty-aware ranking**: Terms ranked by freshness + source diversity + specificity, not raw volume
- **Established tier**: Saturated terms (AGI, Autonomy, etc.) demoted to a collapsible section
- **Extraction stop-list**: Generic phrases filtered from Emerging Terms inbox
- **Better Signal display**: Log-scaled bars instead of saturated percentages

---

## Current setup (LIVE)

### 1. Where Emerging Terms come from
- **Source:** `suggested_terms` table
- **Population:** 
  - `analyze_transcript.py` extracts `emerging_terms` from AI analysis
  - `manage_suggested_terms.py` scans summaries/newsletters for regex patterns
  - Both insert into `suggested_terms` with `status = 'pending'`
- **Filtering:** 
  - `extraction_stoplist.py` blocks generic phrases ("AI takeover", "Compute shortages", etc.)
  - `saturated_terms.py` flags established terms (AGI, Autonomy, AI Boom, etc.)
- **Export:** `get_suggested_terms_for_website(limit=4)` → `dashboardData.suggestedTerms`
- **Site:** Emerging Terms box displays filtered pending terms

### 2. Promotion to Overton Window
- **Script:** `auto_curate_terms.py` runs after suggested-terms scan
- **Gate:** Requires 2+ mentions across 2+ distinct episodes
- **Action:** Auto-promotes to **both** `definitions` and `overton_terms` tables
- **Notification:** Sends iMessage for manual review of borderline terms

### 3. Overton Window ranking (novelty-aware)

The main Overton board now ranks by **novelty score**, not raw mentions × recency:

```
novelty_score = (freshness × source_diversity × specificity) + recency_bonus
```

Components:
- **Freshness**: Newer terms (days since `first_detected_date`) score higher (90-day half-life)
- **Source diversity**: Terms mentioned across multiple shows get 1.0–2.0× bonus
- **Specificity**: Established/saturated terms get 85% penalty (multiplier = 0.15)
- **Recency bonus**: Recent `last_mentioned_date` adds a small boost (30-day half-life)
- **Mention factor**: Log-scaled to prevent volume domination

### 4. Established tier (saturated terms)
Terms in `saturated_terms.ESTABLISHED_TERMS` are demoted to a separate collapsible section:
- AGI, Artificial General Intelligence
- ASI, Artificial Super Intelligence
- Autonomy, Authenticity, AI Boom
- Machine Learning, Deep Learning, Neural Networks

These still appear on the site but don't crowd out newer/specific ideas.

### 5. Signal display (resonance replacement)
Old "Resonance" bars saturated at 100% due to low cap (4.0). New "Signal" uses log scale:

```javascript
signal_pct = log(1 + novelty_score × 10) × 25  // Clamped to 5–95%
```

This spreads values across the 0–100 range for better visual differentiation.

---

## Data flow

```
Transcripts/Newsletters
        ↓
  AI extraction / regex scan
        ↓
  suggested_terms (status='pending')
        ↓ [filtered by extraction_stoplist]
  Emerging Terms box (site)
        ↓ [2+ mentions across 2+ episodes]
  auto_curate_terms.py
        ↓
  overton_terms + definitions
        ↓ [ranked by novelty_score]
  Main Overton board (new ideas)
        ↓ [if is_established]
  Established tier (collapsed)
```

---

## Key files

| File | Purpose |
|------|---------|
| `pipeline/saturated_terms.py` | Established term list + specificity multiplier |
| `pipeline/extraction_stoplist.py` | Generic phrase filter for Emerging inbox |
| `pipeline/db_manager.py` | Novelty scoring in `get_main_page_content()` |
| `pipeline/auto_curate_terms.py` | Promotion logic (suggested → overton) |
| `site/index.html` | `loadOvertonWindow()` renders both tiers |

---

## Configuration

### Adding established terms
Edit `pipeline/saturated_terms.py`:
```python
ESTABLISHED_TERMS["New Term"] = EstablishedTerm(
    term="New Term",
    reason="Why this term is saturated",
    min_mentions_before_established=5,
)
```

### Adding stoplist phrases
Edit `pipeline/extraction_stoplist.py`:
```python
EXTRACTION_STOPLIST.add("Generic Phrase")
```

### Tuning novelty scoring
In `pipeline/db_manager.py`:
- `freshness_half_life_days = 90.0` — how fast freshness decays
- `recency_half_life_days = 30.0` — how fast recency bonus decays
- `ESTABLISHED_TERM_RANKING_MULTIPLIER = 0.15` — penalty for saturated terms

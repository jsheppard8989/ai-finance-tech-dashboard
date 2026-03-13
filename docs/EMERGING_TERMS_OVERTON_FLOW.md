# Emerging Terms → Overton Window: Current Setup & Target Flow

## Current setup

### 1. Where Emerging Terms come from today
- **Source:** `suggested_terms` table.
- **Population:** `manage_suggested_terms.py` → `scan_content_for_terms()`:
  - Reads **episode summaries** and newsletter content (not full transcripts).
  - Uses **regex/heuristics** (`extract_terms_from_content`) to find quoted phrases and repeated capitalized phrases.
  - Inserts/updates rows in `suggested_terms` with `status = 'pending'`.
- **Export:** `get_suggested_terms_for_website(limit=4)` → `dashboardData.suggestedTerms`.
- **Site:** Emerging Terms box reads `suggestedTerms`, filters out person names, and displays.

### 2. Promotion today
- **Script:** `auto_curate_terms.py` runs after suggested-terms scan.
- **Logic:** Scores pending terms; if relevance + mentions + source diversity meet thresholds → **auto-promote to `definitions` table only**.
- **Overton Window:** Not used for promotion. `overton_terms` table exists but is populated by seed/migration, not by this pipeline.

### 3. Overton Window on the site
- **Rendering:** Fully **static HTML** in `index.html` (seven hardcoded `.overton-window-item` cards).
- **Data:** `get_main_page_content()` returns `definitions` and `overton` from the DB and they are in `dashboardData.mainContent`, but the site **never uses them**; the Overton section does not load from data.

---

## Target flow (fully functional)

1. **AI episode analysis** returns an array of **emerging terms** per episode (term + short definition + investment angle).
2. **Ingest** each term into `suggested_terms` (with episode/source context) so the **Emerging Terms** box is driven by AI output, not regex.
3. **Promotion:** When a suggested term is approved (auto or manual), add it to **both** `definitions` and **`overton_terms`** so it appears in the Overton Window.
4. **Site:** **Load Overton Window from data**: merge `mainContent.definitions` and `mainContent.overton` and render `.overton-window-item` cards from that list (with a fallback/empty state when no data).

---

## Implementation checklist

- [ ] **analyze_transcript.py:** Add `emerging_terms` to the AI JSON schema; in `process_transcript_file` ingest each into `suggested_terms` (same shape as existing pipeline: term, definition, investment_implications, source_context = episode).
- [ ] **auto_curate_terms.py:** When auto-promoting, insert into **overton_terms** as well as definitions (so promoted terms show in the Overton Window).
- [ ] **index.html:** Replace static Overton cards with a container; add `loadOvertonWindow()` that builds the list from `mainContent.definitions` + `mainContent.overton` and renders unified `.overton-window-item` cards; call on load and keep existing burst/expand behavior.

After this, Emerging Terms will be populated from the AI episode analysis response, and promoted terms will appear in the Overton Window and be driven by DB data.

# Emerging Terms — pipeline audit

## End-to-end flow

1. **Discovery (ingest)**  
   `analyze_transcript.py` reads AI JSON field `emerging_terms` and calls  
   `DashboardDB.upsert_suggested_term_from_ai()` → row in `suggested_terms` with  
   `status = 'pending'`, `source_type = 'auto_extracted'`.  
   `submitted_date` / `created_at` record when the row was first inserted.

2. **Promotion (Definitions / Overton)**  
   `auto_curate_terms.py` (auto pipeline) evaluates pending rows. If they meet thresholds  
   (or `manage_suggested_terms` / seeds), they can be **auto-promoted**: inserted into  
   `definitions` + `overton_terms`, and `suggested_terms.status` set to **`approved`**.  
   **`reviewed_at`** is set at promotion time.

3. **What the main page shows**  
   `export_data.py` → `get_suggested_terms_for_website(limit=4)` → embedded in  
   `data.js` as `dashboardData.suggestedTerms`.  
   **Only `status = 'pending'`** rows are eligible. Approved / rejected terms **do not**  
   appear in the Emerging Terms box (they live under Overton / Definitions instead).

4. **Why the box looked empty (fixed)**  
   - **Frontend**: A heuristic dropped any term with two Title-Case words (`Federal Reserve`,  
     `Democratic Party`, etc.), which removed **all** of the top exported rows.  
   - **Backend ordering**: The site now orders pending terms by **newest `submitted_date`  
     first**, then priority score, so fresh extractions surface in the box.

## Last 3 **new** terms (discovered = first insert)

From local `dashboard.db` at last audit (newest `id` / `submitted_date`):

| Term | First seen (`submitted_date`) | Status |
|------|-------------------------------|--------|
| Exponential Organizations | 2026-03-20 14:08:13 | pending |
| Adaptability | 2026-03-20 14:08:13 | pending |
| Generative Models | 2026-03-20 14:08:13 | pending |

(Re-run the SQL below after new analyses to refresh.)

## Last 3 **promoted** (approved → Definitions/Overton)

| Term | Submitted | Promoted (`reviewed_at`) |
|------|-----------|---------------------------|
| Strategic Oil Reserves | 2026-03-13 18:27:35 | 2026-03-13 18:28:26 |
| Renewable Energy Transition | 2026-03-13 18:27:35 | 2026-03-13 18:28:26 |
| Artificial General Intelligence (AGI) | 2026-03-13 18:27:45 | 2026-03-13 18:28:26 |

## Handy SQL

```sql
-- Newest discoveries (pending insert times)
SELECT id, term, status, submitted_date, mention_count, relevance_score
FROM suggested_terms
ORDER BY id DESC LIMIT 10;

-- Last promotions
SELECT id, term, submitted_date, reviewed_at, review_notes
FROM suggested_terms
WHERE status = 'approved' AND reviewed_at IS NOT NULL
ORDER BY reviewed_at DESC LIMIT 10;
```

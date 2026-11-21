-- Tony B, Fri Nov 20 2026 nightly batch (G g_fixes_2026-11-20 item b). Already run on the Mac DB after:
--   sqlite3 pipeline/dashboard.db ".backup ~/dashboard-db-backups/nightly_1120_pre_20261120_214939.db"
-- Entity 403 'Evan Baker' (ASR of Gavin Baker, All-In ep 405 Aug 14 2026) merged into existing entity 290 'Gavin Baker'.
BEGIN;
UPDATE appearances SET entity_id=290 WHERE entity_id=403;
DELETE FROM entities WHERE id=403;
INSERT OR REPLACE INTO person_aliases(alias, canonical_name, confidence, source) VALUES ('Evan Baker','Gavin Baker',1.0,'manual');
UPDATE entities SET updated_at=CURRENT_TIMESTAMP WHERE id=290;
COMMIT;
-- Also in the same batch: net_worth_usd/net_worth_source/net_worth_updated_at set NULL on the junk net-worth entities
-- (ids listed as pundit_overrides 'Nov 20 2026 (Jared decisions.md' in pipeline/summary_overrides.json).

-- Reviewed SQL for G's Nov 17 2026 daily site check.
-- DO NOT run on the live dashboard.db without Jared's yes and a backup
-- (copy to ~/dashboard-db-backups first). The nightly export already applies
-- these changes via pipeline/summary_overrides.json (pundit_overrides id 671
-- and net_worth unsets). This file is for a later, explicit DB cleanup only.

BEGIN;

-- 1) Entity 671 is stored as 'Alex E. Moss'. The a16z ep 685 guest (episode
--    title and card 275) is Alex Imas, a Google DeepMind economist.
--    Show notes: https://x.com/alexolegimas
UPDATE entities
   SET name = 'Alex Imas',
       slug = 'alex-imas',
       updated_at = CURRENT_TIMESTAMP
 WHERE id = 671
   AND name = 'Alex E. Moss';

INSERT INTO person_aliases (alias, canonical_name, confidence, source, updated_at)
SELECT 'Alex E. Moss', 'Alex Imas', 1.0, 'manual', CURRENT_TIMESTAMP
 WHERE NOT EXISTS (
    SELECT 1 FROM person_aliases
     WHERE alias = 'Alex E. Moss' AND canonical_name = 'Alex Imas'
 );

-- 2) Optional later cleanup: clear dead / wrong-person net-worth fields on
--    these entity rows. Export already drops them via pundit_overrides
--    (set net_worth_usd/source/updated_at empty; unset formatted net_worth).
--    Names on 123, 307, 308, and 364 are intentionally left unchanged;
--    G will send those corrections separately.
--    ids: 437 Ben Mildenhall (Jace Hall, 410),
--         364 Justin Jo ('JT', 410),
--         347 Clem Delangue (eboona 404),
--         308 John Mata (Juan Matas, 410),
--         307 Paul Beckas (Paul Boukadakis, 404),
--         123 Chandler Luzsicza (Christopher Chandler, 404),
--         260 Clem Delangue (Scott DeLong, wrong person),
--         163 Josh Shapiro (404),
--         158 Shyam Sankar (404),
--         281 Bill Maris (404),
--         282 Sachin Jain (404),
--         157 Trae Stephens (410).
UPDATE entities
   SET net_worth_usd = NULL,
       net_worth_source = NULL,
       net_worth_updated_at = NULL,
       updated_at = CURRENT_TIMESTAMP
 WHERE id IN (437, 364, 347, 308, 307, 123, 260, 163, 158, 281, 282, 157);

COMMIT;

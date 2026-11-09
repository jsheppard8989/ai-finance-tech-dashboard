# Trap Map retirement and private historical archive

The public Trap Map was retired on **2026-11-05**.

Historical records are preserved in the genuinely **private** repository
`jsheppard8989/dragonfly-private`, under `trap_map_archive_2026-11-05/`,
at commit `c7eff38e3dd022d066dba968cb9866d74022c9c9` (Nov 9, 2026 amendment: Healthcare Abundance basket closed at the HIMS Q3 subscriber stop with modeled session closes).
The ops-box copy is `/workspace/cos/trap_map_archive_2026-11-05`.

Nothing historical was deleted. The complete original archive, its rendered
outputs, source snapshots and original SHA-256 manifest were copied byte-for-byte
before removing the archive directory from the public repository's current branch.
`trap_map_archive_locator.json` contains location/checksum metadata only, never records.
The static public healthcare basket source remains unchanged as a frozen research record.

Public CI checks this locator and rejects archived record payloads in the public
checkout or Pages tree. It neither opens the private records nor accesses a private
network service. Local content tests use `TRAP_MAP_PRIVATE_ARCHIVE` (defaulting to
the ops-box path above) and explicitly skip private-record assertions when absent.
Use `python3 pipeline/trap_map_archive.py --check-private` locally to verify the
original manifest and every preserved file; the normal `--check` is public/offline-only.

## Public-history limitation
PR #767 briefly placed the archive in the public repository. Removing it from the
current branch does not remove earlier public commits or Git objects. No history
rewrite or force-push was performed; a true history purge requires separate explicit
approval. This document intentionally contains no record contents, marks or totals.

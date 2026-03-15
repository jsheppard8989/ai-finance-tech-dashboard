"""
Hard stop: do not download, analyze, or otherwise process anything older than Feb 2026.
Used by curate, fetch_latest, and analyze_transcript.
"""
# Episodes with published_date or episode_date before this are skipped everywhere.
CUTOFF_DATE_ISO = "2026-02-01"

def is_before_cutoff(published_date_str: str) -> bool:
    """True if the episode is before the cutoff (should be skipped)."""
    if not published_date_str or not isinstance(published_date_str, str):
        return False  # Unknown date: allow (or could treat as skip; we allow to avoid blocking)
    pub = (published_date_str.strip() or "")[:10]
    if len(pub) < 10:
        return False
    return pub < CUTOFF_DATE_ISO

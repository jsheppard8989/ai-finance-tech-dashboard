#!/usr/bin/env python3
"""Tests for spelling corrections from G (website admin).

These verify the term aliases correctly map misspellings to canonical names.
"""

import json
from pathlib import Path

import pytest

ALIASES_JSON = Path(__file__).parent / "term_aliases.json"


def test_term_aliases_json_is_valid():
    """term_aliases.json parses as valid JSON."""
    assert ALIASES_JSON.exists(), f"Missing {ALIASES_JSON}"
    data = json.loads(ALIASES_JSON.read_text(encoding="utf-8"))
    assert "merges" in data
    assert isinstance(data["merges"], list)


def test_armadin_alias_exists():
    """'Armored in' should map to 'Armadin' (Kevin Mandia's company)."""
    data = json.loads(ALIASES_JSON.read_text(encoding="utf-8"))
    merges = data.get("merges", [])
    armadin = next((m for m in merges if m.get("canonical") == "Armadin"), None)
    assert armadin is not None, "Missing Armadin entry in term_aliases.json"
    assert "Armored in" in armadin.get("aliases", []), "Missing 'Armored in' alias for Armadin"


def test_epoch_ai_alias_exists():
    """'Epic AI' should map to 'Epoch AI' (AI research group)."""
    data = json.loads(ALIASES_JSON.read_text(encoding="utf-8"))
    merges = data.get("merges", [])
    epoch = next((m for m in merges if m.get("canonical") == "Epoch AI"), None)
    assert epoch is not None, "Missing Epoch AI entry in term_aliases.json"
    assert "Epic AI" in epoch.get("aliases", []), "Missing 'Epic AI' alias for Epoch AI"


def test_jevons_paradox_alias_exists():
    """Jevons Paradox alias from #355 should still exist."""
    data = json.loads(ALIASES_JSON.read_text(encoding="utf-8"))
    merges = data.get("merges", [])
    jevons = next((m for m in merges if m.get("canonical") == "Jevons Paradox"), None)
    assert jevons is not None, "Missing Jevons Paradox entry in term_aliases.json"
    assert "Jevon's Paradox" in jevons.get("aliases", [])


def test_no_duplicate_canonicals():
    """Each canonical term should appear exactly once."""
    data = json.loads(ALIASES_JSON.read_text(encoding="utf-8"))
    merges = data.get("merges", [])
    canonicals = [m.get("canonical") for m in merges]
    seen = set()
    for c in canonicals:
        assert c not in seen, f"Duplicate canonical term: {c}"
        seen.add(c)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

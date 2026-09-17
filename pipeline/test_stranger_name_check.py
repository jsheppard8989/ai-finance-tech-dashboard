#!/usr/bin/env python3
"""
Unit tests for the stranger name-check heuristic in person_name_safety.py.

Tests the fails_stranger_name_check() function which detects ASR-garbage
speaker names while preserving real names.

Live ASR garbage examples from the site (as of Sep 2026):
- "Ruby J. To Low" (ASR for Ruby Justice Thelot)
- "NG ZDN" (all-caps letter salad)
- "Sly Miss Mail" (ASR garbage)
- "E-Modemoo" (nonsense compound)
- "Batuan Tashkaya" (known ASR error)
- "Alex Wees" (ASR variant of co-host)
"""

import pytest
from person_name_safety import (
    fails_stranger_name_check,
    sanitize_speaker_name_for_display,
)


class TestFailsStrangerNameCheck:
    """Test cases for fails_stranger_name_check()."""

    # === SHOULD FAIL (ASR garbage) ===

    def test_fails_empty_name(self):
        assert fails_stranger_name_check("") is True
        assert fails_stranger_name_check("   ") is True
        assert fails_stranger_name_check(None) is True  # type: ignore

    def test_fails_known_asr_garbage_ruby_to_low(self):
        """Ruby J. To Low is ASR for Ruby Justice Thelot."""
        assert fails_stranger_name_check("Ruby J. To Low") is True

    def test_fails_known_asr_garbage_ng_zdn(self):
        """NG ZDN is all-caps letter salad."""
        assert fails_stranger_name_check("NG ZDN") is True

    def test_fails_known_asr_garbage_sly_miss_mail(self):
        """Sly Miss Mail is ASR garbage."""
        assert fails_stranger_name_check("Sly Miss Mail") is True

    def test_fails_known_asr_garbage_e_modemoo(self):
        """E-Modemoo is nonsense compound."""
        assert fails_stranger_name_check("E-Modemoo") is True
        assert fails_stranger_name_check("E Modemoo") is True
        assert fails_stranger_name_check("E-Modemustock") is True

    def test_fails_known_asr_garbage_batuan_tashkaya(self):
        """Batuan Tashkaya is a known ASR error (a16z video)."""
        assert fails_stranger_name_check("Batuan Tashkaya") is True

    def test_fails_known_asr_garbage_alex_wees(self):
        """Alex Wees is ASR variant of Alex Wissner-Gross (co-host)."""
        assert fails_stranger_name_check("Alex Wees") is True

    def test_fails_all_caps_letter_salad(self):
        """All-caps short tokens indicate letter salad."""
        assert fails_stranger_name_check("ABC XYZ") is True
        assert fails_stranger_name_check("XY ZW") is True

    def test_fails_mid_name_glue_words(self):
        """Mid-name English glue words like 'To', 'Of', 'The' are suspicious."""
        assert fails_stranger_name_check("John To Smith") is True
        assert fails_stranger_name_check("Jane Of Doe") is True
        assert fails_stranger_name_check("Mike The Guy") is True
        assert fails_stranger_name_check("Bob And Sue") is True

    def test_fails_single_token(self):
        """Single-token names fail (already covered by is_placeholder_person_name)."""
        assert fails_stranger_name_check("Madonna") is True
        assert fails_stranger_name_check("Prince") is True

    def test_fails_hyphenated_nonsense(self):
        """Single letter hyphen prefix followed by gibberish fails."""
        assert fails_stranger_name_check("A-Blahblah") is True
        assert fails_stranger_name_check("X-Randomoo") is True

    def test_fails_triple_repeated_letters(self):
        """Triple+ repeated letters are rare in real names."""
        assert fails_stranger_name_check("John Smiiith") is True
        assert fails_stranger_name_check("Jannne Doe") is True

    def test_fails_unusual_token_endings(self):
        """Unusual endings like 'emoo', 'ezoo' suggest ASR errors."""
        assert fails_stranger_name_check("John Modemoo") is True

    # === SHOULD PASS (real names) ===

    def test_passes_normal_first_last(self):
        """Normal First Last names should pass."""
        assert fails_stranger_name_check("Joseph Wang") is False
        assert fails_stranger_name_check("John Smith") is False
        assert fails_stranger_name_check("Jane Doe") is False

    def test_passes_alfonso_peccatiello(self):
        """Alfonso Peccatiello is a real pundit name."""
        assert fails_stranger_name_check("Alfonso Peccatiello") is False

    def test_passes_hyphenated_surnames(self):
        """Known hyphenated surnames should pass."""
        assert fails_stranger_name_check("Alex Wissner-Gross") is False
        assert fails_stranger_name_check("Mary Smith-Jones") is False

    def test_passes_names_with_particles(self):
        """Names with known particles (van, von, de) should pass."""
        assert fails_stranger_name_check("Ludwig van Beethoven") is False
        assert fails_stranger_name_check("Jean de la Fontaine") is False
        assert fails_stranger_name_check("Werner von Braun") is False

    def test_passes_names_with_initials(self):
        """Names with middle initials should pass."""
        assert fails_stranger_name_check("John F. Kennedy") is False
        assert fails_stranger_name_check("George W. Bush") is False
        assert fails_stranger_name_check("Franklin D. Roosevelt") is False

    def test_passes_names_with_suffixes(self):
        """Names with Jr., Sr., III should pass."""
        assert fails_stranger_name_check("Martin Luther King Jr.") is False
        assert fails_stranger_name_check("Robert Downey Jr") is False

    def test_passes_common_pundits(self):
        """Common pundit names from the site should pass."""
        assert fails_stranger_name_check("Peter Diamandis") is False
        assert fails_stranger_name_check("Marc Andreessen") is False
        assert fails_stranger_name_check("Ben Horowitz") is False
        assert fails_stranger_name_check("David Sacks") is False

    def test_passes_curated_source_names(self):
        """Names from curated_sources.json should pass."""
        assert fails_stranger_name_check("Eric Topol") is False
        assert fails_stranger_name_check("Derek Lowe") is False
        assert fails_stranger_name_check("Jim Bianco") is False
        assert fails_stranger_name_check("Luke Gromen") is False
        assert fails_stranger_name_check("Michael Howell") is False
        assert fails_stranger_name_check("Dario Perkins") is False
        assert fails_stranger_name_check("Sam Rines") is False
        assert fails_stranger_name_check("Adam Feuerstein") is False
        assert fails_stranger_name_check("Matthew Herper") is False
        assert fails_stranger_name_check("George Goncalves") is False
        assert fails_stranger_name_check("Andy Constan") is False

    def test_passes_ruby_justice_thelot(self):
        """Ruby Justice Thelot is a real person (corrected from ASR)."""
        assert fails_stranger_name_check("Ruby Justice Thelot") is False

    def test_passes_three_part_names(self):
        """Three-part names without glue words should pass."""
        assert fails_stranger_name_check("Mary Jane Watson") is False
        assert fails_stranger_name_check("Sarah Michelle Gellar") is False

    def test_passes_names_with_apostrophes(self):
        """Names with apostrophes (O'Brien) should pass."""
        assert fails_stranger_name_check("Conan O'Brien") is False
        assert fails_stranger_name_check("Eugene O'Neill") is False


class TestSanitizeSpeakerNameForDisplay:
    """Test cases for sanitize_speaker_name_for_display()."""

    def test_returns_name_if_passes(self):
        assert sanitize_speaker_name_for_display("Joseph Wang") == "Joseph Wang"
        assert sanitize_speaker_name_for_display("Alfonso Peccatiello") == "Alfonso Peccatiello"

    def test_returns_empty_if_fails(self):
        assert sanitize_speaker_name_for_display("Ruby J. To Low") == ""
        assert sanitize_speaker_name_for_display("NG ZDN") == ""
        assert sanitize_speaker_name_for_display("E-Modemoo") == ""

    def test_returns_empty_for_empty_input(self):
        assert sanitize_speaker_name_for_display("") == ""
        assert sanitize_speaker_name_for_display("   ") == ""

    def test_normalizes_whitespace(self):
        assert sanitize_speaker_name_for_display("Joseph  Wang") == "Joseph Wang"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

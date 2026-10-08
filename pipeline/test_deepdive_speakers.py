#!/usr/bin/env python3
"""Tests for deep dive speaker extraction functions."""

import pytest


class TestExtractHostFromSourceName:
    """Test _extract_host_from_source_name helper."""

    def test_extracts_host_with_simple_name(self):
        from generate_deepdives import _extract_host_from_source_name
        assert _extract_host_from_source_name("Monetary Matters with Jack Farley") == "Jack Farley"

    def test_extracts_host_with_apostrophe_in_name(self):
        from generate_deepdives import _extract_host_from_source_name
        assert _extract_host_from_source_name("Invest Like the Best with Patrick O'Shaughnessy") == "Patrick O'Shaughnessy"

    def test_returns_none_for_no_host_pattern(self):
        from generate_deepdives import _extract_host_from_source_name
        assert _extract_host_from_source_name("All-In Podcast") is None
        assert _extract_host_from_source_name("The Tim Ferriss Show") is None

    def test_returns_none_for_empty_input(self):
        from generate_deepdives import _extract_host_from_source_name
        assert _extract_host_from_source_name("") is None
        assert _extract_host_from_source_name(None) is None


class TestExtractSpeakersFromNotableQuotes:
    """Test _extract_speakers_from_notable_quotes helper."""

    def test_extracts_single_speaker(self):
        from generate_deepdives import _extract_speakers_from_notable_quotes
        quotes = '[{"speaker": "J Mintzmyer", "quote": "The oil must flow."}]'
        assert _extract_speakers_from_notable_quotes(quotes) == ["J Mintzmyer"]

    def test_extracts_multiple_speakers(self):
        from generate_deepdives import _extract_speakers_from_notable_quotes
        quotes = '[{"speaker": "Guest A", "quote": "one"}, {"speaker": "Guest B", "quote": "two"}]'
        assert _extract_speakers_from_notable_quotes(quotes) == ["Guest A", "Guest B"]

    def test_deduplicates_speakers(self):
        from generate_deepdives import _extract_speakers_from_notable_quotes
        quotes = '[{"speaker": "J Mintzmyer", "quote": "one"}, {"speaker": "J Mintzmyer", "quote": "two"}]'
        assert _extract_speakers_from_notable_quotes(quotes) == ["J Mintzmyer"]

    def test_returns_empty_for_invalid_json(self):
        from generate_deepdives import _extract_speakers_from_notable_quotes
        assert _extract_speakers_from_notable_quotes("not json") == []
        assert _extract_speakers_from_notable_quotes("") == []
        assert _extract_speakers_from_notable_quotes(None) == []

    def test_returns_empty_for_missing_speaker_field(self):
        from generate_deepdives import _extract_speakers_from_notable_quotes
        quotes = '[{"quote": "no speaker field"}]'
        assert _extract_speakers_from_notable_quotes(quotes) == []


class TestDeepDiveStructuralOk:
    """Test deep_dive_structural_ok regex for speaker names."""

    def test_matches_single_letter_first_name(self):
        """Speaker names like 'J Mintzmyer' should be recognized."""
        from generate_deepdives import deep_dive_structural_ok
        
        content = {
            "episode_evidence": '''J Mintzmyer: "The oil must flow and this is a longer quote."
J Mintzmyer: "This is another quote with sufficient length."
J Mintzmyer: "And a third quote that is also reasonably long."''',
            "overview": "This is a sufficiently long overview with enough content to pass the length check for validation and contains meaningful content about the topic.",
            "investment_thesis": "This is a sufficiently long investment thesis to pass validation and explains the investment case clearly.",
            "falsification_tracks": [
                "If tanker rates fall below $50,000 per day by Q2 2027, the thesis would be invalidated",
                "If China reduces crude imports by more than 15% this year, demand would collapse",
                "If new VLCC deliveries exceed 50 ships in 2027, supply would overwhelm demand"
            ],
        }
        ok, reason = deep_dive_structural_ok(content)
        assert ok, f"Should pass with single-letter first name, but got: {reason}"

    def test_matches_full_names(self):
        """Normal speaker names like 'Jack Farley' should be recognized."""
        from generate_deepdives import deep_dive_structural_ok
        
        content = {
            "episode_evidence": '''Jack Farley: "Question from the host about market dynamics."
Patrick O'Shaughnessy: "Another named quote with substantial content."''',
            "overview": "This is a sufficiently long overview with enough content to pass the length check for validation and contains meaningful content about the topic.",
            "investment_thesis": "This is a sufficiently long investment thesis to pass validation and explains the investment case clearly.",
            "falsification_tracks": [
                "If the Federal Reserve cuts rates by more than 100bps, the thesis would need revision",
                "If inflation exceeds 5% by end of year, the market outlook changes significantly",
                "If earnings growth falls below 10% for the sector, valuations become stretched"
            ],
        }
        ok, reason = deep_dive_structural_ok(content)
        assert ok, f"Should pass with full names, but got: {reason}"

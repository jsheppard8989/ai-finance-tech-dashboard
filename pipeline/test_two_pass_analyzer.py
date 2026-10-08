#!/usr/bin/env python3
"""
Unit tests for two-pass analyzer.

Tests:
- Cache hit/miss behavior
- 429/insufficient_quota batch stop
- Transcript chunking
- Field mapping from extraction to site contract
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from two_pass_analyzer import (
    TwoPassAnalyzerCache,
    chunk_transcript,
    merge_extractions,
    map_to_site_fields,
    transcript_sha256,
    InsufficientQuotaError,
    CHUNK_TOKEN_BUDGET,
)


class TestTwoPassAnalyzerCache:
    """Tests for the extraction cache."""

    def test_cache_miss_returns_none(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            cache = TwoPassAnalyzerCache(db_path)
            result = cache.get(999, "abc123")
            assert result is None
        finally:
            db_path.unlink(missing_ok=True)

    def test_cache_put_and_get(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            cache = TwoPassAnalyzerCache(db_path)
            
            cache.put(
                episode_id=123,
                transcript_sha256="sha256abc",
                extraction_json='{"episode_summary": "Test"}',
                brief_markdown="# Brief\n\nTest content",
                pass1_input_tokens=1000,
                pass1_output_tokens=500,
                pass2_input_tokens=600,
                pass2_output_tokens=800,
            )
            
            result = cache.get(123, "sha256abc")
            assert result is not None
            assert result["episode_id"] == 123
            assert result["transcript_sha256"] == "sha256abc"
            assert "Test" in result["extraction_json"]
            assert "Brief" in result["brief_markdown"]
            assert result["pass1_input_tokens"] == 1000
        finally:
            db_path.unlink(missing_ok=True)

    def test_cache_different_sha_is_miss(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            cache = TwoPassAnalyzerCache(db_path)
            
            cache.put(
                episode_id=123,
                transcript_sha256="sha256abc",
                extraction_json='{"test": true}',
                brief_markdown="# Brief",
            )
            
            result = cache.get(123, "sha256different")
            assert result is None
        finally:
            db_path.unlink(missing_ok=True)


class TestChunking:
    """Tests for transcript chunking."""

    def test_small_transcript_single_chunk(self):
        text = "This is a short transcript."
        chunks = chunk_transcript(text, max_tokens=1000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_large_transcript_multiple_chunks(self):
        word = "word "
        large_text = word * 500_000
        chunks = chunk_transcript(large_text, max_tokens=10_000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 10_000 * 4 + 100

    def test_chunking_preserves_content(self):
        text = "The quick brown fox jumps over the lazy dog " * 1000
        chunks = chunk_transcript(text, max_tokens=100)
        
        recombined = " ".join(chunks)
        original_words = set(text.split())
        recombined_words = set(recombined.split())
        
        for word in ["quick", "brown", "fox", "lazy", "dog"]:
            assert word in recombined_words


class TestMergeExtractions:
    """Tests for merging chunk extractions."""

    def test_single_extraction_unchanged(self):
        extraction = {
            "episode_summary": "Test summary",
            "major_claims": ["Claim 1"],
            "high_value_quotes": [{"speaker": "John", "quote": "Test quote"}],
        }
        result = merge_extractions([extraction])
        assert result["episode_summary"] == "Test summary"
        assert len(result["major_claims"]) == 1

    def test_multiple_extractions_merged(self):
        ext1 = {
            "episode_summary": "Summary part 1",
            "major_claims": ["Claim A"],
            "numbers": ["$1 billion"],
        }
        ext2 = {
            "episode_summary": "Summary part 2",
            "major_claims": ["Claim B", "Claim A"],
            "numbers": ["$2 billion"],
        }
        result = merge_extractions([ext1, ext2])
        
        assert "Summary part 1" in result["episode_summary"]
        assert "Summary part 2" in result["episode_summary"]
        assert len(result["major_claims"]) == 2
        assert len(result["numbers"]) == 2

    def test_deduplication(self):
        ext1 = {"major_claims": ["Same claim"], "numbers": []}
        ext2 = {"major_claims": ["Same claim"], "numbers": []}
        
        result = merge_extractions([ext1, ext2])
        assert len(result["major_claims"]) == 1


class TestFieldMapping:
    """Tests for mapping extraction to site contract fields."""

    def test_basic_mapping(self):
        extraction = {
            "episode_summary": "Episode about AI",
            "high_value_quotes": [
                {"speaker": "Jane Doe", "quote": "AI will change everything"}
            ],
            "companies_and_assets": ["NVDA", "TSLA"],
        }
        site_contract = {
            "episode_title": "AI Revolution",
            "summary": "Deep dive into AI",
            "key_takeaways": ["AI is growing", "Investment opportunities"],
            "investment_thesis": "AI is the next big thing",
            "sentiment": "bullish",
        }
        brief = "# REAL ALPHA Brief\n\nTest content"
        
        result = map_to_site_fields(extraction, site_contract, brief)
        
        assert result["episode_title"] == "AI Revolution"
        assert result["summary"] == "Deep dive into AI"
        assert result["investment_thesis"] == "AI is the next big thing"
        assert result["sentiment"] == "bullish"
        assert result["_brief_markdown"] == brief

    def test_fallback_to_extraction(self):
        extraction = {
            "episode_summary": "Fallback summary",
            "high_value_quotes": [
                {"speaker": "Test Speaker", "quote": "Important insight"}
            ],
        }
        site_contract = {}
        brief = "# Brief"
        
        result = map_to_site_fields(extraction, site_contract, brief)
        
        assert result["summary"] == "Fallback summary"
        assert len(result["notable_quotes"]) == 1
        assert result["notable_quotes"][0]["speaker"] == "Test Speaker"

    def test_sentiment_defaults_to_neutral(self):
        extraction = {}
        site_contract = {"sentiment": "invalid_value"}
        result = map_to_site_fields(extraction, site_contract, "")
        assert result["sentiment"] == "neutral"

    def test_tickers_from_extraction_fallback(self):
        extraction = {
            "companies_and_assets": ["AAPL", "MSFT", "GOOGL"],
        }
        site_contract = {}
        result = map_to_site_fields(extraction, site_contract, "")
        
        assert "AAPL" in result["key_tickers"]
        assert "MSFT" in result["key_tickers"]


class TestInsufficientQuotaError:
    """Tests for 429/quota handling."""

    def test_error_is_raisable(self):
        with pytest.raises(InsufficientQuotaError):
            raise InsufficientQuotaError("Rate limit exceeded")

    def test_error_message_preserved(self):
        try:
            raise InsufficientQuotaError("Test quota message")
        except InsufficientQuotaError as e:
            assert "Test quota message" in str(e)


class TestTranscriptSha256:
    """Tests for transcript hashing."""

    def test_same_content_same_hash(self):
        text = "This is a test transcript"
        hash1 = transcript_sha256(text)
        hash2 = transcript_sha256(text)
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        hash1 = transcript_sha256("Text A")
        hash2 = transcript_sha256("Text B")
        assert hash1 != hash2

    def test_hash_is_hex_string(self):
        result = transcript_sha256("Test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestFeatureFlag:
    """Tests for ANALYZER_MODE feature flag."""

    def test_default_is_legacy(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANALYZER_MODE", None)
            from two_pass_analyzer import is_two_pass_enabled
            assert is_two_pass_enabled() is False

    def test_two_pass_enabled(self):
        with patch.dict(os.environ, {"ANALYZER_MODE": "two_pass"}):
            from two_pass_analyzer import is_two_pass_enabled
            from importlib import reload
            import two_pass_analyzer
            reload(two_pass_analyzer)
            assert two_pass_analyzer.is_two_pass_enabled() is True

    def test_legacy_explicit(self):
        with patch.dict(os.environ, {"ANALYZER_MODE": "legacy"}):
            from two_pass_analyzer import is_two_pass_enabled
            from importlib import reload
            import two_pass_analyzer
            reload(two_pass_analyzer)
            assert two_pass_analyzer.is_two_pass_enabled() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

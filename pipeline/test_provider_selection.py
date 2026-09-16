"""Tests for get_ai_client() provider selection logic.

These tests verify:
1. Default priority order (Gemini -> OpenAI -> Moonshot) when ANALYZE_BACKEND is not set
2. Explicit provider selection via ANALYZE_BACKEND
3. ProviderKeyMissingError when explicit provider key is missing (no fallback)
4. Invalid ANALYZE_BACKEND value raises ProviderKeyMissingError

No actual API keys or credentials are used; tests mock the environment.
"""

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

try:
    import google.generativeai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


def test_explicit_gemini_missing_key_raises():
    """ANALYZE_BACKEND=gemini without GEMINI_API_KEY raises ProviderKeyMissingError."""
    from analyze_transcript import get_ai_client, ProviderKeyMissingError

    env = {"ANALYZE_BACKEND": "gemini"}
    with mock.patch.dict(os.environ, env, clear=True):
        try:
            get_ai_client()
            assert False, "Expected ProviderKeyMissingError"
        except ProviderKeyMissingError as e:
            assert "GEMINI_API_KEY" in str(e)
            assert "gemini" in str(e).lower()


def test_explicit_openai_missing_key_raises():
    """ANALYZE_BACKEND=openai without OPENAI_API_KEY raises ProviderKeyMissingError."""
    from analyze_transcript import get_ai_client, ProviderKeyMissingError

    env = {"ANALYZE_BACKEND": "openai"}
    with mock.patch.dict(os.environ, env, clear=True):
        try:
            get_ai_client()
            assert False, "Expected ProviderKeyMissingError"
        except ProviderKeyMissingError as e:
            assert "OPENAI_API_KEY" in str(e)
            assert "openai" in str(e).lower()


def test_explicit_moonshot_missing_key_raises():
    """ANALYZE_BACKEND=moonshot without MOONSHOT_API_KEY raises ProviderKeyMissingError."""
    from analyze_transcript import get_ai_client, ProviderKeyMissingError

    env = {"ANALYZE_BACKEND": "moonshot"}
    with mock.patch.dict(os.environ, env, clear=True):
        try:
            get_ai_client()
            assert False, "Expected ProviderKeyMissingError"
        except ProviderKeyMissingError as e:
            assert "MOONSHOT_API_KEY" in str(e)
            assert "moonshot" in str(e).lower()


def test_invalid_analyze_backend_raises():
    """ANALYZE_BACKEND set to invalid value raises ProviderKeyMissingError."""
    from analyze_transcript import get_ai_client, ProviderKeyMissingError

    env = {"ANALYZE_BACKEND": "unsupported_provider"}
    with mock.patch.dict(os.environ, env, clear=True):
        try:
            get_ai_client()
            assert False, "Expected ProviderKeyMissingError"
        except ProviderKeyMissingError as e:
            assert "unsupported_provider" in str(e)
            assert "not a valid provider" in str(e)


def test_no_override_no_keys_returns_none():
    """No ANALYZE_BACKEND and no keys returns None (no exception)."""
    from analyze_transcript import get_ai_client

    env = {}
    with mock.patch.dict(os.environ, env, clear=True):
        result = get_ai_client()
        assert result is None


def test_default_priority_gemini_first():
    """Without ANALYZE_BACKEND, Gemini is tried before OpenAI when both keys exist.
    
    This test mocks the client initialization to verify call order.
    Skipped if google-generativeai is not installed.
    """
    if not GEMINI_AVAILABLE:
        print("  (skipped: google-generativeai not installed)")
        return
        
    from analyze_transcript import get_ai_client

    init_order = []

    def mock_genai_configure(api_key):
        init_order.append("gemini")

    env = {"GEMINI_API_KEY": "fake-gemini-key", "OPENAI_API_KEY": "fake-openai-key"}
    
    with mock.patch.dict(os.environ, env, clear=True):
        import google.generativeai as genai
        with mock.patch.object(genai, 'configure', mock_genai_configure):
            result = get_ai_client()
            assert result is not None
            assert result[0] == "gemini"
            assert "gemini" in init_order


def test_explicit_openai_with_key_succeeds():
    """ANALYZE_BACKEND=openai with OPENAI_API_KEY succeeds.
    
    Skipped if openai library is not installed.
    """
    if not OPENAI_AVAILABLE:
        print("  (skipped: openai not installed)")
        return
        
    from analyze_transcript import get_ai_client

    env = {"ANALYZE_BACKEND": "openai", "OPENAI_API_KEY": "fake-openai-key"}
    with mock.patch.dict(os.environ, env, clear=True):
        result = get_ai_client()
        assert result is not None
        assert result[0] == "openai"


def test_explicit_gemini_with_key_succeeds():
    """ANALYZE_BACKEND=gemini with GEMINI_API_KEY succeeds.
    
    Skipped if google-generativeai is not installed.
    """
    if not GEMINI_AVAILABLE:
        print("  (skipped: google-generativeai not installed)")
        return
        
    from analyze_transcript import get_ai_client

    env = {"ANALYZE_BACKEND": "gemini", "GEMINI_API_KEY": "fake-gemini-key"}
    with mock.patch.dict(os.environ, env, clear=True):
        result = get_ai_client()
        assert result is not None
        assert result[0] == "gemini"


def test_explicit_provider_no_fallback():
    """ANALYZE_BACKEND=gemini with missing key does NOT fall back to OpenAI."""
    from analyze_transcript import get_ai_client, ProviderKeyMissingError

    env = {"ANALYZE_BACKEND": "gemini", "OPENAI_API_KEY": "fake-openai-key"}
    with mock.patch.dict(os.environ, env, clear=True):
        try:
            get_ai_client()
            assert False, "Expected ProviderKeyMissingError, should NOT fall back to OpenAI"
        except ProviderKeyMissingError as e:
            assert "GEMINI_API_KEY" in str(e)


if __name__ == "__main__":
    test_explicit_gemini_missing_key_raises()
    print("✓ test_explicit_gemini_missing_key_raises")
    
    test_explicit_openai_missing_key_raises()
    print("✓ test_explicit_openai_missing_key_raises")
    
    test_explicit_moonshot_missing_key_raises()
    print("✓ test_explicit_moonshot_missing_key_raises")
    
    test_invalid_analyze_backend_raises()
    print("✓ test_invalid_analyze_backend_raises")
    
    test_no_override_no_keys_returns_none()
    print("✓ test_no_override_no_keys_returns_none")
    
    test_default_priority_gemini_first()
    print("✓ test_default_priority_gemini_first")
    
    test_explicit_openai_with_key_succeeds()
    print("✓ test_explicit_openai_with_key_succeeds")
    
    test_explicit_gemini_with_key_succeeds()
    print("✓ test_explicit_gemini_with_key_succeeds")
    
    test_explicit_provider_no_fallback()
    print("✓ test_explicit_provider_no_fallback")
    
    print("\nAll provider selection tests passed!")

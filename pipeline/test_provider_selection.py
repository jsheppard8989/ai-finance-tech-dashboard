#!/usr/bin/env python3
"""Tests for podcast analyzer provider selection logic (ANALYZE_BACKEND)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import importlib


def _reload_module():
    """Reload analyze_transcript to pick up env changes."""
    import analyze_transcript
    importlib.reload(analyze_transcript)
    return analyze_transcript


class TestProviderSelection(unittest.TestCase):
    """Test ANALYZE_BACKEND provider selection and error handling."""

    def setUp(self):
        self.env_backup = {}
        for key in (
            "ANALYZE_BACKEND",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "MOONSHOT_API_KEY",
            "CURSOR_AGENT_AUTH_PROFILES_PATH",
        ):
            self.env_backup[key] = os.environ.get(key)
            if key in os.environ:
                del os.environ[key]

    def tearDown(self):
        for key, val in self.env_backup.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_explicit_openai_requires_key(self):
        """When ANALYZE_BACKEND=openai but no key, raises ProviderKeyMissingError."""
        os.environ["ANALYZE_BACKEND"] = "openai"
        mod = _reload_module()
        with self.assertRaises(mod.ProviderKeyMissingError) as ctx:
            mod.get_ai_client()
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_explicit_gemini_requires_key(self):
        """When ANALYZE_BACKEND=gemini but no key, raises ProviderKeyMissingError."""
        os.environ["ANALYZE_BACKEND"] = "gemini"
        mod = _reload_module()
        with self.assertRaises(mod.ProviderKeyMissingError) as ctx:
            mod.get_ai_client()
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def test_explicit_moonshot_requires_key(self):
        """When ANALYZE_BACKEND=moonshot but no key, raises ProviderKeyMissingError."""
        os.environ["ANALYZE_BACKEND"] = "moonshot"
        mod = _reload_module()
        with self.assertRaises(mod.ProviderKeyMissingError) as ctx:
            mod.get_ai_client()
        self.assertIn("MOONSHOT_API_KEY", str(ctx.exception))

    def test_auto_mode_returns_none_when_no_keys(self):
        """In auto mode (ANALYZE_BACKEND unset) with no keys, returns None."""
        mod = _reload_module()
        result = mod.get_ai_client()
        self.assertIsNone(result)


class TestProviderKeyMissingErrorMessage(unittest.TestCase):
    """Test that error messages are helpful for production debugging."""

    def setUp(self):
        self.env_backup = {}
        for key in (
            "ANALYZE_BACKEND",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "MOONSHOT_API_KEY",
            "CURSOR_AGENT_AUTH_PROFILES_PATH",
        ):
            self.env_backup[key] = os.environ.get(key)
            if key in os.environ:
                del os.environ[key]

    def tearDown(self):
        for key, val in self.env_backup.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_openai_error_mentions_env_var(self):
        """OpenAI missing-key error clearly states which env var to set."""
        os.environ["ANALYZE_BACKEND"] = "openai"
        mod = _reload_module()
        try:
            mod.get_ai_client()
            self.fail("Expected ProviderKeyMissingError")
        except mod.ProviderKeyMissingError as e:
            msg = str(e)
            self.assertIn("OPENAI_API_KEY", msg)

    def test_gemini_error_mentions_env_var(self):
        """Gemini missing-key error clearly states which env var to set."""
        os.environ["ANALYZE_BACKEND"] = "gemini"
        mod = _reload_module()
        try:
            mod.get_ai_client()
            self.fail("Expected ProviderKeyMissingError")
        except mod.ProviderKeyMissingError as e:
            msg = str(e)
            self.assertIn("GEMINI_API_KEY", msg)

    def test_moonshot_error_mentions_both_options(self):
        """Moonshot missing-key error mentions both env var and auth profiles."""
        os.environ["ANALYZE_BACKEND"] = "moonshot"
        mod = _reload_module()
        try:
            mod.get_ai_client()
            self.fail("Expected ProviderKeyMissingError")
        except mod.ProviderKeyMissingError as e:
            msg = str(e)
            self.assertIn("MOONSHOT_API_KEY", msg)
            self.assertIn("auth profiles", msg)


if __name__ == "__main__":
    unittest.main()

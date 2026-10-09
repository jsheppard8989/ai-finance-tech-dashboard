"""
Shared pytest fixtures for pipeline tests.

Every test runs with fetch_cot / fetch_curve / fetch_treasury_calendar state and
market_data paths redirected to a per-test tmp dir, so tests can never touch the
real pipeline/state/ or site/data/ files (root cause of the Oct 8 2026 COT
fixture leak into cot_prior_nets.json).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _isolate_pipeline_state(tmp_path, monkeypatch):
    state = tmp_path / "state"
    site_data = tmp_path / "site_data"
    state.mkdir()
    site_data.mkdir()
    for modname, attrs in {
        "fetch_cot": {"STATE_DIR": state,
                      "COT_PRIOR_NETS_FILE": state / "cot_prior_nets.json",
                      "MARKET_DATA_FILE": site_data / "market_data.json"},
        "fetch_curve": {"MARKET_DATA_FILE": site_data / "market_data.json"},
        "fetch_treasury_calendar": {"MARKET_DATA_FILE": site_data / "market_data.json"},
    }.items():
        mod = sys.modules.get(modname)
        if mod is None:
            try:
                mod = __import__(modname)
            except Exception:
                continue
        for attr, val in attrs.items():
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, val)
    yield

"""Retirement preserves record integrity and blocks accidental public resurrection."""
import hashlib
import json
import shutil
from pathlib import Path
from unittest import mock
import pytest
import build_trap_map as build
import publish_guard

ROOT = Path(__file__).resolve().parent.parent
from trap_map_archive import ARCHIVE
from trap_map_test_support import private_archive


def test_archive_is_complete_and_hashed():
    private_archive()  # Historical contents are optional local fixtures, never public CI inputs.
    manifest = json.loads((ARCHIVE / "manifest.json").read_text())
    assert manifest["retired_date_CT"] == "2026-11-05"
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest
    d = json.loads((ARCHIVE / "trap_map.json").read_text())
    assert len(d["rows"]) == 8
    assert len([r for r in d["rows"] if r["status"] != "closed"]) == 6
    assert d["totals"]["realized_change"] == -1758.34
    assert d["totals"]["portfolio_value"] == 44417.08
    assert {r["id"]: r["exit"]["result"] for r in d["rows"] if r["status"] == "closed"} == {"lrcx-put": -1043.33, "ceg-q3": -715.01}
    assert (ARCHIVE / "index.html").is_file()
    assert (ARCHIVE / "trap-map.html").is_file()
    assert len(list((ARCHIVE / "sources").glob("*.snapshot"))) >= 5


def test_no_public_surface_or_reference():
    assert not (ROOT / "site/trap-map.html").exists()
    assert not (ROOT / "site/data/trap_map.json").exists()
    for path in (ROOT / "site").rglob("*"):
        if path.is_file() and path.suffix in (".html", ".js", ".json", ".css", ".xml", ".txt"):
            text = path.read_text(errors="replace").lower()
            assert "trap-map.html" not in text, path
            assert "trap_map.json" not in text, path
            assert "trap-map-strip" not in text, path
    for name in ("mu-memory-cycle.html", "healthcare.html", "power-bottleneck.html", "lrcx-paid-to-wait.html"):
        assert (ROOT / "site" / name).is_file()


def test_build_defaults_are_archive_only_and_public_overrides_refused():
    assert build.DATA == ARCHIVE / "trap_map.json"
    assert build.PAGE == ARCHIVE / "trap-map.html"
    assert build.INDEX == ARCHIVE / "index.html"
    with pytest.raises(ValueError, match="retired"):
        build.build(write=False, page_path=ROOT / "site/trap-map.html")


def test_private_build_outputs_are_reproducible():
    private_archive()
    assert build.build(write=False) == []


def test_market_workflow_keeps_other_refreshes_without_retired_pull():
    workflow = (ROOT / ".github/workflows/market-data.yml").read_text()
    for script in ("fetch_gpu_index.py", "fetch_compute_curve.py", "fetch_treasury_calendar.py"):
        assert script in workflow
    assert "fetch_trap_map_prices.py" not in workflow
    assert "steps.trap_map.outcome" not in workflow
    assert 'TRAP="' not in workflow
    assert "site/data/market_data.json" in workflow and "gh workflow run deploy.yml" in workflow
    deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "trap_map_archive.py" in deploy
    assert "build_trap_map.py --check" not in deploy


def test_missing_private_archive_locator_blocks_publish(tmp_path):
    site, pipeline = tmp_path / "site", tmp_path / "pipeline"
    site.mkdir(); pipeline.mkdir()
    errors = publish_guard.check_trap_map(site, pipeline, {})
    assert any("locator" in e.lower() for e in errors)


def public_fixture(tmp_path):
    repo = tmp_path / "public"
    site, pipeline = repo / "site", repo / "pipeline"
    (site / "data").mkdir(parents=True)
    pipeline.mkdir()
    for name in ("TRAP_MAP_RETIREMENT.md", "trap_map_archive_locator.json"):
        shutil.copyfile(ROOT / "pipeline" / name, pipeline / name)
    shutil.copyfile(ROOT / "site/data/portfolio.json", site / "data/portfolio.json")
    return site, pipeline


def test_public_locator_guard_detects_public_links_without_private_records(tmp_path):
    site, pipeline = public_fixture(tmp_path)
    assert publish_guard.check_trap_map(site, pipeline, {}) == []
    (site / "index.html").write_text('<a href="trap-map.html">old</a>')
    assert any("public" in e.lower() for e in publish_guard.check_trap_map(site, pipeline, {}))


def test_optional_local_archive_guard_still_detects_record_corruption(tmp_path):
    from trap_map_archive import check_archive
    archive = tmp_path / "local-private-fixture"
    shutil.copytree(private_archive(), archive)
    assert check_archive(archive) == []
    (archive / "trap_map.json").write_text('{}')
    assert any("archive" in e.lower() for e in check_archive(archive))


def test_retired_price_cli_cannot_refresh_the_snapshot():
    import fetch_trap_map_prices as prices
    with mock.patch.object(prices, "pull", side_effect=AssertionError("retired CLI must not pull quotes")):
        with pytest.raises(SystemExit, match="retired"):
            prices.main()


def test_public_essays_are_historical_paper_only_not_live_marks():
    for name in ("mu-memory-cycle.html", "healthcare.html", "power-bottleneck.html", "lrcx-paid-to-wait.html"):
        text = (ROOT / "site" / name).read_text()
        assert "Historical research expression" in text, name
        assert "paper-only" in text, name
        assert "not a current position" in text, name
        assert "Current market values are tracked" not in text, name
        assert "our paper book" not in text, name
        assert "<h2>What we hold</h2>" not in text, name
    healthcare = (ROOT / "site/healthcare.html").read_text()
    assert "data/portfolio.json" in healthcare
    assert "frozen historical record" in healthcare
    assert "basket was worth" not in healthcare


def test_portfolio_record_is_frozen_without_changing_its_bytes():
    import fetch_portfolio_prices as prices
    path = ROOT / "site/data/portfolio.json"
    before = path.read_bytes()
    with mock.patch.object(prices, "fetch_yahoo_price", side_effect=AssertionError("frozen record must not reprice")):
        assert prices.update_portfolio() is True
    locator = json.loads((ROOT / "pipeline/trap_map_archive_locator.json").read_text())
    assert path.read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == locator["public_historical_portfolio_sha256"]
    source = (ROOT / "pipeline/auto_pipeline.py").read_text()
    assert 'run_script("Fetch Portfolio Prices", "fetch_portfolio_prices.py"' not in source


def test_public_basket_cannot_silently_resume_live_marks(tmp_path):
    from trap_map_archive import check_retirement
    site, pipeline = public_fixture(tmp_path)
    assert check_retirement(site, pipeline) == []
    d = json.loads((site / "data/portfolio.json").read_text())
    d["baskets"][0]["basket_current_value"] = 999999
    (site / "data/portfolio.json").write_text(json.dumps(d))
    assert any("frozen historical basket" in error for error in check_retirement(site, pipeline))

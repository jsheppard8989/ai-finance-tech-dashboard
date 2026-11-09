"""The public repository carries a private locator, never archived record payloads."""
import json
from pathlib import Path
from unittest import mock
import pytest
import trap_map_archive as archive
import build_trap_map as build

ROOT = Path(__file__).resolve().parent.parent


def test_archive_payload_is_not_in_public_repository():
    assert not (ROOT / "pipeline/private_archive/trap_map").exists()
    assert not list((ROOT / "pipeline").rglob("trap_map.json"))


def test_locator_points_to_confirmed_private_storage_without_record_payloads():
    path = ROOT / "pipeline/trap_map_archive_locator.json"
    assert path.is_file(), "A metadata-only private archive locator is required"
    data = json.loads(path.read_text())
    assert data["private_repository"] == "jsheppard8989/dragonfly-private"
    assert data["private_archive_path"] == "trap_map_archive_2026-11-05"
    assert data["private_commit"] == "c7eff38e3dd022d066dba968cb9866d74022c9c9"
    assert data["ops_archive_path"] == "/workspace/cos/trap_map_archive_2026-11-05"
    assert not {"rows", "totals", "snapshot_totals", "record_ids", "benchmark"}.intersection(data)
    doc = ROOT / "pipeline/TRAP_MAP_RETIREMENT.md"
    assert doc.is_file()
    text = doc.read_text()
    assert "jsheppard8989/dragonfly-private" in text
    assert "trap_map_archive_2026-11-05" in text
    assert "Nothing historical was deleted" in text


def test_public_publish_guard_never_opens_private_record_contents():
    with mock.patch.object(archive, "check_archive", side_effect=AssertionError("public CI must not read private records")):
        assert archive.check_retirement(ROOT / "site", ROOT / "pipeline") == []


def test_default_record_paths_are_outside_the_public_checkout():
    assert not archive.ARCHIVE.resolve().is_relative_to(ROOT.resolve())
    assert build.ARCHIVE == archive.ARCHIVE
    assert build.DATA == archive.ARCHIVE / "trap_map.json"


def test_builder_rejects_record_or_output_paths_anywhere_in_public_repo():
    with pytest.raises(ValueError, match="public repository"):
        build.build(write=False, data=ROOT / "pipeline/accidental/trap_map.json")


@pytest.fixture
def public_checkout(tmp_path):
    import shutil
    repo = tmp_path / "public"
    pipeline, site = repo / "pipeline", repo / "site"
    pipeline.mkdir(parents=True)
    (site / "data").mkdir(parents=True)
    for name in ("TRAP_MAP_RETIREMENT.md", "trap_map_archive_locator.json"):
        shutil.copyfile(ROOT / "pipeline" / name, pipeline / name)
    shutil.copyfile(ROOT / "site/data/portfolio.json", site / "data/portfolio.json")
    return repo, pipeline, site


@pytest.mark.parametrize("name", ["TRAP_MAP_RETIREMENT.md", "trap_map_archive_locator.json"])
def test_missing_pointer_component_fails_closed(public_checkout, name):
    _, pipeline, site = public_checkout
    (pipeline / name).unlink()
    assert any("locator" in e for e in archive.check_retirement(site, pipeline))


@pytest.mark.parametrize("field,value", [("private_repository", "anyone/public"), ("private_commit", "main"), ("manifest_sha256", "wrong"), ("rows", [])])
def test_invalid_or_payload_bearing_locator_fails_closed(public_checkout, field, value):
    _, pipeline, site = public_checkout
    path = pipeline / "trap_map_archive_locator.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    assert any("locator" in e for e in archive.check_retirement(site, pipeline))


def test_record_copy_outside_pages_also_blocks_publication(public_checkout):
    repo, pipeline, site = public_checkout
    docs = repo / "docs"
    docs.mkdir()
    (docs / "trap_map.json").write_text('{"synthetic": true}')
    assert any("record payload" in e for e in archive.check_retirement(site, pipeline))


def test_public_guard_has_no_private_filesystem_or_network_dependency():
    import socket
    read_bytes, read_text = Path.read_bytes, Path.read_text
    def safe_bytes(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(archive.ARCHIVE), "Private archive must not be opened by public CI"
        return read_bytes(path, *args, **kwargs)
    def safe_text(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(archive.ARCHIVE), "Private archive must not be opened by public CI"
        return read_text(path, *args, **kwargs)
    with mock.patch.object(Path, "read_bytes", safe_bytes), mock.patch.object(Path, "read_text", safe_text), mock.patch.object(socket.socket, "connect", side_effect=AssertionError("No CI network access")):
        assert archive.check_retirement(ROOT / "site", ROOT / "pipeline") == []


def test_public_cli_passes_with_private_archive_absent(tmp_path):
    import os, subprocess, sys
    env = dict(os.environ, TRAP_MAP_PRIVATE_ARCHIVE=str(tmp_path / "missing-private-records"))
    run = subprocess.run([sys.executable, str(ROOT / "pipeline/trap_map_archive.py"), "--check"], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("realized", [-10, 0, 5])
def test_synthetic_accounting_stays_covered_without_private_records(realized):
    # Entirely synthetic sizing/marks, not historical portfolio payloads.
    data = {"rows": [
        {"id": "example-open", "status": "live", "trade": {"cost": 50, "value": 55}},
        {"id": "example-closed", "status": "closed", "trade": {"cost": 100}, "exit": {"value": 100 + realized, "result": realized}},
    ], "benchmark": {"buys": [{"shares": 15}], "spy_close_now": 11}}
    totals = build.compute(data)["totals"]
    assert totals["cost"] == 50
    assert totals["value"] == 55
    assert totals["closed_cash"] == 100 + realized
    assert totals["realized_change"] == realized
    assert totals["portfolio_cost"] == 150
    assert totals["portfolio_value"] == 155 + realized
    assert totals["portfolio_change"] == 5 + realized
    assert totals["spy_value"] == 165 and totals["spy_change"] == 15


def test_retirement_gate_cannot_fall_back_to_legacy_page_rules(public_checkout):
    import publish_guard
    _, pipeline, site = public_checkout
    (pipeline / "TRAP_MAP_RETIREMENT.md").unlink()
    (pipeline / "trap_map_archive_locator.json").unlink()
    (pipeline / "trap_map_archive.py").write_text("# retirement gate present")
    (site / "trap-map.html").write_text("<html>accidentally resurrected</html>")
    assert any("locator" in e for e in publish_guard.check_trap_map(site, pipeline, {}))

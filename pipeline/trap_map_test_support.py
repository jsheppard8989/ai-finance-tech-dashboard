"""Local-only private record fixtures; no copying into the public checkout/network calls."""
import json
from unittest import SkipTest
from trap_map_archive import private_archive_path


def private_archive():
    path = private_archive_path()
    if not path.is_dir():
        raise SkipTest("Private Trap Map archive not present locally; set TRAP_MAP_PRIVATE_ARCHIVE to run historical-record assertions (no CI network access)")
    return path


def private_records():
    return json.loads((private_archive() / "trap_map.json").read_text(encoding="utf-8"))

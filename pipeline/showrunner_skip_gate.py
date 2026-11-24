#!/usr/bin/env python3
"""Pre-analysis Show Runner skip gate.

Jared, 2026-11-23 5:50 PM CT (decisions.md, narrow skip):
  - Episode with Ditka89 total_score < 30: do not analyze and do not publish.
  - Moonshots episodes are never skipped on score.
  - Fail open: no score yet, ledger/scores file missing or unreadable, or
    parse error => process as normal (log a warning).
  - Only the <30 rule is binding. DEFER and SKIP at 30+ stay advisory.

The pipeline runs on Jared's Mac. Ditka's ledger lives on the box at
/workspace/cos/showrunner/ledger.db, which the Mac cannot read. Sync is a
compact JSON snapshot:

  Box (writer):  /workspace/cos/showrunner/runs/showrunner_scores.json
                 (screen.py apply/rescore refreshes this)
  Mac (reader):  pipeline/state/showrunner_scores.json
                 (copy after each 1 PM / 9 PM CT scoring pass, before the
                 10 PM analysis window)

Override with SHOWRUNNER_SCORES_PATH or SHOWRUNNER_LEDGER_PATH (sqlite).

Skip log (append-only, for Red Team spot-check on Mon Dec 21, 2026):
  pipeline/state/skip_log.jsonl
  Override with SHOWRUNNER_SKIP_LOG_PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    CT = timezone.utc

from workspace_paths import PIPELINE_DIR, STATE_DIR, TRANSCRIPT_DIR

SCHEMA = "showrunner.scores.v1"
SKIP_SCORE_THRESHOLD = 30.0
DEFAULT_SCORES_PATH = STATE_DIR / "showrunner_scores.json"
ALT_SCORES_PATH = PIPELINE_DIR / "data" / "showrunner_scores.json"
DEFAULT_SKIP_LOG_PATH = STATE_DIR / "skip_log.jsonl"

LEDGER_QUERY = """
SELECT guid, url, feed_name, title, published_at, total_score, decision,
       published_summary_id, run_date
FROM episodes
WHERE total_score IS NOT NULL
"""


@dataclass
class ScoredEpisode:
    guid: str
    url: str = ""
    feed_name: str = ""
    title: str = ""
    published_at: str = ""
    total_score: float = 0.0
    decision: str = ""
    published_summary_id: Optional[int] = None
    run_date: str = ""


@dataclass
class ScoreIndex:
    by_guid: dict[str, ScoredEpisode] = field(default_factory=dict)
    by_url: dict[str, ScoredEpisode] = field(default_factory=dict)
    by_summary_id: dict[int, ScoredEpisode] = field(default_factory=dict)
    source: str = ""
    episode_count: int = 0


@dataclass
class SkipDecision:
    skip: bool
    reason: str
    score: Optional[float] = None
    show: Optional[str] = None
    title: Optional[str] = None
    guid: Optional[str] = None
    episode_id: Optional[int] = None
    decision: Optional[str] = None
    warning: Optional[str] = None

    @property
    def fail_open(self) -> bool:
        return (not self.skip) and self.reason in {
            "no_score",
            "unreadable",
            "parse_error",
            "invalid_score",
        }


def now_ct() -> datetime:
    return datetime.now(CT)


def is_moonshots(name: Optional[str]) -> bool:
    return bool(name) and "moonshots" in str(name).lower()


def _norm_key(value: Optional[str]) -> str:
    return (value or "").strip()


def _norm_url(value: Optional[str]) -> str:
    url = (value or "").strip()
    if len(url) > 1 and url.endswith("/"):
        url = url[:-1]
    return url


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _episode_from_mapping(raw: Any) -> Optional[ScoredEpisode]:
    if not isinstance(raw, dict):
        return None
    guid = _norm_key(raw.get("guid"))
    if not guid:
        return None
    score = _as_float(raw.get("total_score"))
    if score is None:
        return None
    return ScoredEpisode(
        guid=guid,
        url=_norm_url(raw.get("url")),
        feed_name=str(raw.get("feed_name") or ""),
        title=str(raw.get("title") or ""),
        published_at=str(raw.get("published_at") or ""),
        total_score=score,
        decision=str(raw.get("decision") or ""),
        published_summary_id=_as_int(raw.get("published_summary_id")),
        run_date=str(raw.get("run_date") or ""),
    )


def index_episodes(rows: Iterable[Any], source: str = "") -> ScoreIndex:
    idx = ScoreIndex(source=source)
    for raw in rows:
        if not isinstance(raw, dict) and hasattr(raw, "keys"):
            raw = dict(raw)
        ep = _episode_from_mapping(raw)
        if ep is None:
            continue
        idx.by_guid[ep.guid] = ep
        if ep.url and ep.url not in idx.by_url:
            idx.by_url[ep.url] = ep
        if ep.published_summary_id is not None and ep.published_summary_id not in idx.by_summary_id:
            idx.by_summary_id[ep.published_summary_id] = ep
    idx.episode_count = len(idx.by_guid)
    return idx


def load_scores_json(path: Path) -> ScoreIndex:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        episodes = data.get("episodes")
        if isinstance(episodes, list):
            rows = episodes
        elif isinstance(episodes, dict):
            rows = []
            for guid, payload in episodes.items():
                if isinstance(payload, dict):
                    row = dict(payload)
                    row.setdefault("guid", guid)
                    rows.append(row)
        else:
            raise ValueError("scores JSON has no episodes list")
    else:
        raise ValueError("scores JSON must be an object or list")
    return index_episodes(rows, source=str(path))


def load_scores_ledger(path: Path) -> ScoreIndex:
    con = sqlite3.connect(str(path))
    try:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(LEDGER_QUERY)]
    finally:
        con.close()
    return index_episodes(rows, source=str(path))


def export_scores_from_ledger(ledger_path: Path, dest_path: Path) -> dict:
    """Write a compact scores snapshot the Mac pipeline can read."""
    con = sqlite3.connect(str(ledger_path))
    try:
        con.row_factory = sqlite3.Row
        rows = []
        for r in con.execute(LEDGER_QUERY + " ORDER BY guid"):
            d = dict(r)
            if d.get("total_score") is not None:
                d["total_score"] = float(d["total_score"])
            rows.append(d)
    finally:
        con.close()
    payload = {
        "schema": SCHEMA,
        "exported_at": now_ct().isoformat(),
        "source": str(ledger_path),
        "episode_count": len(rows),
        "episodes": rows,
    }
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def _resolve_source_paths(
    scores_path: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
) -> tuple[Optional[Path], Optional[Path], Optional[str]]:
    """Return (json_path, ledger_path, warning). Env wins only when args are omitted."""
    if ledger_path is not None:
        return None, Path(ledger_path), None
    if scores_path is not None:
        return Path(scores_path), None, None

    env_ledger = os.environ.get("SHOWRUNNER_LEDGER_PATH", "").strip()
    if env_ledger:
        return None, Path(env_ledger).expanduser(), None
    env_scores = os.environ.get("SHOWRUNNER_SCORES_PATH", "").strip()
    if env_scores:
        return Path(env_scores).expanduser(), None, None

    if DEFAULT_SCORES_PATH.exists():
        return DEFAULT_SCORES_PATH, None, None
    if ALT_SCORES_PATH.exists():
        return ALT_SCORES_PATH, None, None
    return (
        DEFAULT_SCORES_PATH,
        None,
        f"Show Runner scores not found at {DEFAULT_SCORES_PATH} "
        f"(or {ALT_SCORES_PATH}); fail open",
    )


def load_score_index(
    scores_path: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
) -> tuple[Optional[ScoreIndex], Optional[str]]:
    """Load the score index. On any problem return (None, warning) — fail open."""
    json_path, sqlite_path, missing_warning = _resolve_source_paths(scores_path, ledger_path)
    if missing_warning and sqlite_path is None and (json_path is None or not json_path.exists()):
        return None, missing_warning
    try:
        if sqlite_path is not None:
            if not sqlite_path.exists():
                return None, f"Show Runner ledger missing at {sqlite_path}; fail open"
            return load_scores_ledger(sqlite_path), None
        assert json_path is not None
        if not json_path.exists():
            return None, f"Show Runner scores missing at {json_path}; fail open"
        return load_scores_json(json_path), None
    except Exception as e:
        src = sqlite_path or json_path
        return None, f"Show Runner scores unreadable ({src}: {type(e).__name__}: {e}); fail open"


def lookup(meta: dict, index: ScoreIndex) -> Optional[ScoredEpisode]:
    """Match by rss guid, then enclosure/audio URL, then published_summary_id.

    Never match on title alone.
    """
    guid = _norm_key(meta.get("rss_guid") or meta.get("guid"))
    if guid and guid in index.by_guid:
        return index.by_guid[guid]
    url = _norm_url(
        meta.get("audio_url") or meta.get("url") or meta.get("enclosure_url")
    )
    if url and url in index.by_url:
        return index.by_url[url]
    summary_id = _as_int(meta.get("published_summary_id") or meta.get("episode_id"))
    if summary_id is not None and summary_id in index.by_summary_id:
        # Only use the summary-id fallback when no guid/url was provided.
        # A provided guid/url that did not match must fail open, not steal
        # another episode's score via a coincidental id.
        if not guid and not url:
            return index.by_summary_id[summary_id]
    return None


def evaluate_episode(meta: dict, index: Optional[ScoreIndex], *, load_warning: Optional[str] = None) -> SkipDecision:
    if index is None:
        return SkipDecision(
            skip=False,
            reason="unreadable",
            guid=_norm_key(meta.get("rss_guid") or meta.get("guid")) or None,
            show=(meta.get("podcast_name") or meta.get("feed_name") or None),
            title=(meta.get("title") or meta.get("episode_title") or None),
            warning=load_warning or "Show Runner scores unavailable; fail open",
        )
    ep = lookup(meta, index)
    if ep is None:
        return SkipDecision(
            skip=False,
            reason="no_score",
            guid=_norm_key(meta.get("rss_guid") or meta.get("guid")) or None,
            show=(meta.get("podcast_name") or meta.get("feed_name") or None),
            title=(meta.get("title") or meta.get("episode_title") or None),
            warning="Show Runner has no score for this episode yet; fail open",
        )
    show = ep.feed_name or (meta.get("podcast_name") or "")
    title = ep.title or (meta.get("title") or meta.get("episode_title") or "")
    if is_moonshots(show) or is_moonshots(meta.get("podcast_name")):
        return SkipDecision(
            skip=False,
            reason="moonshots_exempt",
            score=ep.total_score,
            show=show,
            title=title,
            guid=ep.guid,
            episode_id=ep.published_summary_id,
            decision=ep.decision,
        )
    score = _as_float(ep.total_score)
    if score is None:
        return SkipDecision(
            skip=False,
            reason="invalid_score",
            show=show,
            title=title,
            guid=ep.guid,
            episode_id=ep.published_summary_id,
            decision=ep.decision,
            warning=f"Show Runner score is not numeric for {ep.guid}; fail open",
        )
    if score < SKIP_SCORE_THRESHOLD:
        return SkipDecision(
            skip=True,
            reason="score_below_threshold",
            score=score,
            show=show,
            title=title,
            guid=ep.guid,
            episode_id=ep.published_summary_id,
            decision=ep.decision,
        )
    return SkipDecision(
        skip=False,
        reason="at_or_above_threshold",
        score=score,
        show=show,
        title=title,
        guid=ep.guid,
        episode_id=ep.published_summary_id,
        decision=ep.decision,
    )


def skip_log_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("SHOWRUNNER_SKIP_LOG_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_SKIP_LOG_PATH


def _log_fingerprint(guid: str, score: Optional[float]) -> str:
    if score is None:
        return f"{guid}|"
    return f"{guid}|{score:.4f}"


def existing_skip_fingerprints(log_path: Path) -> set[str]:
    found: set[str] = set()
    if not log_path.exists():
        return found
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            guid = _norm_key(row.get("guid"))
            if not guid:
                continue
            found.add(_log_fingerprint(guid, _as_float(row.get("score"))))
    except OSError:
        return found
    return found


def log_skip(decision: SkipDecision, log_path: Optional[Path] = None) -> bool:
    """Append one skip row if this guid+score has not already been logged.

    Returns True if a new line was written.
    """
    if not decision.skip:
        return False
    path = skip_log_path(log_path)
    guid = decision.guid or ""
    fingerprint = _log_fingerprint(guid, decision.score)
    if fingerprint in existing_skip_fingerprints(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": now_ct().isoformat(),
        "guid": guid or None,
        "episode_id": decision.episode_id,
        "show": decision.show,
        "score": decision.score,
        "title": decision.title,
        "decision": decision.decision,
        "reason": decision.reason,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


_WARNED_LOAD = False
_INDEX_CACHE: tuple[Optional[ScoreIndex], Optional[str]] | None = None


def reset_cache() -> None:
    global _WARNED_LOAD, _INDEX_CACHE
    _WARNED_LOAD = False
    _INDEX_CACHE = None


def _cached_index() -> tuple[Optional[ScoreIndex], Optional[str]]:
    global _INDEX_CACHE, _WARNED_LOAD
    if _INDEX_CACHE is None:
        _INDEX_CACHE = load_score_index()
        index, warning = _INDEX_CACHE
        if warning and not _WARNED_LOAD:
            print(f"    ⚠ {warning}")
            _WARNED_LOAD = True
    return _INDEX_CACHE


def should_skip_and_log(
    meta: dict,
    *,
    scores_path: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
    use_process_cache: bool = True,
) -> bool:
    """Return True if this episode must not be analyzed or published.

    Fail open on any load/parse/lookup problem. Logs a skip once per guid+score.
    """
    try:
        if use_process_cache and scores_path is None and ledger_path is None:
            index, warning = _cached_index()
        else:
            index, warning = load_score_index(scores_path=scores_path, ledger_path=ledger_path)
            if warning:
                print(f"    ⚠ {warning}")
        decision = evaluate_episode(meta, index, load_warning=warning)
        if decision.warning and decision.reason != "no_score":
            # no_score is the common fail-open for new episodes; keep that to
            # one cache-level warning plus a quiet process-as-normal path.
            if decision.reason != "unreadable" or not use_process_cache:
                if decision.warning and not (use_process_cache and decision.reason == "unreadable"):
                    print(f"    ⚠ {decision.warning}")
        if decision.skip:
            wrote = log_skip(decision, log_path=log_path)
            score = f"{decision.score:.1f}" if decision.score is not None else "?"
            eid = f" id={decision.episode_id}" if decision.episode_id is not None else ""
            extra = "" if wrote else " (already logged)"
            print(
                f"    ⏭ Show Runner skip{eid}: {decision.show or 'unknown show'} "
                f"score {score} < {SKIP_SCORE_THRESHOLD:.0f}; not analyzing{extra}"
            )
            return True
        return False
    except Exception as e:
        print(f"    ⚠ Show Runner skip gate failed open: {type(e).__name__}: {e}")
        return False


def sidecar_meta_for_transcript(transcript_path: Path) -> dict:
    sidecar = transcript_path.parent / f"{transcript_path.stem}.meta.json"
    meta: dict[str, Any] = {"transcript": str(transcript_path)}
    if sidecar.exists():
        try:
            raw = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                meta.update(raw)
        except Exception as e:
            meta["_sidecar_error"] = f"{type(e).__name__}: {e}"
    return meta


def dry_run_unprocessed(
    transcript_dir: Optional[Path] = None,
    scores_path: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
    processed_check=None,
) -> list[SkipDecision]:
    """Evaluate unprocessed transcripts against the current scores snapshot."""
    index, warning = load_score_index(scores_path=scores_path, ledger_path=ledger_path)
    if warning:
        print(f"WARNING: {warning}")
    tdir = Path(transcript_dir) if transcript_dir is not None else TRANSCRIPT_DIR
    skips: list[SkipDecision] = []
    if not tdir.exists():
        return skips
    for path in sorted(tdir.glob("*.txt")):
        if processed_check is not None and processed_check(path):
            continue
        meta = sidecar_meta_for_transcript(path)
        decision = evaluate_episode(meta, index, load_warning=warning)
        if decision.skip:
            skips.append(decision)
    return skips


def _cmd_export(args: argparse.Namespace) -> int:
    payload = export_scores_from_ledger(Path(args.ledger), Path(args.dest))
    print(f"wrote {args.dest} ({payload['episode_count']} scored episodes)")
    return 0


def _cmd_dry_run(args: argparse.Namespace) -> int:
    scores = Path(args.scores) if args.scores else None
    ledger = Path(args.ledger) if args.ledger else None
    tdir = Path(args.transcripts) if args.transcripts else None
    processed_check = None
    if not args.all_transcripts:
        try:
            from analyze_transcript import is_transcript_processed
            processed_check = is_transcript_processed
        except Exception as e:
            print(f"WARNING: could not import is_transcript_processed ({e}); scoring every .txt")
    skips = dry_run_unprocessed(
        transcript_dir=tdir,
        scores_path=scores,
        ledger_path=ledger,
        processed_check=processed_check,
    )
    print(f"would skip {len(skips)} unprocessed episode(s):")
    for d in skips:
        eid = d.episode_id if d.episode_id is not None else "-"
        score = f"{d.score:.1f}" if d.score is not None else "?"
        print(f"  id={eid}  show={d.show}  score={score}  {d.title}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Show Runner pre-analysis skip gate")
    sp = p.add_subparsers(dest="cmd", required=True)
    ex = sp.add_parser("export", help="Export compact scores JSON from a ledger.db")
    ex.add_argument("--ledger", required=True)
    ex.add_argument("--dest", required=True)
    dr = sp.add_parser("dry-run", help="List unprocessed transcripts that would be skipped")
    dr.add_argument("--scores")
    dr.add_argument("--ledger")
    dr.add_argument("--transcripts")
    dr.add_argument("--all-transcripts", action="store_true", help="Do not consult .processed markers")
    args = p.parse_args(argv)
    if args.cmd == "export":
        return _cmd_export(args)
    if args.cmd == "dry-run":
        return _cmd_dry_run(args)
    p.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())

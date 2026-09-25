"""The pre-open engine pass and polling loop.

One session per day. Drafts first seen at or before the cutoff are sized once
and frozen; drafts first seen after it are carded `late` and never sized.
DONE is written once the cutoff has passed and every on-time draft has a card.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from dragonfly.engine import core
from dragonfly.engine.core import (
    DRAFT_SUFFIX,
    OUTCOME_LATE,
    OUTCOME_REJECTED,
    OUTCOME_SIZED,
    EngineError,
    SessionClock,
    iso,
    parse_iso,
)
from dragonfly.engine.gitops import PrivateRepo

log = logging.getLogger("dragonfly.engine")

UNIDENTIFIED_DIR = "unidentified"
DONE_NAME = "DONE"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


class Engine:
    def __init__(
        self,
        repo_path: Path,
        session_date: date,
        clock: Optional[SessionClock] = None,
        book_path: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        pull: bool = True,
        push: bool = True,
        finalize: bool = False,
        poll_seconds: int = core.DEFAULT_POLL_SECONDS,
        now_fn: Callable[[], datetime] = core.now_ct,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.repo_path = Path(repo_path)
        self.session_date = session_date
        self.clock = clock or SessionClock(session_date)
        self.book_path = Path(book_path) if book_path else core.default_book_path()
        self.state_root = Path(state_dir) if state_dir else core.state_dir()
        self.pull = pull
        self.push = push
        self.finalize = finalize
        self.poll_seconds = max(1, int(poll_seconds))
        self.now_fn = now_fn
        self.sleep_fn = sleep_fn
        self.git: Optional[PrivateRepo] = PrivateRepo(self.repo_path, sleep=sleep_fn) if (pull or push) else None
        ds = session_date.isoformat()
        self.inbox_rel = f"inbox/{ds}"
        self.cards_rel = f"handoff/{ds}/cards"
        self.inbox_dir = self.repo_path / self.inbox_rel
        self.cards_dir = self.repo_path / self.cards_rel
        self.done_path = self.cards_dir / DONE_NAME
        self.state_path = self.state_root / "engine" / f"{ds}.json"

    # ------------------------------------------------------------ local state
    def _load_state(self) -> dict:
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            st = {}
        except (OSError, ValueError) as exc:
            raise EngineError(f"engine state unreadable at {self.state_path}: {exc}") from exc
        st.setdefault("session_date", self.session_date.isoformat())
        st.setdefault("drafts", {})
        return st

    def _save_state(self, st: dict) -> None:
        _atomic_write(self.state_path, core.dumps(st))

    # ------------------------------------------------------------ cards on disk
    def load_cards(self) -> Dict[str, dict]:
        """key -> card. key is the trade_id, or unidentified/<stem>."""
        out: Dict[str, dict] = {}
        if not self.cards_dir.is_dir():
            return out
        paths = sorted(self.cards_dir.glob("*.json")) + sorted((self.cards_dir / UNIDENTIFIED_DIR).glob("*.json"))
        for path in paths:
            try:
                card = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise EngineError(f"existing card unreadable: {path}: {exc}") from exc
            key = path.stem if path.parent == self.cards_dir else f"{UNIDENTIFIED_DIR}/{path.stem}"
            out[key] = card
        return out

    def _card_path(self, key: str) -> Path:
        return self.cards_dir / f"{key}.json"

    # ------------------------------------------------------------ one pass
    def run_pass(self, tick: Optional[datetime] = None) -> dict:
        tick = (tick or self.now_fn()).astimezone(core.tz()).replace(microsecond=0)
        result = {"tick": iso(tick), "written": [], "pending": [], "frozen_changed": [], "done": None,
                  "pulled": False, "pushed": False}
        if self.git is not None:
            if self.push:
                # Anything a crashed earlier pass wrote but did not commit goes first.
                self.git.commit_paths([self.cards_rel], f"engine {self.session_date}: recover uncommitted cards")
            if self.pull:
                result["pulled"] = self.git.sync()

        st = self._load_state()
        drafts: List[Tuple[str, bytes]] = []
        if self.inbox_dir.is_dir():
            for path in sorted(self.inbox_dir.glob(f"*{DRAFT_SUFFIX}")):
                if path.is_file():
                    drafts.append((path.name, path.read_bytes()))
        for name, data in drafts:
            if name not in st["drafts"]:
                st["drafts"][name] = {"first_seen_at": iso(tick), "sha256": core.sha256_bytes(data), "logged_sha": []}
                log.info("draft first seen: %s/%s at %s", self.inbox_rel, name, iso(tick))
        self._save_state(st)

        existing = self.load_cards()
        by_file = {c["engine"]["draft_file"]: k for k, c in existing.items() if isinstance(c.get("engine"), dict)}
        ordered = sorted(drafts, key=lambda d: (st["drafts"][d[0]]["first_seen_at"], d[0]))

        book = None
        ctx = None
        prep = None
        window_closed = tick > self.clock.end
        may_size_without_regime = self.clock.past_cutoff(tick) or self.finalize

        for name, data in ordered:
            rec = st["drafts"][name]
            sha = core.sha256_bytes(data)
            draft_file = f"{self.inbox_rel}/{name}"
            if draft_file in by_file:
                card = existing[by_file[draft_file]]
                if sha != card["engine"]["draft_sha256"] and sha not in rec["logged_sha"]:
                    log.warning("card %s is frozen; draft %s changed after carding (sha %s); ignored",
                                by_file[draft_file], draft_file, sha[:12])
                    rec["logged_sha"].append(sha)
                    result["frozen_changed"].append(by_file[draft_file])
                continue

            first_seen = parse_iso(rec["first_seen_at"])
            late = self.clock.is_late(first_seen)
            try:
                draft = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                draft = None
            trade_id, id_reasons = core.draft_identity(name, draft)

            if book is None:
                book = core.load_book(self.book_path)
                regime, regime_rel, problems = core.load_regime(self.repo_path, self.session_date)
                for p in problems:
                    log.warning("regime snapshot problem: %s", p)
                ctx = core.risk_context(book, regime, regime_rel)
                prep, prep_rel = core.load_prep_measurements(self.repo_path, self.session_date)

            common = dict(session_date=self.session_date, draft_file=draft_file, draft_sha=sha,
                          first_seen=first_seen, clock=self.clock)
            stem = name[: -len(DRAFT_SUFFIX)]
            key: Optional[str] = trade_id
            card: Optional[dict] = None

            if trade_id is not None and trade_id in existing:
                key = f"{UNIDENTIFIED_DIR}/{stem}"
                card = core.reject_record(trade_id=None, ticker=(draft or {}).get("ticker") if isinstance(draft, dict) else None,
                                          reasons=["duplicate_trade_id", f"trade_id {trade_id} already carded"],
                                          now=self.now_fn(), book_name=book["book"], ctx=ctx, late=late, **common)
            elif draft is None or not isinstance(draft, dict):
                key = trade_id or f"{UNIDENTIFIED_DIR}/{stem}"
                card = core.reject_record(trade_id=trade_id, ticker=None, reasons=["draft_not_json_object"],
                                          now=self.now_fn(), book_name=book["book"], ctx=ctx, late=late, **common)
            else:
                presized = [reason for field, reason in core.PRESIZED_REASONS if field in draft]
                stripped = {k: v for k, v in draft.items() if k not in dict(core.PRESIZED_REASONS)}
                if isinstance(stripped.get("entry"), dict) and "max_fill" in stripped["entry"]:
                    presized.append("draft_carries_max_fill")
                    stripped["entry"] = {k: v for k, v in stripped["entry"].items() if k != "max_fill"}
                errs = core.schema_errors("trade_draft.schema.json", stripped)
                if trade_id is None:
                    key = f"{UNIDENTIFIED_DIR}/{stem}"
                    card = core.reject_record(trade_id=None, ticker=draft.get("ticker"),
                                              reasons=presized + ["trade_id_missing"] + [f"draft_schema_invalid: {e}" for e in errs],
                                              now=self.now_fn(), book_name=book["book"], ctx=ctx, late=late, **common)
                elif errs:
                    card = core.reject_record(trade_id=trade_id, ticker=draft.get("ticker"),
                                              reasons=presized + id_reasons + [f"draft_schema_invalid: {e}" for e in errs],
                                              now=self.now_fn(), book_name=book["book"], ctx=ctx, late=late, **common)
                elif late:
                    card = core.build_card(draft=stripped, outcome_hint=OUTCOME_LATE, extra_reasons=[],
                                           now=self.now_fn(), book=book, ctx=ctx, measurements=None, **common)
                else:
                    pre = presized + id_reasons + core.extra_validation(stripped, self.session_date, book)
                    if window_closed and not pre:
                        pre = ["engine_window_closed"]
                    if not pre and ctx["regime"] is None and not may_size_without_regime:
                        log.info("draft %s waiting for today's regime snapshot (cutoff %s)", draft_file, iso(self.clock.cutoff))
                        result["pending"].append(trade_id)
                        continue
                    measurements = None if pre else core.resolve_measurements(stripped, prep, prep_rel)
                    sized_cards = [c for c in existing.values()
                                   if c.get("engine", {}).get("outcome") == OUTCOME_SIZED and "sizing" in c]
                    live_book = core.with_pending(book, sized_cards)
                    card = core.build_card(draft=stripped, outcome_hint=None, extra_reasons=pre,
                                           now=self.now_fn(), book=live_book, ctx=ctx, measurements=measurements, **common)

            card = self._fail_closed(card, key, trade_id, draft, book, ctx, late, common)
            path = self._card_path(key)
            if path.exists():  # never rewrite a frozen card
                log.warning("card %s already exists on disk; not rewriting", key)
                continue
            _atomic_write(path, core.dumps(card))
            existing[key] = card
            by_file[draft_file] = key
            result["written"].append(key)
            log.info("carded %s: %s %s", key, card["engine"]["outcome"], card["engine"]["reasons"])

        self._save_state(st)

        done = self._maybe_done(tick, st, existing, drafts, result["pending"])
        result["done"] = done

        if self.git is not None and self.push and (result["written"] or done):
            msg = self._commit_message(result["written"], done)
            self.git.commit_and_push([self.cards_rel], msg, push=True)
            result["pushed"] = True
        elif self.git is not None and self.push and self.git.ahead():
            self.git.push()
            result["pushed"] = True
        return result

    def _fail_closed(self, card, key, trade_id, draft, book, ctx, late, common) -> dict:
        errs = core.card_errors(card)
        if not errs:
            return card
        log.error("card %s failed its schema; writing a reject record instead: %s", key, errs)
        record = core.reject_record(
            trade_id=trade_id if trade_id and not str(key).startswith(UNIDENTIFIED_DIR) else None,
            ticker=draft.get("ticker") if isinstance(draft, dict) else None,
            reasons=["card_schema_invalid"] + [f"card_schema_invalid: {e}" for e in errs],
            now=self.now_fn(), book_name=book["book"], ctx=ctx, late=late, **common,
        )
        errs2 = core.card_errors(record)
        if errs2:
            raise EngineError(f"reject record for {key} also failed its schema: {errs2}")
        return record

    # ------------------------------------------------------------ DONE
    def done_document(self, tick: datetime, st: dict, existing: Dict[str, dict], present: List[str]) -> dict:
        ids = {OUTCOME_SIZED: [], OUTCOME_REJECTED: [], OUTCOME_LATE: []}
        unidentified: List[str] = []
        for key in sorted(existing):
            eng = existing[key]["engine"]
            if key.startswith(UNIDENTIFIED_DIR + "/"):
                unidentified.append(eng["draft_file"])
                if eng["outcome"] == OUTCOME_LATE:
                    ids[OUTCOME_LATE].append(key)
                else:
                    ids[OUTCOME_REJECTED].append(key)
                continue
            ids[eng["outcome"]].append(key)
        carded_files = {c["engine"]["draft_file"] for c in existing.values()}
        withdrawn = sorted(
            f"{self.inbox_rel}/{name}" for name, rec in st["drafts"].items()
            if name not in present and f"{self.inbox_rel}/{name}" not in carded_files
            and not self.clock.is_late(parse_iso(rec["first_seen_at"]))
        )
        trade_ids = {k: [x for x in v if not x.startswith(UNIDENTIFIED_DIR + "/")] for k, v in ids.items()}
        return {
            "schema_version": "1.0.0",
            "marker": "DONE",
            "session_date": self.session_date.isoformat(),
            "as_of": iso(self.now_fn()),
            "cutoff": iso(self.clock.cutoff),
            "finalized_by": "cutoff" if self.clock.past_cutoff(tick) else "flag",
            "revision": 1,
            "counts": {
                "drafts": len(existing),
                "sized": len(ids[OUTCOME_SIZED]),
                "rejected": len(ids[OUTCOME_REJECTED]),
                "late": len(ids[OUTCOME_LATE]),
            },
            "trade_ids": trade_ids,
            "unidentified": unidentified,
            "withdrawn": withdrawn,
        }

    def _maybe_done(self, tick, st, existing, drafts, pending) -> Optional[dict]:
        if not (self.clock.past_cutoff(tick) or self.finalize):
            return None
        carded_files = {c["engine"]["draft_file"] for c in existing.values()}
        present = [name for name, _ in drafts]
        missing = [n for n in present if f"{self.inbox_rel}/{n}" not in carded_files]
        if missing or pending:
            log.warning("DONE held: uncarded drafts %s", missing or pending)
            return None
        doc = self.done_document(tick, st, existing, present)
        errs = core.schema_errors("engine_done.schema.json", doc)
        if errs:
            raise EngineError(f"DONE marker failed its schema: {errs}")
        prior = None
        if self.done_path.exists():
            try:
                prior = json.loads(self.done_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = None
        core_keys = ("counts", "trade_ids", "unidentified", "withdrawn")
        if prior and all(prior.get(k) == doc[k] for k in core_keys):
            return None
        if prior:
            doc["revision"] = int(prior.get("revision", 1)) + 1
            if prior.get("finalized_by") == "cutoff":
                doc["finalized_by"] = "cutoff"
        _atomic_write(self.done_path, core.dumps(doc))
        log.info("DONE r%d: %s", doc["revision"], doc["counts"])
        return doc

    def _commit_message(self, written: List[str], done: Optional[dict]) -> str:
        parts = []
        if written:
            parts.append(f"{len(written)} card(s) {', '.join(written[:6])}{' ...' if len(written) > 6 else ''}")
        if done:
            c = done["counts"]
            parts.append(f"DONE r{done['revision']} (sized {c['sized']}, rejected {c['rejected']}, late {c['late']})")
        return f"engine {self.session_date}: " + "; ".join(parts)

    # ------------------------------------------------------------ loop
    def next_tick(self, tick: datetime) -> datetime:
        step = timedelta(seconds=self.poll_seconds)
        start = self.clock.start
        if tick < start:
            nxt = start
        else:
            n = int((tick - start).total_seconds() // self.poll_seconds) + 1
            nxt = start + n * step
        if tick < self.clock.cutoff < nxt:
            nxt = self.clock.cutoff
        if tick < self.clock.end < nxt:
            nxt = self.clock.end
        return nxt

    def run_loop(self) -> int:
        """Poll from start to end. Exit 0 only if DONE exists when the loop ends."""
        now = self.now_fn()
        if now < self.clock.start:
            wait = (self.clock.start - now).total_seconds()
            log.info("sleeping %.0fs until window start %s", wait, iso(self.clock.start))
            self.sleep_fn(wait)
            now = self.now_fn()
        if now > self.clock.end:
            log.warning("started after the window end %s; one closing pass only (no sizing)", iso(self.clock.end))
        tick = now.replace(microsecond=0)
        failures = 0
        while True:
            try:
                self.run_pass(tick)
            except EngineError as exc:
                failures += 1
                log.error("pass at %s failed: %s", iso(tick), exc)
            if tick >= self.clock.end:
                break
            nxt = self.next_tick(tick)
            delay = (nxt - self.now_fn()).total_seconds()
            if delay > 0:
                self.sleep_fn(delay)
            actual = self.now_fn()
            tick = nxt if actual <= nxt + timedelta(seconds=5) else actual.replace(microsecond=0)
        if not self.done_path.exists():
            log.error("window ended without a DONE marker (%d failed passes)", failures)
            return 1
        return 0

"""The pre-open engine pass and polling loop.

One NYSE session per day (dragonfly/market_calendar.py; holidays and weekends
are a no-op). One engine pass per trade, no version-2 cards:

- The Architect writes inbox/<date>/<trade_id>.draft.json; the Red Team then
  writes inbox/<date>/<trade_id>.redteam.json against it.
- A draft is sized only once its red team file is valid, and only if that file
  was first seen valid by a pass scheduled at or before the 08:20 cutoff.
  Otherwise, after the cutoff, it gets a `late_redteam` card, unsized.
- warning_count is derived by the engine from the seven flags (plus a
  Mac-measured gap_history) and passed to caps()/size_*(). Red team keys that
  try to block or size are stripped and logged; hard blocks are the engine's.
- A book marked before the previous session's close blocks every draft
  (`book_stale`) and sizes nothing.
- Every measurement (price, ATR, ADV, relative volume, sector, spread) and every
  setup gate is recomputed on the Mac from the bars cache / prep file.
  Mismatch, unavailable, or a failed gate is a structural block on the card.

DONE is written after the cutoff once every draft has a card (sized,
rejected, or late).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from dragonfly import market_calendar as mc
from dragonfly.engine import core, measure
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
        bars_dir: Optional[Path] = None,
        watchlist_path: Optional[Path] = None,
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
        self.bars_dir = Path(bars_dir) if bars_dir else measure.default_bars_dir()
        self.watchlist_path = Path(watchlist_path) if watchlist_path else core.ROOT / "dragonfly" / "watchlist.json"
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
                  "pulled": False, "pushed": False, "not_session": False}
        try:
            session = mc.is_session(self.session_date)
        except mc.CalendarNotCovered as exc:
            raise EngineError(str(exc)) from exc
        if not session:
            log.info("%s is not an NYSE session (%s); engine idle", self.session_date,
                     mc.holiday_name(self.session_date) or "weekend")
            result["not_session"] = True
            return result
        if self.git is not None:
            if self.push:
                # Anything a crashed earlier pass wrote but did not commit goes first.
                self.git.commit_paths([self.cards_rel], f"engine {self.session_date}: recover uncommitted cards")
            if self.pull:
                result["pulled"] = self.git.sync()

        st = self._load_state()
        st.setdefault("redteam", {})
        drafts: List[Tuple[str, bytes]] = []
        if self.inbox_dir.is_dir():
            for path in sorted(self.inbox_dir.glob(f"*{DRAFT_SUFFIX}")):
                if path.is_file():
                    drafts.append((path.name, path.read_bytes()))
            for path in sorted(self.inbox_dir.glob(f"*{core.REDTEAM_SUFFIX}")):
                if path.is_file() and path.name not in st["redteam"]:
                    st["redteam"][path.name] = {"first_seen_at": iso(tick), "first_valid_at": None}
                    log.info("red team file first seen: %s/%s at %s", self.inbox_rel, path.name, iso(tick))
        for name, data in drafts:
            if name not in st["drafts"]:
                st["drafts"][name] = {"first_seen_at": iso(tick), "sha256": core.sha256_bytes(data), "logged_sha": []}
                log.info("draft first seen: %s/%s at %s", self.inbox_rel, name, iso(tick))
        self._save_state(st)

        existing = self.load_cards()
        by_file = {c["engine"]["draft_file"]: k for k, c in existing.items() if isinstance(c.get("engine"), dict)}
        ordered = sorted(drafts, key=lambda d: (st["drafts"][d[0]]["first_seen_at"], d[0]))
        env: Dict[str, object] = {}
        final = self.clock.past_cutoff(tick) or self.finalize

        for name, data in ordered:
            rec = st["drafts"][name]
            sha = core.sha256_bytes(data)
            draft_file = f"{self.inbox_rel}/{name}"
            if draft_file in by_file:
                key = by_file[draft_file]
                if sha != existing[key]["engine"]["draft_sha256"] and sha not in rec["logged_sha"]:
                    log.warning("card %s is frozen; draft %s changed after carding (sha %s); ignored",
                                key, draft_file, sha[:12])
                    rec["logged_sha"].append(sha)
                    result["frozen_changed"].append(key)
                continue
            outcome = self._card_one(name, data, sha, rec, st, tick, final, existing, env, result)
            if outcome is None:
                continue
            key, card = outcome
            card = self._fail_closed(card, key, env["ctx"])
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

    def _env(self, env: Dict[str, object]) -> Dict[str, object]:
        """Per-pass inputs, loaded once and only when a draft needs a card."""
        if not env:
            book = core.load_book(self.book_path)
            regime, regime_rel, problems = core.load_regime(self.repo_path, self.session_date)
            for p in problems:
                log.warning("regime snapshot problem: %s", p)
            prep, prep_rel = measure.load_prep(self.repo_path, self.session_date)
            env.update(book=book, ctx=core.risk_context(book, regime, regime_rel),
                       freshness=core.book_freshness(book, self.session_date),
                       prep=prep, prep_rel=prep_rel, watchlist=measure.load_watchlist(self.watchlist_path))
            if not env["freshness"]["fresh"]:
                log.error("book_stale: book marked %s, must be at or after %s; nothing will be sized",
                          env["freshness"].get("book_as_of"), env["freshness"].get("required_at_or_after"))
        return env

    def _redteam(self, trade_id: str, draft_sha: str, st: dict, tick: datetime):
        """(redteam or None, info, problems). Records first_valid_at in local state."""
        name = f"{trade_id}{core.REDTEAM_SUFFIX}"
        path = self.inbox_dir / name
        if not path.is_file():
            return None, None, ["redteam_missing"]
        data = path.read_bytes()
        rt, problems = core.parse_redteam(data, trade_id, draft_sha)
        rec = st["redteam"].setdefault(name, {"first_seen_at": iso(tick), "first_valid_at": None})
        info = {"file": f"{self.inbox_rel}/{name}", "sha256": core.sha256_bytes(data),
                "first_seen_at": rec["first_seen_at"], "first_valid_at": rec.get("first_valid_at")}
        if rt is None:
            if rec.get("logged_invalid") != info["sha256"]:
                log.warning("red team file %s invalid: %s", info["file"], problems)
                rec["logged_invalid"] = info["sha256"]
            return None, info, problems
        if rec.get("first_valid_at") is None:
            rec["first_valid_at"] = iso(tick)
            info["first_valid_at"] = rec["first_valid_at"]
        if rt["ignored_fields"] and rec.get("logged_ignored") != info["sha256"]:
            log.warning("red team file %s tried to set %s; ignored (red team never blocks or sizes)",
                        info["file"], rt["ignored_fields"])
            rec["logged_ignored"] = info["sha256"]
        if rt["warning_count_claim_ignored"]:
            log.warning("red team file %s claims warning_count %s; engine derived %d from the flags",
                        info["file"], rt["warning_count_claimed"], rt["warning_count"])
        info.update(warning_count=rt["warning_count"], warnings=rt["warnings"], as_of=rt["as_of"],
                    ignored_fields=rt["ignored_fields"], warning_count_claimed=rt["warning_count_claimed"],
                    warning_count_source="derived_from_flags")
        return rt, info, []

    def _card_one(self, name, data, sha, rec, st, tick, final, existing, envd, result):
        """Decide one uncarded draft. Returns (key, card), or None to wait."""
        first_seen = parse_iso(rec["first_seen_at"])
        late_draft = self.clock.is_late(first_seen)
        draft_file = f"{self.inbox_rel}/{name}"
        try:
            draft = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            draft = None
        trade_id, id_reasons = core.draft_identity(name, draft)
        env = self._env(envd)
        book, ctx = env["book"], env["ctx"]
        now = self.now_fn()
        common = dict(session_date=self.session_date, draft_file=draft_file, draft_sha=sha,
                      first_seen=first_seen, clock=self.clock)
        stem = name[: -len(DRAFT_SUFFIX)]
        ticker = draft.get("ticker") if isinstance(draft, dict) else None

        if trade_id is not None and trade_id in existing:
            return f"{UNIDENTIFIED_DIR}/{stem}", core.reject_record(
                trade_id=None, ticker=ticker, reasons=["duplicate_trade_id", f"trade_id {trade_id} already carded"],
                now=now, book_name=book["book"], ctx=ctx, late=late_draft, **common)
        if not isinstance(draft, dict):
            return (trade_id or f"{UNIDENTIFIED_DIR}/{stem}"), core.reject_record(
                trade_id=trade_id, ticker=None, reasons=["draft_not_json_object"],
                now=now, book_name=book["book"], ctx=ctx, late=late_draft, **common)

        presized = [reason for field, reason in core.PRESIZED_REASONS if field in draft]
        stripped = {k: v for k, v in draft.items() if k not in dict(core.PRESIZED_REASONS)}
        if isinstance(stripped.get("entry"), dict) and "max_fill" in stripped["entry"]:
            presized.append("draft_carries_max_fill")
            stripped["entry"] = {k: v for k, v in stripped["entry"].items() if k != "max_fill"}
        errs = core.schema_errors("trade_draft.schema.json", stripped)
        if trade_id is None:
            return f"{UNIDENTIFIED_DIR}/{stem}", core.reject_record(
                trade_id=None, ticker=ticker,
                reasons=presized + ["trade_id_missing"] + [f"draft_schema_invalid: {e}" for e in errs],
                now=now, book_name=book["book"], ctx=ctx, late=late_draft, **common)
        if errs:
            return trade_id, core.reject_record(
                trade_id=trade_id, ticker=ticker,
                reasons=presized + id_reasons + [f"draft_schema_invalid: {e}" for e in errs],
                now=now, book_name=book["book"], ctx=ctx, late=late_draft, **common)

        card_kw = dict(draft=stripped, now=now, book=book, ctx=ctx, **common)
        rt, rt_info, rt_problems = self._redteam(trade_id, sha, st, tick)
        if late_draft:
            return trade_id, core.build_card(kind=core.KIND_LATE, reasons=["late_draft"], redteam=rt,
                                             redteam_info=rt_info, **card_kw)
        pre = presized + id_reasons + core.extra_validation(stripped, self.session_date, book)
        if pre:
            return trade_id, core.build_card(kind=core.KIND_REJECT, reasons=pre, redteam=rt,
                                             redteam_info=rt_info, **card_kw)
        if not env["freshness"]["fresh"]:
            return trade_id, core.build_card(kind=core.KIND_REJECT, reasons=["book_stale"], redteam=rt,
                                             redteam_info=rt_info, extra_inputs={"book_freshness": env["freshness"]},
                                             **card_kw)
        # Red team gate: size only with a valid red team file seen by the cutoff pass.
        rt_on_time = rt is not None and not self.clock.is_late(parse_iso(rt_info["first_valid_at"]))
        if not rt_on_time:
            if rt is None and not final:
                log.info("draft %s waiting for its red team file (%s)", draft_file, ", ".join(rt_problems))
                result["pending"].append(trade_id)
                return None
            codes = ["late_redteam"] + [p for p in rt_problems if p != "redteam_missing"][:3]
            return trade_id, core.build_card(kind=core.KIND_LATE, reasons=codes, redteam=None,
                                             redteam_info=rt_info, **card_kw)
        if tick > self.clock.end:
            return trade_id, core.build_card(kind=core.KIND_REJECT, reasons=["engine_window_closed"], redteam=rt,
                                             redteam_info=rt_info, **card_kw)
        if ctx["regime"] is None and not final:
            log.info("draft %s waiting for today's regime snapshot (cutoff %s)", draft_file, iso(self.clock.cutoff))
            result["pending"].append(trade_id)
            return None
        mac = measure.resolve(stripped, self.session_date, bars_dir=self.bars_dir, prep=env["prep"],
                              prep_rel=env["prep_rel"], watchlist=env["watchlist"])
        sized_cards = [c for c in existing.values()
                       if c.get("engine", {}).get("outcome") == OUTCOME_SIZED and "sizing" in c]
        live_book = core.with_pending(book, sized_cards)
        card_kw["book"] = live_book
        return trade_id, core.build_card(kind=core.KIND_GOVERNOR, reasons=[], redteam=rt, redteam_info=rt_info,
                                         mac=mac, **card_kw)

    def _fail_closed(self, card: dict, key: str, ctx: dict) -> dict:
        """Every card is validated before writing. A failure is never written as sized."""
        errs = core.card_errors(card)
        if not errs:
            return card
        log.error("card %s failed its schema; writing a reject record instead: %s", key, errs)
        eng = card.get("engine") or {}
        record = core.reject_record(
            trade_id=card.get("trade_id") if not str(key).startswith(UNIDENTIFIED_DIR) else None,
            ticker=card.get("ticker"),
            reasons=["card_schema_invalid"] + [f"card_schema_invalid: {e}" for e in errs],
            session_date=self.session_date, draft_file=eng["draft_file"], draft_sha=eng["draft_sha256"],
            first_seen=parse_iso(eng["first_seen_at"]), clock=self.clock, now=self.now_fn(),
            book_name=eng.get("book", "paper"), ctx=ctx, late=eng.get("outcome") == OUTCOME_LATE,
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
        """Poll from start to end. Exit 0 only if DONE exists when the loop ends.

        On an NYSE holiday (or weekend) the engine idles: no pass, no DONE, exit 0.
        """
        try:
            if not mc.is_session(self.session_date):
                log.info("%s is not an NYSE session (%s); engine not run", self.session_date,
                         mc.holiday_name(self.session_date) or "weekend")
                return 0
        except mc.CalendarNotCovered as exc:
            log.error("%s", exc)
            return 2
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

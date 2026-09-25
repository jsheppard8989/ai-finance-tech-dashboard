"""Pure pieces of the pre-open engine: clock, schemas, book, regime, cards.

Python 3.9 compatible. Imports risk_math only (never bars, chains, guards, or
the watchlist builder), so the engine cannot make a market-data call.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dragonfly import risk_math as rm
from dragonfly.engine import ENGINE_VERSION

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "docs" / "dragonfly" / "schemas"
TZ_NAME = "America/Chicago"
TRADE_ID_RE = re.compile(r"^DF-[0-9]{4}-[0-9]{4}$")
DRAFT_SUFFIX = ".draft.json"
PRESIZED_REASONS = (
    ("sizing", "draft_carries_sizing"),
    ("risk_decision", "draft_carries_risk_decision"),
)
DEFAULT_START = "08:08"
DEFAULT_CUTOFF = "08:20"
DEFAULT_END = "08:24"
DEFAULT_POLL_SECONDS = 60
OPTION_INSTRUMENTS = ("call", "put", "debit_spread")

OUTCOME_SIZED = "sized"
OUTCOME_REJECTED = "rejected"
OUTCOME_LATE = "late"


class EngineError(RuntimeError):
    """Loud failure. The engine stops rather than write something unsafe."""


# ------------------------------------------------------------------ clock

def tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo(TZ_NAME)


def now_ct() -> datetime:
    return datetime.now(tz()).replace(microsecond=0)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise EngineError("naive datetime; every engine timestamp is America/Chicago aware")
    return dt.astimezone(tz()).isoformat()


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise EngineError(f"naive timestamp {value!r}")
    return dt.astimezone(tz())


def parse_hhmm(value: str) -> dtime:
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", value.strip())
    if not m:
        raise EngineError(f"bad HH:MM time {value!r}")
    return dtime(int(m.group(1)), int(m.group(2)))


class SessionClock:
    """Start, cutoff and end of the engine window on one session date, in CT."""

    def __init__(self, session_date: date, start: str = DEFAULT_START, cutoff: str = DEFAULT_CUTOFF,
                 end: str = DEFAULT_END):
        self.session_date = session_date
        z = tz()
        self.start = datetime.combine(session_date, parse_hhmm(start), tzinfo=z)
        self.cutoff = datetime.combine(session_date, parse_hhmm(cutoff), tzinfo=z)
        self.end = datetime.combine(session_date, parse_hhmm(end), tzinfo=z)
        if not (self.start <= self.cutoff <= self.end):
            raise EngineError("window must satisfy start <= cutoff <= end")

    def is_late(self, first_seen: datetime) -> bool:
        return first_seen > self.cutoff

    def past_cutoff(self, tick: datetime) -> bool:
        return tick > self.cutoff


# ------------------------------------------------------------------ schemas

_SCHEMA_CACHE: Dict[str, Any] = {}


def _validator(name: str):
    try:
        import jsonschema
    except ImportError as exc:  # fail closed: no validation, no cards
        raise EngineError(
            "jsonschema is not installed; the engine will not write unvalidated cards "
            "(python3 -m pip install --user -r dragonfly/requirements.txt)"
        ) from exc
    if name not in _SCHEMA_CACHE:
        schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        cls = jsonschema.Draft202012Validator
        _SCHEMA_CACHE[name] = cls(schema, format_checker=cls.FORMAT_CHECKER)
    return _SCHEMA_CACHE[name]


def schema_errors(name: str, instance: Any, limit: int = 8) -> List[str]:
    errors = sorted(_validator(name).iter_errors(instance), key=lambda e: [str(p) for p in e.path])
    out = []
    for err in errors[:limit]:
        where = "/".join(str(p) for p in err.path) or "$"
        out.append(f"{where}: {err.message[:160]}")
    return out


def card_errors(card: Mapping) -> List[str]:
    """Contract for every file under handoff/<date>/cards/*.json."""
    if card.get("record") == "engine_reject":
        return schema_errors("engine_reject_record.schema.json", card)
    errs = schema_errors("trade_card.schema.json", card)
    if "engine" not in card:
        errs.append("$: engine block missing")
    return errs


# ------------------------------------------------------------------ json

def to_json_number(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=False, default=str) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ book

def state_dir() -> Path:
    override = os.environ.get("DRAGONFLY_STATE_DIR")
    return Path(override) if override else ROOT / "dragonfly" / "state" / "live"


def default_book_path() -> Path:
    return state_dir() / "book.json"


def load_book(path: Path) -> dict:
    """Read the live book (engine of record). Missing or invalid is loud."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EngineError(f"book state not found at {path}") from exc
    except (OSError, ValueError) as exc:
        raise EngineError(f"book state unreadable at {path}: {exc}") from exc
    errs = schema_errors("engine_book.schema.json", raw)
    if errs:
        raise EngineError(f"book state invalid at {path}: {errs}")
    positions = raw["positions"]
    pos_heat = sum((rm.D(p["heat"]) for p in positions), Decimal("0"))
    pos_notional = sum(
        (rm.D(p.get("notional", 0)) for p in positions if p.get("instrument") == "stock"), Decimal("0")
    )
    return {
        "path": str(path),
        "book": raw["book"],
        "as_of": raw["as_of"],
        "equity": rm.D(raw["equity"]),
        "cash": rm.D(raw["cash"]),
        "open_heat": max(rm.D(raw.get("open_heat", 0)), pos_heat),
        "gross_long": max(rm.D(raw.get("gross_long", 0)), pos_notional),
        "positions": [dict(p) for p in positions],
        "day_pnl_pct": rm.D(raw["day_pnl_pct"]),
        "week_pnl_pct": rm.D(raw["week_pnl_pct"]),
        "drawdown_pct": rm.D(raw["drawdown_pct"]),
        "consecutive_full_losses": int(raw["consecutive_full_losses"]),
    }


def with_pending(book: Mapping, approved_cards: Sequence[Mapping]) -> dict:
    """Book plus today's APPROVED-but-not-filled engine cards.

    Conservative: a pending_human card's heat, notional, sector and setup
    count against the next draft, so two approvals can never together exceed
    a cap if Jared approves both.
    """
    out = dict(book)
    positions = list(book["positions"])
    open_heat = rm.D(book["open_heat"])
    gross = rm.D(book["gross_long"])
    cash = rm.D(book["cash"])
    for card in approved_cards:
        sizing = card["sizing"]
        inputs = card["engine"]["inputs"]
        heat = rm.D(sizing["heat_contribution"])
        notional = rm.D(sizing["notional"])
        open_heat += heat
        if card["instrument"] == "stock":
            gross += notional
            cash -= notional
        else:
            cash -= heat
        positions.append(
            {
                "trade_id": card["trade_id"],
                "ticker": card["ticker"],
                "sector": inputs.get("sector", ""),
                "setup": card["setup"],
                "instrument": card["instrument"],
                "heat": float(heat),
                "pending": True,
            }
        )
    out["positions"] = positions
    out["open_heat"] = open_heat
    out["gross_long"] = gross
    out["buying_power"] = max(cash, Decimal("0"))
    return out


# ------------------------------------------------------------------ regime

def load_regime(repo: Path, session_date: date) -> Tuple[Optional[dict], Optional[str], List[str]]:
    """Regime snapshot for the day: inbox first (Market Read), then handoff.

    Returns (snapshot, relative_path, problems). The mode is recomputed with
    regime_to_mode(); the snapshot's derived_risk_mode is advisory only.
    """
    problems: List[str] = []
    ds = session_date.isoformat()
    for rel in (f"inbox/{ds}/regime_snapshot.json", f"handoff/{ds}/regime_snapshot.json"):
        path = repo / rel
        if not path.exists():
            continue
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{rel}: unreadable ({exc})")
            continue
        errs = schema_errors("regime_snapshot.schema.json", snap)
        if errs:
            problems.append(f"{rel}: schema {errs}")
            continue
        if snap["session_date"] != ds:
            problems.append(f"{rel}: session_date {snap['session_date']} != {ds}")
            continue
        return snap, rel, problems
    return None, None, problems


def risk_context(book: Mapping, regime: Optional[Mapping], regime_path: Optional[str]) -> dict:
    """Mode = regime_to_mode() tightened by the circuit breakers.

    No usable regime snapshot fails closed to stand_down (reason regime_missing).
    """
    if regime is None:
        regime_mode = rm.STAND_DOWN
        extra = ["regime_missing"]
        regime_info = None
    else:
        regime_mode = rm.regime_to_mode(
            regime["trend"], regime["risk_appetite"], regime["volatility"], regime["persistence"]
        )
        extra = []
        regime_info = {
            "path": regime_path,
            "trend": regime["trend"],
            "risk_appetite": regime["risk_appetite"],
            "volatility": regime["volatility"],
            "persistence": regime["persistence"],
            "regime_mode": regime_mode,
            "snapshot_derived_risk_mode": regime.get("derived_risk_mode"),
        }
    eff = rm.effective_risk_mode(
        regime_mode,
        book["day_pnl_pct"],
        book["week_pnl_pct"],
        book["drawdown_pct"],
        book["consecutive_full_losses"],
    )
    reasons = extra + [r for r in eff["reasons"] if r not in extra]
    if regime is None and "regime_stand_down" in reasons:
        reasons.remove("regime_stand_down")
    return {
        "risk_mode": eff["risk_mode"],
        "entries_allowed": eff["entries_allowed"],
        "reasons": reasons,
        "regime": regime_info,
    }


# ------------------------------------------------------------------ measurements

def load_prep_measurements(repo: Path, session_date: date) -> Tuple[Dict[str, dict], Optional[str]]:
    """Optional Mac prep file handoff/<date>/measurements.json.

    Accepts {"names": {"XYZ": {...}}} or {"names": [{"ticker": "XYZ", ...}]}.
    Missing file: empty map (the draft's own measurements are used).
    """
    rel = f"handoff/{session_date.isoformat()}/measurements.json"
    path = repo / rel
    if not path.exists():
        return {}, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"{rel} unreadable: {exc}") from exc
    names = doc.get("names") if isinstance(doc, dict) else None
    out: Dict[str, dict] = {}
    if isinstance(names, dict):
        for k, v in names.items():
            if isinstance(v, dict):
                out[str(k).upper()] = v
    elif isinstance(names, list):
        for v in names:
            if isinstance(v, dict) and v.get("ticker"):
                out[str(v["ticker"]).upper()] = v
    return out, rel


PREP_FIELDS = ("price", "atr", "adv_dollars", "spread", "spread_source", "provisional", "sector", "source", "as_of")
_PREP_ALIASES = {"adv_dollars": ("adv_dollars", "adv20_dollars")}


def resolve_measurements(draft: Mapping, prep: Mapping[str, dict], prep_rel: Optional[str]) -> dict:
    m = dict(draft["measurements"])
    used = "draft"
    row = prep.get(draft["ticker"].upper())
    if row:
        used = prep_rel or "prep"
        for field in PREP_FIELDS:
            for alias in _PREP_ALIASES.get(field, (field,)):
                if alias in row:
                    m[field] = row[alias]
                    break
    m["measurements_source"] = used
    return m


# ------------------------------------------------------------------ drafts

def draft_identity(filename: str, draft: Any) -> Tuple[Optional[str], List[str]]:
    """trade_id from the draft body, else from a <trade_id>.draft.json name."""
    reasons: List[str] = []
    stem = filename[: -len(DRAFT_SUFFIX)] if filename.endswith(DRAFT_SUFFIX) else filename
    stem_id = stem if TRADE_ID_RE.match(stem) else None
    body_id = None
    if isinstance(draft, dict) and isinstance(draft.get("trade_id"), str) and TRADE_ID_RE.match(draft["trade_id"]):
        body_id = draft["trade_id"]
    if body_id and stem_id and body_id != stem_id:
        reasons.append("trade_id_filename_mismatch")
    return body_id or stem_id, reasons


def _supports_kwarg(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def structural_inputs(draft: Mapping, m: Mapping, book: Mapping, ctx: Mapping) -> dict:
    atr = rm.D(m["atr"])
    level = rm.D(m["reference_level"])
    if draft["instrument"] == "stock":
        ref = rm.D(draft["entry"]["price"])
        stop_distance = (rm.max_buy_fill(draft["entry"]["price"]) - rm.D(draft["stop"])) / atr
    else:
        ref = rm.D(m["price"])
        stop_distance = (ref - rm.D(draft["option"]["underlying_stop"])) / atr
    extension = max(Decimal("0"), (ref - level) / atr)
    sector = str(m["sector"]).strip().lower()
    positions = book["positions"]
    kwargs = dict(
        setup=draft["setup"],
        instrument=draft["instrument"],
        direction=draft["direction"],
        catalyst_quality=draft["catalyst"]["quality"],
        earnings_in_window=bool(draft["catalyst"]["earnings_in_window"]),
        invalidation=list(draft["invalidation"]),
        fields_complete=True,
        sector_already_open=any(str(p.get("sector", "")).strip().lower() == sector for p in positions),
        setup_open_count=sum(1 for p in positions if p.get("setup") == draft["setup"]),
        open_positions=len(positions),
        risk_mode=ctx["risk_mode"],
        extension_atr=extension.quantize(Decimal("0.0001")),
        stop_distance_atr=stop_distance.quantize(Decimal("0.0001")),
        book=book["book"],
        provisional_data=m.get("provisional"),
    )
    # Forward compatible with a structural_blocks that also takes spread_source
    # (modeled spreads are live-blocked). Only passed when the signature has it.
    if m.get("spread_source") is not None and _supports_kwarg(rm.structural_blocks, "spread_source"):
        kwargs["spread_source"] = m.get("spread_source")
    return kwargs


def extra_validation(draft: Mapping, session_date: date, book: Mapping) -> List[str]:
    """Draft checks the governor does not do. Any hit rejects the draft."""
    reasons: List[str] = []
    if draft.get("book") and draft["book"] != book["book"]:
        reasons.append("book_mismatch")
    if draft["trade_id"][3:7] != f"{session_date.year:04d}":
        reasons.append("trade_id_year_mismatch")
    ts = draft["time_stop"]
    try:
        entry_d = date.fromisoformat(ts["entry_session_date"])
        exit_d = date.fromisoformat(ts["exit_session_date"])
    except ValueError:
        reasons.append("time_stop_invalid")
    else:
        if entry_d < session_date or not (entry_d < exit_d <= entry_d + timedelta(days=7)) or exit_d.weekday() >= 5:
            reasons.append("time_stop_invalid")
    if "time_stop" not in draft["invalidation"] or "stop_hit" not in draft["invalidation"]:
        reasons.append("invalidation_not_machine_checkable")
    return reasons


def _sizing_block(size: Mapping, book: Mapping) -> dict:
    return {
        "equity_at_decision": to_json_number(rm.money(book["equity"])),
        "units": int(size["units"]),
        "planned_loss": to_json_number(rm.money(size["planned_loss"])),
        "heat_contribution": to_json_number(rm.money(size["heat_contribution"])),
        "open_heat_before": to_json_number(rm.money(book["open_heat"])),
        "book_heat_cap": to_json_number(rm.money(size["book_heat_cap"])),
        "name_heat_cap": to_json_number(rm.money(size["name_heat_cap"])),
        "notional": to_json_number(rm.money(size["notional"])),
        "gap_multiplier": to_json_number(rm.D(size["gap_multiplier"])),
        "expected_reward": to_json_number(rm.money(size["expected_reward"])),
        "expected_r": to_json_number(size["expected_r"]),
        "initial_risk": to_json_number(size["initial_risk"]) if size.get("initial_risk") else None,
    }


def zero_sizing(instrument: str, book: Mapping, ctx: Mapping) -> dict:
    """Governor-shaped empty size: caps populated, zero units. Never a model's numbers."""
    limit = rm.caps(book["equity"], ctx["risk_mode"], 0)
    size = {
        "units": 0,
        "planned_loss": Decimal("0"),
        "heat_contribution": Decimal("0"),
        "notional": Decimal("0"),
        "expected_reward": Decimal("0"),
        "expected_r": None,
        "initial_risk": None,
        "gap_multiplier": rm.GAP_MULTIPLIER_STOCK if instrument == "stock" else Decimal("1"),
        **limit,
    }
    return _sizing_block(size, book)


def run_governor(draft: Mapping, m: Mapping, book: Mapping, ctx: Mapping) -> dict:
    """structural_blocks, then size_stock / size_option on max_buy_fill."""
    max_fill = rm.max_buy_fill(draft["entry"]["price"])
    s_kwargs = structural_inputs(draft, m, book, ctx)
    blocks = rm.structural_blocks(**s_kwargs)
    inputs = {
        "structural": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in s_kwargs.items()},
        "max_fill": str(max_fill),
    }
    if blocks:
        return {"blocked": True, "reasons": blocks, "size": None, "max_fill": max_fill, "inputs": inputs}
    if draft["instrument"] == "stock":
        kwargs = dict(
            equity=book["equity"],
            entry=max_fill,
            stop=rm.D(draft["stop"]),
            target=rm.D(draft["targets"][0]["price"]),
            atr=rm.D(m["atr"]),
            price=rm.D(m["price"]),
            adv_dollars=rm.D(m["adv_dollars"]),
            spread=None if m.get("spread") is None else rm.D(m["spread"]),
            open_heat=book["open_heat"],
            buying_power=book["buying_power"],
            gross_long=book["gross_long"],
            risk_mode=ctx["risk_mode"],
            warning_count=0,
        )
        size = rm.size_stock(**kwargs)
    else:
        opt = draft["option"]
        kwargs = dict(
            equity=book["equity"],
            debit=max_fill,
            stop_premium=rm.D(draft["stop"]),
            target_premium=rm.D(draft["targets"][0]["price"]),
            open_heat=book["open_heat"],
            buying_power=book["buying_power"],
            risk_mode=ctx["risk_mode"],
            warning_count=0,
            open_interest=int(opt["open_interest"]),
            volume=int(opt["volume"]),
            bid=rm.D(opt["bid"]),
            ask=rm.D(opt["ask"]),
        )
        size = rm.size_option(**kwargs)
    inputs["sizing"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in kwargs.items()}
    return {"blocked": False, "reasons": list(size["reasons"]), "size": size, "max_fill": max_fill, "inputs": inputs}


def _engine_block(*, outcome: str, reasons: Sequence[str], session_date: date, draft_file: str,
                  draft_sha: str, first_seen: datetime, cutoff: datetime, carded_at: datetime,
                  book: Mapping, inputs: Mapping) -> dict:
    return {
        "engine_version": ENGINE_VERSION,
        "outcome": outcome,
        "reasons": list(reasons),
        "session_date": session_date.isoformat(),
        "draft_file": draft_file,
        "draft_sha256": draft_sha,
        "first_seen_at": iso(first_seen),
        "cutoff": iso(cutoff),
        "carded_at": iso(carded_at),
        "book": book["book"],
        "inputs": dict(inputs),
    }


def _card_shell(draft: Mapping, max_fill: Decimal, now: datetime) -> dict:
    return {
        "schema_version": "1.0.0",
        "trade_id": draft["trade_id"],
        "version": 1,
        "status": "candidate",
        "ticker": draft["ticker"],
        "setup": draft["setup"],
        "direction": draft["direction"],
        "instrument": draft["instrument"],
        "catalyst": dict(draft["catalyst"]),
        "why_now": draft["why_now"],
        "entry": {
            "trigger": draft["entry"]["trigger"],
            "price": draft["entry"]["price"],
            "max_fill": to_json_number(max_fill),
        },
        "stop": draft["stop"],
        "targets": [dict(t) for t in draft["targets"]],
        "time_stop": dict(draft["time_stop"]),
        "sizing": None,
        "invalidation": list(draft["invalidation"]),
        "invalidation_level": draft["invalidation_level"],
        "evidence": dict(draft["evidence"]),
        "red_team": None,
        "risk_decision": None,
        "human_decision": None,
        "watcher": None,
        "created_at": iso(now),
        "frozen_at": iso(now),
    }


RED_TEAM_PENDING = {
    "decision": "pending",
    "hard_blocks": [],
    "warnings": [],
    "narrative": "Red team pending (08:18-08:25 CT). The engine froze this card before red team review; "
    "warnings recorded later do not change this card's size.",
}


def build_card(*, draft: Mapping, outcome_hint: Optional[str], extra_reasons: Sequence[str],
               session_date: date, draft_file: str, draft_sha: str, first_seen: datetime,
               clock: SessionClock, now: datetime, book: Mapping, ctx: Mapping, measurements: Optional[Mapping]) -> dict:
    """Card for a draft that passed trade_draft.schema.json.

    outcome_hint "late": not sized, risk_decision null.
    extra_reasons non-empty: rejected before the governor (pre-sized, bad
    time stop, ...), never sized. Otherwise the governor decides.
    """
    max_fill = rm.max_buy_fill(draft["entry"]["price"])
    card = _card_shell(draft, max_fill, now)
    inputs: Dict[str, Any] = {
        "sector": (measurements or draft["measurements"]).get("sector"),
        "book_as_of": book.get("as_of"),
        "risk_context": {k: ctx[k] for k in ("risk_mode", "entries_allowed", "reasons", "regime")},
        "measurements": {k: v for k, v in (measurements or {}).items()},
        "market_data_network_calls": 0,
    }
    if draft.get("option"):
        inputs["option"] = dict(draft["option"])
    common = dict(session_date=session_date, draft_file=draft_file, draft_sha=draft_sha,
                  first_seen=first_seen, cutoff=clock.cutoff, carded_at=now, book=book)

    if outcome_hint == OUTCOME_LATE:
        card["status"] = "blocked"
        card["sizing"] = zero_sizing(draft["instrument"], book, ctx)
        card["red_team"] = {"decision": "block", "hard_blocks": ["late_draft"], "warnings": [],
                            "narrative": "Draft first seen after the cutoff. Not sized. No post-open pass."}
        card["risk_decision"] = None
        card["engine"] = _engine_block(outcome=OUTCOME_LATE, reasons=["late_draft"], inputs=inputs, **common)
        return card

    if extra_reasons:
        reasons = list(dict.fromkeys(extra_reasons))
        card["status"] = "blocked"
        card["sizing"] = zero_sizing(draft["instrument"], book, ctx)
        card["red_team"] = {"decision": "block", "hard_blocks": reasons, "warnings": [],
                            "narrative": "Engine rejected the draft before sizing."}
        card["risk_decision"] = {"decision": "REJECTED", "reasons": reasons,
                                 "risk_mode": ctx["risk_mode"], "entries_allowed": ctx["entries_allowed"]}
        card["engine"] = _engine_block(outcome=OUTCOME_REJECTED, reasons=reasons, inputs=inputs, **common)
        return card

    gov = run_governor(draft, measurements, book, ctx)
    inputs["governor"] = gov["inputs"]
    mode_reasons = [] if ctx["entries_allowed"] else list(ctx["reasons"])
    if gov["blocked"]:
        reasons = list(dict.fromkeys(gov["reasons"] + mode_reasons))
        card["status"] = "blocked"
        card["sizing"] = zero_sizing(draft["instrument"], book, ctx)
        card["red_team"] = {"decision": "block", "hard_blocks": list(gov["reasons"]), "warnings": [],
                            "narrative": "Engine hard block (structural_blocks)."}
        card["risk_decision"] = {"decision": "REJECTED", "reasons": reasons,
                                 "risk_mode": ctx["risk_mode"], "entries_allowed": ctx["entries_allowed"]}
        card["engine"] = _engine_block(outcome=OUTCOME_REJECTED, reasons=reasons, inputs=inputs, **common)
        return card

    size = gov["size"]
    card["sizing"] = _sizing_block(size, book)
    if size["approved"] and int(size["units"]) >= 1:
        card["status"] = "pending_human"
        card["red_team"] = dict(RED_TEAM_PENDING)
        card["risk_decision"] = {"decision": "APPROVED", "reasons": [],
                                 "risk_mode": ctx["risk_mode"], "entries_allowed": ctx["entries_allowed"]}
        card["engine"] = _engine_block(outcome=OUTCOME_SIZED, reasons=[], inputs=inputs, **common)
        return card
    reasons = list(dict.fromkeys(list(size["reasons"]) + mode_reasons)) or ["size_zero"]
    card["status"] = "risk_rejected"
    card["red_team"] = dict(RED_TEAM_PENDING)
    card["risk_decision"] = {"decision": "REJECTED", "reasons": reasons,
                             "risk_mode": ctx["risk_mode"], "entries_allowed": ctx["entries_allowed"]}
    card["engine"] = _engine_block(outcome=OUTCOME_REJECTED, reasons=reasons, inputs=inputs, **common)
    return card


def reject_record(*, trade_id: Optional[str], ticker: Optional[str], reasons: Sequence[str],
                  session_date: date, draft_file: str, draft_sha: str, first_seen: datetime,
                  clock: SessionClock, now: datetime, book_name: str, ctx: Mapping,
                  inputs: Optional[Mapping] = None, late: bool = False) -> dict:
    """Record for a draft too broken to card (or a card that failed its schema)."""
    reasons = list(dict.fromkeys(reasons)) or ["draft_invalid"]
    if late and "late_draft" not in reasons:
        reasons.insert(0, "late_draft")
    outcome = OUTCOME_LATE if late else OUTCOME_REJECTED
    risk_decision = None if late else {"decision": "REJECTED", "reasons": reasons,
                                       "risk_mode": ctx["risk_mode"], "entries_allowed": ctx["entries_allowed"]}
    engine = _engine_block(outcome=outcome, reasons=reasons, session_date=session_date,
                           draft_file=draft_file, draft_sha=draft_sha, first_seen=first_seen,
                           cutoff=clock.cutoff, carded_at=now, book={"book": book_name},
                           inputs=dict(inputs or {}, market_data_network_calls=0))
    return {
        "schema_version": "1.0.0",
        "record": "engine_reject",
        "trade_id": trade_id,
        "ticker": ticker if isinstance(ticker, str) else None,
        "status": "blocked",
        "risk_decision": risk_decision,
        "engine": engine,
    }

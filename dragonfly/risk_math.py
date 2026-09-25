"""Normative risk math for Dragonfly 7.

The operating plan in docs/dragonfly/DRAGONFLY_7_OPERATING_PLAN.md explains
these rules. If the prose and this module disagree, this module and
dragonfly/test_risk_math.py win, and the prose gets patched.

Money is decimal dollars, half-up to the cent on stored amounts. Share and
contract counts are floored. Caps that limit a budget are rounded down so a
rounding choice cannot push heat through a ceiling.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Iterable, Mapping, Optional, Sequence

CENT = Decimal("0.01")
R_QUANTUM = Decimal("0.0001")

NORMAL = "normal"
CAUTIOUS = "cautious"
STAND_DOWN = "stand_down"
MODES = (NORMAL, CAUTIOUS, STAND_DOWN)

GAP_MULTIPLIER_STOCK = Decimal("1.5")
MIN_RR = Decimal("1.5")
MIN_PRICE = Decimal("10")
MIN_ADV_DOLLARS = Decimal("25000000")
NOTIONAL_CAP_PCT = Decimal("0.20")
GROSS_EXPOSURE_CAP_PCT = Decimal("1")
ADV_PARTICIPATION_PCT = Decimal("0.02")
MAX_ENTRY_SLIPPAGE = Decimal("0.0015")
MIN_STOP_ATR = Decimal("0.4")
MAX_STOP_ATR = Decimal("2.0")
MAX_EXTENSION_ATR = Decimal("1.0")
MAX_POSITIONS = 4
MAX_PER_SETUP = 2
DAY_HALT_PCT = Decimal("-0.01")
WEEK_HALT_PCT = Decimal("-0.02")
DRAWDOWN_CAUTIOUS_PCT = Decimal("0.08")
DRAWDOWN_HALT_PCT = Decimal("0.12")
LOSS_STREAK_HALT = 4
WARNING_TIGHTEN_AT = 2
OPTION_MULTIPLIER = 100
MAX_OPTION_SPREAD_PCT = Decimal("0.10")
MIN_OPTION_OPEN_INTEREST = 100
MIN_OPTION_VOLUME = 50
# Universe stock spread gate: spread <= the wider of $0.05 and 0.15% of price.
MAX_STOCK_SPREAD_ABS = Decimal("0.05")
MAX_STOCK_SPREAD_PCT = Decimal("0.0015")

# Books. Phase 1 is paper. A live card must say so explicitly (book="live").
PAPER = "paper"
LIVE = "live"
BOOKS = (PAPER, LIVE)

# Planning haircut used only to translate the design hypothesis into a weekly
# rate. It is not a fill model. Live expectancy uses measured net R.
DESIGN_WIN_RATE = Decimal("0.45")
DESIGN_AVG_WIN_R = Decimal("2")
DESIGN_AVG_LOSS_R = Decimal("1")
DESIGN_FRICTION_R = Decimal("0.08")

_MODE_RANK = {NORMAL: 0, CAUTIOUS: 1, STAND_DOWN: 2}

_CAPS = {
    NORMAL: {
        "planned": Decimal("0.01"),
        "name_heat": Decimal("0.01"),
        "book_heat": Decimal("0.02"),
    },
    CAUTIOUS: {
        "planned": Decimal("0.005"),
        "name_heat": Decimal("0.005"),
        "book_heat": Decimal("0.01"),
    },
    STAND_DOWN: {
        "planned": Decimal("0"),
        "name_heat": Decimal("0"),
        "book_heat": Decimal("0"),
    },
}

SETUPS = (
    "catalyst_breakout",
    "momentum_pullback",
    "failed_breakdown",
    "compression_expansion",
)
SETUPS_REQUIRING_PRIMARY = {"catalyst_breakout"}
SETUPS_REQUIRING_CATALYST = {"catalyst_breakout", "failed_breakdown"}
ALLOWED_INSTRUMENTS = {"stock", "call", "put", "debit_spread"}
ALLOWED_INVALIDATION = {"stop_hit", "level_lost", "time_stop", "catalyst_retracted"}
ALLOWED_EXIT_REASONS = {"stop", "target", "time", "invalidation", "human_tighten"}


def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money_down(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_FLOOR)


def q_r(value) -> Decimal:
    return D(value).quantize(R_QUANTUM, rounding=ROUND_HALF_UP)


def _floor_units(budget: Decimal, unit_risk: Decimal) -> int:
    if unit_risk <= 0 or budget <= 0:
        return 0
    return int((budget / unit_risk).to_integral_value(rounding=ROUND_FLOOR))


def stock_spread_limit(price) -> Decimal:
    """Widest legal stock spread at this price: max($0.05, 0.15% of price)."""
    return max(MAX_STOCK_SPREAD_ABS, MAX_STOCK_SPREAD_PCT * D(price))


def universe_reasons(price, adv_dollars, spread) -> list[str]:
    """Stock universe gates from the operating plan, in the governor's order.

    `spread` of None means the bid/ask was not observed. That fails closed as
    `spread_unavailable`; an unmeasured name never passes the spread gate.
    """
    reasons = []
    if price is None or D(price) < MIN_PRICE:
        reasons.append("price_below_minimum")
    if adv_dollars is None or D(adv_dollars) < MIN_ADV_DOLLARS:
        reasons.append("adv_below_minimum")
    if spread is None:
        reasons.append("spread_unavailable")
    elif price is None or D(spread) > stock_spread_limit(price):
        reasons.append("spread_too_wide")
    return reasons


def sources_provisional(sources: Optional[Iterable[Mapping]]) -> bool:
    """True unless every data source is explicitly stamped provisional=False.

    No sources, a source without a `provisional` flag, or any source stamped
    provisional (for example Yahoo via yfinance) counts as provisional.
    """
    if not sources:
        return True
    seen = False
    for source in sources:
        seen = True
        if not isinstance(source, Mapping) or source.get("provisional") is not False:
            return True
    return not seen


def tighter_mode(current: str, proposed: str) -> str:
    if current not in _MODE_RANK or proposed not in _MODE_RANK:
        raise ValueError(f"unknown risk mode: {current!r} / {proposed!r}")
    return current if _MODE_RANK[current] >= _MODE_RANK[proposed] else proposed


def regime_to_mode(
    trend: str,
    risk_appetite: str,
    volatility: str,
    persistence: str,
) -> str:
    """Map a regime classification to a risk mode. Classification is an input.

    The regime agent may only emit the enums documented in the operating plan.
    This function, not the agent, sets the mode.
    """
    if volatility == "high" and risk_appetite == "risk_off":
        return STAND_DOWN
    if (
        volatility == "high"
        or risk_appetite == "risk_off"
        or persistence == "mean_reverting"
        or (trend == "range" and persistence != "persistent")
    ):
        return CAUTIOUS
    return NORMAL


def effective_risk_mode(
    regime_mode: str,
    day_pnl_pct,
    week_pnl_pct,
    drawdown_pct,
    consecutive_full_losses: int,
) -> dict:
    """Tightest ceiling wins. Halt conditions stand the book down for new risk."""
    reasons = []
    mode = regime_mode
    if D(day_pnl_pct) <= DAY_HALT_PCT:
        mode = STAND_DOWN
        reasons.append("day_halt")
    if D(week_pnl_pct) <= WEEK_HALT_PCT:
        mode = STAND_DOWN
        reasons.append("week_halt")
    if D(drawdown_pct) >= DRAWDOWN_HALT_PCT:
        mode = STAND_DOWN
        reasons.append("drawdown_halt")
    if D(drawdown_pct) >= DRAWDOWN_CAUTIOUS_PCT and mode != STAND_DOWN:
        mode = tighter_mode(mode, CAUTIOUS)
        reasons.append("drawdown_cautious")
    elif D(drawdown_pct) >= DRAWDOWN_CAUTIOUS_PCT and "drawdown_halt" not in reasons:
        reasons.append("drawdown_cautious")
    if consecutive_full_losses >= LOSS_STREAK_HALT and mode != STAND_DOWN:
        mode = tighter_mode(mode, CAUTIOUS)
        reasons.append("streak_cautious")
    elif consecutive_full_losses >= LOSS_STREAK_HALT:
        reasons.append("streak_cautious")
    if regime_mode == STAND_DOWN and "regime_stand_down" not in reasons:
        reasons.append("regime_stand_down")
    return {"risk_mode": mode, "reasons": reasons, "entries_allowed": mode != STAND_DOWN}


def caps(equity, risk_mode: str, warning_count: int = 0) -> dict:
    if risk_mode not in _CAPS:
        raise ValueError(f"unknown risk mode: {risk_mode}")
    equity = D(equity)
    base = _CAPS[risk_mode]
    planned_pct = base["planned"]
    name_pct = base["name_heat"]
    book_pct = base["book_heat"]
    warnings_tightened = False
    if warning_count >= WARNING_TIGHTEN_AT and risk_mode == NORMAL:
        planned_pct = _CAPS[CAUTIOUS]["planned"]
        name_pct = _CAPS[CAUTIOUS]["name_heat"]
        warnings_tightened = True
    return {
        "planned_cap": money(equity * planned_pct),
        "name_heat_cap": money(equity * name_pct),
        "book_heat_cap": money(equity * book_pct),
        "warnings_tightened": warnings_tightened,
    }


def _budget_stock(limit_caps: Mapping, open_heat) -> Decimal:
    gap = GAP_MULTIPLIER_STOCK
    remaining = D(limit_caps["book_heat_cap"]) - D(open_heat)
    if remaining <= 0 or limit_caps["planned_cap"] <= 0:
        return Decimal("0")
    raw = min(
        D(limit_caps["planned_cap"]),
        D(limit_caps["name_heat_cap"]) / gap,
        remaining / gap,
    )
    return money_down(raw)


def design_expectancy_r() -> dict:
    """Illustration only. Not a forecast and not a weekly quota."""
    gross = DESIGN_WIN_RATE * DESIGN_AVG_WIN_R - (1 - DESIGN_WIN_RATE) * DESIGN_AVG_LOSS_R
    net = gross - DESIGN_FRICTION_R
    return {"gross_r": q_r(gross), "friction_r": DESIGN_FRICTION_R, "net_r": q_r(net)}


def r_multiple(net_pnl, initial_risk) -> Decimal:
    """R uses planned dollar risk locked at the fill. Losses worse than -1R stay."""
    risk = D(initial_risk)
    if risk <= 0:
        raise ValueError("initial_risk must be positive")
    return q_r(D(net_pnl) / risk)


def expectancy(rs: Sequence) -> Optional[Decimal]:
    if not rs:
        return None
    total = sum((D(r) for r in rs), Decimal("0"))
    return q_r(total / Decimal(len(rs)))


def max_buy_fill(trigger) -> Decimal:
    return money(D(trigger) * (1 + MAX_ENTRY_SLIPPAGE))


def fill_acceptable(trigger, fill) -> bool:
    return D(fill) <= max_buy_fill(trigger)


def time_stop_session(entry_session: date, sessions: Iterable[date]) -> date:
    """Last NYSE session after entry and on or before entry + 7 calendar days."""
    deadline = entry_session + timedelta(days=7)
    candidates = [s for s in sessions if entry_session < s <= deadline]
    if not candidates:
        raise ValueError(
            f"no session after {entry_session.isoformat()} on or before {deadline.isoformat()}"
        )
    return max(candidates)


def weekly_scoreboard(trade_rs: Sequence, equity_start, net_pnl) -> dict:
    """R is the score. Dollars are a translation. There is no deficit to target."""
    equity_start = D(equity_start)
    net = money(net_pnl)
    return {
        "trades": len(trade_rs),
        "r_sum": q_r(sum((D(r) for r in trade_rs), Decimal("0"))) if trade_rs else Decimal("0.0000"),
        "expectancy_r": expectancy(trade_rs),
        "net_pnl": net,
        "net_pnl_pct": q_r(net / equity_start) if equity_start else None,
        "flat_week_is_success": True,
    }


def structural_blocks(
    *,
    setup: str,
    instrument: str,
    direction: str,
    catalyst_quality: str,
    earnings_in_window: bool,
    invalidation: Sequence[str],
    fields_complete: bool,
    sector_already_open: bool,
    setup_open_count: int,
    open_positions: int,
    risk_mode: str,
    extension_atr,
    stop_distance_atr,
    book: str = PAPER,
    provisional_data: Optional[bool] = None,
) -> list[str]:
    """Deterministic hard blocks. A language model cannot clear these.

    Provenance: a card on the live book is blocked unless its data is known
    to be non-provisional (`provisional_data is False`). Unknown provenance
    (None) counts as provisional. Paper cards may use provisional data.
    """
    reasons = []
    if book not in BOOKS:
        reasons.append("unknown_book")
    elif book == LIVE and provisional_data is not False:
        reasons.append("provisional_source_live")
    if not fields_complete:
        reasons.append("missing_field")
    if setup not in SETUPS:
        reasons.append("unknown_setup")
    if instrument not in ALLOWED_INSTRUMENTS:
        reasons.append("instrument_not_allowed")
    if direction != "long":
        reasons.append("short_stock_forbidden" if instrument == "stock" else "direction_not_long")
    if instrument == "stock" and earnings_in_window:
        reasons.append("earnings_stock_forbidden")
    if setup in SETUPS_REQUIRING_PRIMARY and catalyst_quality != "primary":
        reasons.append("catalyst_insufficient")
    elif setup in SETUPS_REQUIRING_CATALYST and catalyst_quality not in {"primary", "secondary"}:
        reasons.append("catalyst_insufficient")
    if not invalidation or any(code not in ALLOWED_INVALIDATION for code in invalidation):
        reasons.append("invalidation_not_machine_checkable")
    if "stop_hit" not in invalidation or "time_stop" not in invalidation:
        reasons.append("invalidation_not_machine_checkable")
    if sector_already_open:
        reasons.append("sector_occupied")
    if setup_open_count >= MAX_PER_SETUP:
        reasons.append("setup_cap")
    if open_positions >= MAX_POSITIONS:
        reasons.append("position_cap")
    if risk_mode == STAND_DOWN:
        reasons.append("stand_down")
    if D(extension_atr) > MAX_EXTENSION_ATR:
        reasons.append("extended")
    if D(stop_distance_atr) < MIN_STOP_ATR or D(stop_distance_atr) > MAX_STOP_ATR:
        reasons.append("stop_distance_atr")
    # de-duplicate while preserving order
    seen = set()
    unique = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)
    return unique


def size_stock(
    *,
    equity,
    entry,
    stop,
    target,
    atr,
    price,
    adv_dollars,
    spread,
    open_heat,
    buying_power,
    gross_long,
    risk_mode: str,
    warning_count: int = 0,
) -> dict:
    """Size a long stock. Heat is 1.5× planned stop loss because stops gap.

    For a buy stop, pass `entry` as the worst acceptable fill (`max_buy_fill`),
    not the trigger. That keeps a slippage-worse fill inside the heat cap.
    """
    reasons: list[str] = []
    entry = D(entry)
    stop = D(stop)
    target = D(target)
    atr = D(atr)
    price = D(price)
    distance = entry - stop
    reward = target - entry

    reasons.extend(universe_reasons(price, adv_dollars, spread))
    if distance <= 0:
        reasons.append("stop_not_below_entry")
    if atr <= 0:
        reasons.append("atr_missing")
    elif distance > 0 and (distance < MIN_STOP_ATR * atr or distance > MAX_STOP_ATR * atr):
        reasons.append("stop_distance_atr")
    if distance > 0 and reward / distance < MIN_RR:
        reasons.append("reward_risk_below_minimum")
    if risk_mode == STAND_DOWN:
        reasons.append("stand_down")

    limit_caps = caps(equity, risk_mode, warning_count)
    budget = _budget_stock(limit_caps, open_heat)
    if budget <= 0 and "stand_down" not in reasons:
        reasons.append("heat_exhausted")

    if reasons:
        return _empty_size("stock", limit_caps, reasons, gap_multiplier=GAP_MULTIPLIER_STOCK)

    shares = _floor_units(budget, distance)
    notional_cap = D(equity) * NOTIONAL_CAP_PCT
    gross_room = D(equity) * GROSS_EXPOSURE_CAP_PCT - D(gross_long)
    shares = min(
        shares,
        _floor_units(notional_cap, entry),
        _floor_units(D(buying_power), entry),
        _floor_units(gross_room, entry) if gross_room > 0 else 0,
        _floor_units(D(adv_dollars) * ADV_PARTICIPATION_PCT, entry),
    )
    if shares < 1:
        return _empty_size(
            "stock",
            limit_caps,
            ["size_zero"],
            gap_multiplier=GAP_MULTIPLIER_STOCK,
        )

    planned = money(Decimal(shares) * distance)
    heat = money(planned * GAP_MULTIPLIER_STOCK)
    while shares > 0 and (
        heat > limit_caps["name_heat_cap"]
        or D(open_heat) + heat > limit_caps["book_heat_cap"]
    ):
        shares -= 1
        planned = money(Decimal(shares) * distance)
        heat = money(planned * GAP_MULTIPLIER_STOCK)
    if shares < 1:
        return _empty_size(
            "stock",
            limit_caps,
            ["heat_exhausted"],
            gap_multiplier=GAP_MULTIPLIER_STOCK,
        )

    expected_reward = money(Decimal(shares) * reward)
    return {
        "approved": True,
        "reasons": [],
        "instrument": "stock",
        "units": shares,
        "planned_loss": planned,
        "heat_contribution": heat,
        "notional": money(Decimal(shares) * entry),
        "expected_reward": expected_reward,
        "expected_r": q_r(reward / distance),
        "gap_multiplier": GAP_MULTIPLIER_STOCK,
        "initial_risk": planned,
        **limit_caps,
    }


def size_option(
    *,
    equity,
    debit,
    stop_premium,
    target_premium,
    open_heat,
    buying_power,
    risk_mode: str,
    warning_count: int = 0,
    open_interest: int,
    volume: int,
    bid,
    ask,
    multiplier: int = OPTION_MULTIPLIER,
) -> dict:
    """Defined-risk long option or debit spread. Heat is the full debit."""
    reasons: list[str] = []
    debit = D(debit)
    stop_premium = D(stop_premium)
    target_premium = D(target_premium)
    bid = D(bid)
    ask = D(ask)
    mult = Decimal(multiplier)

    if debit <= 0 or stop_premium < 0 or stop_premium >= debit:
        reasons.append("option_stop_invalid")
    if target_premium <= debit:
        reasons.append("reward_risk_below_minimum")
    mid = (bid + ask) / 2 if bid > 0 and ask >= bid else Decimal("0")
    if bid <= 0 or ask < bid or mid <= 0 or (ask - bid) / mid > MAX_OPTION_SPREAD_PCT:
        reasons.append("option_spread_too_wide")
    if open_interest < MIN_OPTION_OPEN_INTEREST:
        reasons.append("option_open_interest")
    if volume < MIN_OPTION_VOLUME:
        reasons.append("option_volume")
    if risk_mode == STAND_DOWN:
        reasons.append("stand_down")

    planned_per = money((debit - stop_premium) * mult) if debit > stop_premium >= 0 else Decimal("0")
    max_loss_per = money(debit * mult) if debit > 0 else Decimal("0")
    reward_per = money((target_premium - debit) * mult) if target_premium > debit else Decimal("0")
    if planned_per > 0 and reward_per / planned_per < MIN_RR:
        reasons.append("reward_risk_below_minimum")

    limit_caps = caps(equity, risk_mode, warning_count)
    remaining = D(limit_caps["book_heat_cap"]) - D(open_heat)
    if remaining <= 0 or limit_caps["planned_cap"] <= 0:
        if "stand_down" not in reasons:
            reasons.append("heat_exhausted")

    if reasons:
        return _empty_size("option", limit_caps, reasons, gap_multiplier=Decimal("1"))

    contracts = min(
        _floor_units(limit_caps["planned_cap"], planned_per),
        _floor_units(limit_caps["name_heat_cap"], max_loss_per),
        _floor_units(remaining, max_loss_per),
        _floor_units(D(buying_power), max_loss_per),
    )
    if contracts < 1:
        return _empty_size("option", limit_caps, ["size_zero"], gap_multiplier=Decimal("1"))

    planned = money(Decimal(contracts) * planned_per)
    heat = money(Decimal(contracts) * max_loss_per)
    while contracts > 0 and (
        planned > limit_caps["planned_cap"]
        or heat > limit_caps["name_heat_cap"]
        or D(open_heat) + heat > limit_caps["book_heat_cap"]
    ):
        contracts -= 1
        planned = money(Decimal(contracts) * planned_per)
        heat = money(Decimal(contracts) * max_loss_per)
    if contracts < 1:
        return _empty_size("option", limit_caps, ["heat_exhausted"], gap_multiplier=Decimal("1"))

    expected_reward = money(Decimal(contracts) * reward_per)
    return {
        "approved": True,
        "reasons": [],
        "instrument": "option",
        "units": contracts,
        "planned_loss": planned,
        "heat_contribution": heat,
        "notional": heat,
        "structural_max_loss": heat,
        "expected_reward": expected_reward,
        "expected_r": q_r(reward_per / planned_per),
        "gap_multiplier": Decimal("1"),
        "initial_risk": planned,
        **limit_caps,
    }


def _empty_size(instrument: str, limit_caps: Mapping, reasons: list[str], gap_multiplier: Decimal) -> dict:
    seen = []
    for reason in reasons:
        if reason not in seen:
            seen.append(reason)
    return {
        "approved": False,
        "reasons": seen,
        "instrument": instrument,
        "units": 0,
        "planned_loss": Decimal("0.00"),
        "heat_contribution": Decimal("0.00"),
        "notional": Decimal("0.00"),
        "expected_reward": Decimal("0.00"),
        "expected_r": None,
        "gap_multiplier": gap_multiplier,
        "initial_risk": None,
        **limit_caps,
    }


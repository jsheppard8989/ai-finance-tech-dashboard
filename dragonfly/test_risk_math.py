"""Vectors for the Dragonfly 7 risk constitution. Run: python3 dragonfly/test_risk_math.py"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dragonfly.risk_math import (  # noqa: E402
    caps,
    design_expectancy_r,
    effective_risk_mode,
    fill_acceptable,
    max_buy_fill,
    money,
    r_multiple,
    regime_to_mode,
    size_option,
    size_stock,
    structural_blocks,
    time_stop_session,
    weekly_scoreboard,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "docs" / "dragonfly" / "schemas"
EXAMPLES = ROOT / "docs" / "dragonfly" / "examples"


def stock(**overrides):
    base = dict(
        equity=Decimal("100000"),
        entry=Decimal("84.63"),
        stop=Decimal("80.75"),
        target=Decimal("91.00"),
        atr=Decimal("4"),
        price=Decimal("84.63"),
        adv_dollars=Decimal("50000000"),
        spread=Decimal("0.02"),
        open_heat=Decimal("0"),
        buying_power=Decimal("100000"),
        gross_long=Decimal("0"),
        risk_mode="normal",
        warning_count=0,
    )
    base.update(overrides)
    return size_stock(**base)


def option(**overrides):
    base = dict(
        equity=Decimal("100000"),
        debit=Decimal("2.50"),
        stop_premium=Decimal("1.50"),
        target_premium=Decimal("4.00"),
        open_heat=Decimal("0"),
        buying_power=Decimal("100000"),
        risk_mode="normal",
        warning_count=0,
        open_interest=500,
        volume=200,
        bid=Decimal("2.45"),
        ask=Decimal("2.55"),
    )
    base.update(overrides)
    return size_option(**base)


def blocks(**overrides):
    base = dict(
        setup="catalyst_breakout",
        instrument="stock",
        direction="long",
        catalyst_quality="primary",
        earnings_in_window=False,
        invalidation=("stop_hit", "level_lost", "time_stop", "catalyst_retracted"),
        fields_complete=True,
        sector_already_open=False,
        setup_open_count=0,
        open_positions=0,
        risk_mode="normal",
        extension_atr=Decimal("0.4"),
        stop_distance_atr=Decimal("0.94"),
    )
    base.update(overrides)
    return structural_blocks(**base)


def main() -> None:
    xyz = stock()
    assert xyz["approved"] is True
    assert xyz["units"] == 171
    assert xyz["planned_loss"] == Decimal("663.48")
    assert xyz["heat_contribution"] == Decimal("995.22")
    assert xyz["notional"] == Decimal("14471.73")
    assert xyz["expected_reward"] == Decimal("1089.27")
    assert xyz["expected_r"] == Decimal("1.6418")
    assert xyz["initial_risk"] == Decimal("663.48")

    # Outline's $1,000 risk does not fit the per-name heat cap.
    assert xyz["planned_loss"] < Decimal("1000")
    assert xyz["heat_contribution"] <= xyz["name_heat_cap"]

    crowded = stock(open_heat=Decimal("1500"))
    assert crowded["approved"] is True
    assert crowded["units"] == 85
    assert crowded["planned_loss"] == Decimal("329.80")
    assert crowded["heat_contribution"] == Decimal("494.70")
    assert Decimal("1500") + crowded["heat_contribution"] <= crowded["book_heat_cap"]

    warned = stock(warning_count=2)
    assert warned["warnings_tightened"] is True
    assert warned["units"] == 85
    assert warned["planned_loss"] == Decimal("329.80")
    assert warned["name_heat_cap"] == Decimal("500.00")
    assert warned["book_heat_cap"] == Decimal("2000.00")

    cautious = stock(risk_mode="cautious")
    assert cautious["approved"] is True
    assert cautious["planned_cap"] == Decimal("500.00")
    assert cautious["book_heat_cap"] == Decimal("1000.00")
    assert cautious["units"] == 85
    assert cautious["heat_contribution"] == Decimal("494.70")

    halted = stock(risk_mode="stand_down")
    assert halted["approved"] is False
    assert halted["reasons"] == ["stand_down"]

    wide_stop = stock(atr=Decimal("10"))
    assert wide_stop["approved"] is False
    assert "stop_distance_atr" in wide_stop["reasons"]

    poor_rr = stock(target=Decimal("88"))
    assert poor_rr["approved"] is False
    assert "reward_risk_below_minimum" in poor_rr["reasons"]

    penny = stock(price=Decimal("9"), entry=Decimal("9"), stop=Decimal("8"), target=Decimal("11"), atr=Decimal("1.5"))
    assert penny["approved"] is False
    assert "price_below_minimum" in penny["reasons"]

    # Notional cap binds before the risk budget when the stop is tight.
    tight = stock(
        entry=Decimal("100"),
        stop=Decimal("99"),
        target=Decimal("102"),
        atr=Decimal("2"),
        price=Decimal("100"),
    )
    assert tight["approved"] is True
    assert tight["units"] == 200
    assert tight["planned_loss"] == Decimal("200.00")
    assert tight["notional"] == Decimal("20000.00")
    assert tight["heat_contribution"] == Decimal("300.00")

    # Participation cap binds on a large book in a thin-but-legal name.
    thin = size_stock(
        equity=Decimal("5000000"),
        entry=Decimal("20"),
        stop=Decimal("19.50"),
        target=Decimal("20.75"),
        atr=Decimal("1"),
        price=Decimal("20"),
        adv_dollars=Decimal("25000000"),
        spread=Decimal("0.02"),
        open_heat=Decimal("0"),
        buying_power=Decimal("5000000"),
        gross_long=Decimal("0"),
        risk_mode="normal",
    )
    assert thin["approved"] is True
    assert thin["units"] == 25000
    assert thin["planned_loss"] == Decimal("12500.00")
    assert thin["heat_contribution"] == Decimal("18750.00")

    opt = option()
    assert opt["approved"] is True
    assert opt["units"] == 4
    assert opt["planned_loss"] == Decimal("400.00")
    assert opt["heat_contribution"] == Decimal("1000.00")
    assert opt["structural_max_loss"] == Decimal("1000.00")
    assert opt["expected_r"] == Decimal("1.5000")
    # A total loss is worse than -1R when the planned stop is tighter than the debit.
    assert r_multiple(Decimal("-1000"), opt["initial_risk"]) == Decimal("-2.5000")

    wide_opt = option(bid=Decimal("2.20"), ask=Decimal("2.80"))
    assert wide_opt["approved"] is False
    assert "option_spread_too_wide" in wide_opt["reasons"]

    assert blocks() == []
    assert "earnings_stock_forbidden" in blocks(earnings_in_window=True)
    assert "catalyst_insufficient" in blocks(catalyst_quality="absent")
    assert "catalyst_insufficient" in blocks(setup="failed_breakdown", catalyst_quality="absent")
    assert blocks(setup="momentum_pullback", catalyst_quality="absent") == []
    assert "extended" in blocks(extension_atr=Decimal("1.2"))
    assert "sector_occupied" in blocks(sector_already_open=True)
    assert "instrument_not_allowed" in blocks(instrument="naked_call")
    assert "short_stock_forbidden" in blocks(direction="short")
    assert "invalidation_not_machine_checkable" in blocks(invalidation=("the thesis feels worse",))
    assert "stand_down" in blocks(risk_mode="stand_down")

    assert regime_to_mode("up", "risk_on", "normal", "persistent") == "normal"
    assert regime_to_mode("range", "neutral", "normal", "mixed") == "cautious"
    assert regime_to_mode("down", "risk_off", "high", "mean_reverting") == "stand_down"
    assert regime_to_mode("up", "risk_on", "high", "persistent") == "cautious"

    day = effective_risk_mode("normal", Decimal("-0.011"), 0, 0, 0)
    assert day == {"risk_mode": "stand_down", "reasons": ["day_halt"], "entries_allowed": False}

    dd = effective_risk_mode("normal", 0, 0, Decimal("0.09"), 0)
    assert dd["risk_mode"] == "cautious"
    assert dd["reasons"] == ["drawdown_cautious"]
    assert dd["entries_allowed"] is True

    both = effective_risk_mode("normal", Decimal("-0.02"), 0, Decimal("0.13"), 4)
    assert both["risk_mode"] == "stand_down"
    assert both["entries_allowed"] is False
    assert "day_halt" in both["reasons"]
    assert "drawdown_halt" in both["reasons"]
    assert "streak_cautious" in both["reasons"]

    streak = effective_risk_mode("normal", 0, 0, 0, 4)
    assert streak["risk_mode"] == "cautious"

    assert max_buy_fill(Decimal("84.50")) == Decimal("84.63")
    assert fill_acceptable(Decimal("84.50"), Decimal("84.63")) is True
    assert fill_acceptable(Decimal("84.50"), Decimal("84.64")) is False
    paper_fill = money(Decimal("84.50") * Decimal("1.0005"))
    assert paper_fill == Decimal("84.54")
    assert fill_acceptable(Decimal("84.50"), paper_fill) is True

    sessions = [
        date(2026, 9, 25),
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 5),
    ]
    assert time_stop_session(date(2026, 9, 25), sessions) == date(2026, 10, 2)
    # Deadline lands on Saturday 3 Oct when entry is Saturday-less Friday 26 Sep... 
    # Entry Friday 25 Sep + 7 days = Friday 2 Oct, a session.
    # Entry Monday 28 Sep + 7 = Monday 5 Oct.
    assert time_stop_session(date(2026, 9, 28), sessions) == date(2026, 10, 5)
    holiday = [s for s in sessions if s != date(2026, 10, 2)]
    assert time_stop_session(date(2026, 9, 25), holiday) == date(2026, 10, 1)

    gap = r_multiple(Decimal("-1400"), Decimal("885"))
    assert gap == Decimal("-1.5819")
    assert gap < Decimal("-1")

    board = weekly_scoreboard(
        [Decimal("1.8"), Decimal("-0.6"), Decimal("0.4")],
        Decimal("100000"),
        Decimal("810"),
    )
    assert board["r_sum"] == Decimal("1.6000")
    assert board["expectancy_r"] == Decimal("0.5333")
    assert board["flat_week_is_success"] is True
    assert "quota" not in board
    assert "target" not in board

    hypothesis = design_expectancy_r()
    assert hypothesis == {
        "gross_r": Decimal("0.3500"),
        "friction_r": Decimal("0.08"),
        "net_r": Decimal("0.2700"),
    }

    normal_caps = caps(Decimal("100000"), "normal")
    assert normal_caps["planned_cap"] == Decimal("1000.00")
    assert normal_caps["name_heat_cap"] == Decimal("1000.00")
    assert normal_caps["book_heat_cap"] == Decimal("2000.00")

    _validate_examples()
    print("dragonfly risk math: all vectors passed")
    print(
        "XYZ canonical:"
        f" {xyz['units']} sh,"
        f" planned ${xyz['planned_loss']},"
        f" heat ${xyz['heat_contribution']},"
        f" notional ${xyz['notional']},"
        f" expected R {xyz['expected_r']}"
    )


def _validate_examples() -> None:
    import jsonschema

    def check(schema_name: str, instance: dict) -> None:
        schema = json.loads((SCHEMAS / schema_name).read_text())
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        errors = sorted(validator.iter_errors(instance), key=lambda err: list(err.path))
        if errors:
            rendered = "\n".join(err.message for err in errors)
            raise AssertionError(f"{schema_name} rejected instance:\n{rendered}")

    pairs = {
        "trade_card.schema.json": "trade_card.json",
        "daily_brief.schema.json": "daily_brief.json",
        "journal_entry.schema.json": "journal_entry.json",
        "regime_snapshot.schema.json": "regime_snapshot.json",
        "risk_decision.schema.json": "risk_decision.json",
    }
    for schema_name, example_name in pairs.items():
        check(schema_name, json.loads((EXAMPLES / example_name).read_text()))

    card = json.loads((EXAMPLES / "trade_card.json").read_text())
    del card["stop"]
    try:
        check("trade_card.schema.json", card)
    except AssertionError:
        return
    raise AssertionError("trade card without a stop must fail validation")


if __name__ == "__main__":
    main()

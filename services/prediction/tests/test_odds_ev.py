from decimal import Decimal as D

import pytest
from auspex_prediction.core import InsufficientData, require_probability
from auspex_prediction.ev import (
    PositionCosts,
    break_even_probability,
    evaluate_position,
    expected_profit_usd,
    expected_return_pct,
    gross_payout_usd_for_shares,
)
from auspex_prediction.odds import (
    american_odds_from_decimal_odds,
    decimal_odds_from_american_odds,
    decimal_odds_from_price,
    implied_probability_from_american_odds,
    implied_probability_from_decimal_odds,
    implied_probability_from_price,
)


def costs(stake: str = "10", payout: str = "25", fees: str = "0", slip: str = "0") -> PositionCosts:
    return PositionCosts(D(stake), D(payout), D(fees), D(slip))


# --- conversions ---------------------------------------------------------------------------


def test_price_is_raw_implied_probability() -> None:
    assert implied_probability_from_price(D("0.40")) == D("0.40")


def test_decimal_odds_from_price() -> None:
    assert decimal_odds_from_price(D("0.40")) == D("2.5")
    assert decimal_odds_from_price(D("0.5")) == D("2")


@pytest.mark.parametrize("price", [D(0), D(1), D("-0.1"), D("1.01")])
def test_price_bounds_are_open(price: D) -> None:
    with pytest.raises(ValueError):
        implied_probability_from_price(price)
    with pytest.raises(ValueError):
        decimal_odds_from_price(price)


@pytest.mark.parametrize("bad", [0.4, 1, "0.4", True, None])
def test_non_decimal_inputs_rejected(bad: object) -> None:
    with pytest.raises(TypeError):
        implied_probability_from_price(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D("-Infinity")])
def test_non_finite_rejected(bad: D) -> None:
    with pytest.raises(ValueError):
        implied_probability_from_price(bad)


@pytest.mark.parametrize(
    ("american", "prob"),
    [(150, D("0.4")), (-150, D("0.6")), (100, D("0.5")), (-100, D("0.5")), (400, D("0.2"))],
)
def test_american_to_probability(american: int, prob: D) -> None:
    assert implied_probability_from_american_odds(american) == prob


@pytest.mark.parametrize("american", [0, 99, -99, 50])
def test_american_dead_zone_rejected(american: int) -> None:
    with pytest.raises(ValueError):
        implied_probability_from_american_odds(american)


@pytest.mark.parametrize("bad", [150.0, D(150), True])
def test_american_requires_int(bad: object) -> None:
    with pytest.raises(TypeError):
        implied_probability_from_american_odds(bad)  # type: ignore[arg-type]


def test_decimal_odds_roundtrip() -> None:
    assert implied_probability_from_decimal_odds(D("2.5")) == D("0.4")
    assert decimal_odds_from_american_odds(150) == D("2.5")
    assert decimal_odds_from_american_odds(-200) == D("1.5")
    assert american_odds_from_decimal_odds(D("2.5")) == D(150)
    assert american_odds_from_decimal_odds(D("1.5")) == D(-200)
    assert american_odds_from_decimal_odds(D("2")) == D(100)


@pytest.mark.parametrize("bad", [D(1), D("0.5"), D(0)])
def test_decimal_odds_must_exceed_one(bad: D) -> None:
    with pytest.raises(ValueError):
        implied_probability_from_decimal_odds(bad)
    with pytest.raises(ValueError):
        american_odds_from_decimal_odds(bad)


# --- expected value ------------------------------------------------------------------------


def test_share_payout() -> None:
    assert gross_payout_usd_for_shares(D("10"), D("0.40")) == D("25")


def test_break_even_equals_price_without_costs() -> None:
    assert break_even_probability(costs()) == D("0.4")


def test_break_even_includes_fees_and_slippage() -> None:
    assert break_even_probability(costs(fees="0.25", slip="0.25")) == D("0.42")


def test_break_even_can_exceed_one_when_costs_exceed_payout() -> None:
    assert break_even_probability(costs(stake="10", payout="10", fees="1")) > 1


def test_expected_profit_formula() -> None:
    # 0.5 * 25 - 10 - 0.30 - 0.20 = 2.00
    assert expected_profit_usd(D("0.5"), costs(fees="0.30", slip="0.20")) == D("2.00")


def test_expected_profit_is_exact_decimal() -> None:
    assert expected_profit_usd(D("0.1"), costs(stake="1", payout="3")) == D("-0.7")


def test_expected_return_pct_of_stake() -> None:
    assert expected_return_pct(D("0.5"), costs(fees="0.30", slip="0.20")) == D("20")


def test_zero_edge_at_break_even() -> None:
    ev = evaluate_position(D("0.42"), costs(fees="0.25", slip="0.25"))
    assert ev.expected_profit_usd == 0
    assert ev.edge_probability_points == 0


def test_evaluate_position_negative_edge() -> None:
    ev = evaluate_position(D("0.35"), costs())
    assert ev.break_even_probability == D("0.4")
    assert ev.edge_probability_points == D("-5")
    assert ev.expected_profit_usd == D("-1.25")
    assert ev.expected_return_pct == D("-12.5")


def test_probability_extremes_allowed_for_model() -> None:
    assert expected_profit_usd(D(0), costs()) == D(-10)
    assert expected_profit_usd(D(1), costs()) == D(15)


@pytest.mark.parametrize("p", [D("-0.01"), D("1.01")])
def test_model_probability_bounds(p: D) -> None:
    with pytest.raises(ValueError):
        expected_profit_usd(p, costs())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stake": "0"},
        {"stake": "-1"},
        {"payout": "0"},
        {"fees": "-0.01"},
        {"slip": "-0.01"},
    ],
)
def test_position_costs_bounds(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        costs(**kwargs)


def test_position_costs_rejects_float_money() -> None:
    with pytest.raises(TypeError):
        PositionCosts(10.0, D(25), D(0), D(0))  # type: ignore[arg-type]


def test_open_interval_probability_guard() -> None:
    with pytest.raises(ValueError):
        require_probability("p", D(1), open_interval=True)


def test_insufficient_data_requires_reason() -> None:
    with pytest.raises(ValueError):
        InsufficientData(reasons=())
    assert InsufficientData(("x",)).status.value == "INSUFFICIENT_DATA"

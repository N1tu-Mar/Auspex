from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from auspex_contracts import BetLeg, LegStatus, MarketType, Side, Sport
from auspex_prediction.core import InsufficientData
from auspex_sports.adapter import (
    CoverageBoundedAdapter,
    FeatureObservation,
    FeatureSnapshot,
    LegEstimate,
    SportAdapter,
)
from auspex_sports.mlb import MLB_ADAPTER, MLB_COVERAGE
from auspex_sports.nfl import NFL_ADAPTER, NFL_COVERAGE

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
START = NOW + timedelta(hours=4)


def nfl_leg(**kw: Any) -> BetLeg:
    base: dict[str, Any] = {
        "sport": Sport.NFL,
        "league": "NFL",
        "event_id": "g1",
        "event_start_utc": START,
        "home_participant": "Chiefs",
        "away_participant": "Bills",
        "market_type": MarketType.MONEYLINE,
        "side": Side.HOME,
        "market_price_usd": D("0.55"),
        "settlement_rule_ref": "pm-us/nfl-moneyline-v1",
    }
    return BetLeg(**(base | kw))


def mlb_leg(**kw: Any) -> BetLeg:
    return nfl_leg(sport=Sport.MLB, league="MLB", **kw)


def snapshot(names: tuple[str, ...], age: timedelta = timedelta(hours=1)) -> FeatureSnapshot:
    obs = FeatureObservation("known", NOW - age, "evidence:1")
    return FeatureSnapshot(NOW, {n: obs for n in names})


NFL_FEATURES = NFL_COVERAGE.markets[MarketType.MONEYLINE].required_features
MLB_FEATURES = MLB_COVERAGE.markets[MarketType.MONEYLINE].required_features


def reasons(adapter: CoverageBoundedAdapter, leg: BetLeg, snap: FeatureSnapshot | None) -> str:
    return " | ".join(adapter.validate_coverage(leg, snap, NOW).reasons)


def test_adapters_satisfy_protocol() -> None:
    adapters: list[SportAdapter] = [NFL_ADAPTER, MLB_ADAPTER]
    assert [a.sport for a in adapters] == [Sport.NFL, Sport.MLB]


@pytest.mark.parametrize(
    "leg",
    [
        nfl_leg(),
        nfl_leg(market_type=MarketType.SPREAD, side=Side.AWAY, line=D("-3.5")),
        nfl_leg(market_type=MarketType.SPREAD, side=Side.HOME, line=D("3")),
        nfl_leg(market_type=MarketType.TOTAL, side=Side.OVER, line=D("47.5")),
    ],
)
def test_nfl_covered_legs(leg: BetLeg) -> None:
    assert NFL_ADAPTER.validate_coverage(leg, snapshot(NFL_FEATURES), NOW).covered


@pytest.mark.parametrize(
    "leg",
    [
        mlb_leg(),
        mlb_leg(market_type=MarketType.SPREAD, side=Side.HOME, line=D("-1.5")),
        mlb_leg(market_type=MarketType.TOTAL, side=Side.UNDER, line=D("8.5")),
    ],
)
def test_mlb_covered_legs(leg: BetLeg) -> None:
    assert MLB_ADAPTER.validate_coverage(leg, snapshot(MLB_FEATURES), NOW).covered


@pytest.mark.parametrize(
    ("leg", "expected"),
    [
        (nfl_leg(sport=Sport.MLB), "leg sport MLB is not NFL"),
        (nfl_leg(league="CFL"), "league 'CFL' not in coverage"),
        (nfl_leg(market_type=MarketType.PLAYER_PROP, side=Side.OVER), "outside coverage"),
        (nfl_leg(side=Side.DRAW), "side DRAW invalid"),
        (nfl_leg(side=Side.OVER), "side OVER invalid"),
        (nfl_leg(line=D("3.5")), "must not carry a line"),
        (nfl_leg(market_type=MarketType.SPREAD), "requires a line"),
        (nfl_leg(market_type=MarketType.SPREAD, line=D("3.25")), "not a multiple of 0.5"),
        (nfl_leg(market_type=MarketType.TOTAL, side=Side.OVER, line=D("0")), "must be positive"),
        (nfl_leg(settlement_rule_ref=None), "settlement rule not confirmed"),
        (nfl_leg(status=LegStatus.POSTPONED), "POSTPONED is not PREGAME"),
        (nfl_leg(status=LegStatus.LIVE), "LIVE is not PREGAME"),
        (nfl_leg(event_start_utc=NOW), "event has started"),
    ],
)
def test_nfl_coverage_rejections(leg: BetLeg, expected: str) -> None:
    assert expected in reasons(NFL_ADAPTER, leg, snapshot(NFL_FEATURES))


def test_out_of_coverage_market_lists_exclusions() -> None:
    r = NFL_ADAPTER.validate_coverage(
        nfl_leg(market_type=MarketType.PLAYER_PROP, side=Side.OVER), None, NOW
    )
    assert r.reasons[1:] == NFL_COVERAGE.exclusions


@pytest.mark.parametrize("line", [D("2.5"), D("-2.5"), D("1")])
def test_mlb_only_standard_run_line(line: D) -> None:
    leg = mlb_leg(market_type=MarketType.SPREAD, line=line)
    assert "outside supported lines" in reasons(MLB_ADAPTER, leg, snapshot(MLB_FEATURES))


def test_missing_snapshot() -> None:
    assert reasons(NFL_ADAPTER, nfl_leg(), None) == "no feature snapshot"


def test_missing_and_unknown_features() -> None:
    snap = snapshot(NFL_FEATURES[1:])
    unknown = FeatureSnapshot(
        NOW, {**snap.features, "weather_forecast": FeatureObservation(None, NOW, "evidence:2")}
    )
    text = reasons(NFL_ADAPTER, nfl_leg(), unknown)
    assert f"missing feature {NFL_FEATURES[0]}" in text
    assert "missing feature weather_forecast" in text


def test_mlb_requires_confirmed_lineups() -> None:
    snap = snapshot(tuple(f for f in MLB_FEATURES if "lineup" not in f))
    text = reasons(MLB_ADAPTER, mlb_leg(), snap)
    assert "missing feature home_confirmed_lineup" in text
    assert "missing feature away_confirmed_lineup" in text


def test_stale_features() -> None:
    text = reasons(MLB_ADAPTER, mlb_leg(), snapshot(MLB_FEATURES, age=timedelta(hours=7)))
    assert "stale" in text


def test_feature_age_boundary_is_inclusive() -> None:
    snap = snapshot(MLB_FEATURES, age=MLB_COVERAGE.max_feature_age)
    assert MLB_ADAPTER.validate_coverage(mlb_leg(), snap, NOW).covered


def test_future_dated_feature() -> None:
    text = reasons(NFL_ADAPTER, nfl_leg(), snapshot(NFL_FEATURES, age=-timedelta(minutes=1)))
    assert "observed after as_of_utc" in text


def test_multiple_reasons_accumulate() -> None:
    leg = nfl_leg(status=LegStatus.POSTPONED, settlement_rule_ref=None)
    r = NFL_ADAPTER.validate_coverage(leg, None, NOW)
    assert len(r.reasons) == 3


def test_estimate_is_insufficient_without_coverage() -> None:
    r = NFL_ADAPTER.estimate_leg(nfl_leg(), None, NOW)
    assert isinstance(r, InsufficientData)
    assert r.reasons == ("no feature snapshot",)


@pytest.mark.parametrize(
    ("adapter", "features"), [(NFL_ADAPTER, NFL_FEATURES), (MLB_ADAPTER, MLB_FEATURES)]
)
def test_estimate_is_insufficient_without_model(
    adapter: CoverageBoundedAdapter, features: tuple[str, ...]
) -> None:
    leg = nfl_leg(sport=adapter.sport, league=adapter.sport.value)
    r = adapter.estimate_leg(leg, snapshot(features), NOW)
    assert isinstance(r, InsufficientData)
    assert "no validated" in r.reasons[0]


def test_settlement_requirements() -> None:
    assert any("tie" in s for s in NFL_ADAPTER.settlement_requirements(nfl_leg()))
    assert any("first five" in s for s in MLB_ADAPTER.settlement_requirements(mlb_leg()))
    prop = nfl_leg(market_type=MarketType.PLAYER_PROP, side=Side.OVER)
    assert NFL_ADAPTER.settlement_requirements(prop) == ()


def test_leg_estimate_validation() -> None:
    ok = LegEstimate(D("0.5"), D("0.4"), D("0.6"), "v1", NOW)
    assert ok.model_probability == D("0.5")
    with pytest.raises(ValueError, match="within"):
        LegEstimate(D("0.7"), D("0.4"), D("0.6"), "v1", NOW)
    with pytest.raises(ValueError):
        LegEstimate(D("0.5"), D("-0.1"), D("0.6"), "v1", NOW)
    with pytest.raises(ValueError, match="model_version"):
        LegEstimate(D("0.5"), D("0.4"), D("0.6"), "", NOW)
    with pytest.raises(TypeError):
        LegEstimate(0.5, D("0.4"), D("0.6"), "v1", NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="aware"):
        LegEstimate(D("0.5"), D("0.4"), D("0.6"), "v1", datetime(2026, 1, 1))  # noqa: DTZ001

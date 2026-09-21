from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from auspex_contracts import BetLeg, LegStatus, MarketType, Side, Sport
from auspex_prediction.combo import (
    ComboAssessment,
    ComboSettlement,
    LegResult,
    VoidPolicy,
    assess_combo,
    naive_independent_probability,
    settle_combo,
)
from auspex_prediction.core import InsufficientData, pregame_blockers
from auspex_prediction.correlation import DependencyKind, detect_correlation_warnings

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
KICKOFF = NOW + timedelta(hours=5)


def leg(**kw: Any) -> BetLeg:
    base: dict[str, Any] = {
        "sport": Sport.NFL,
        "league": "NFL",
        "event_id": "g1",
        "event_start_utc": KICKOFF,
        "home_participant": "Chiefs",
        "away_participant": "Bills",
        "market_type": MarketType.MONEYLINE,
        "side": Side.HOME,
        "market_price_usd": D("0.55"),
    }
    return BetLeg(**(base | kw))


def other_game(**kw: Any) -> BetLeg:
    return leg(event_id="g2", home_participant="Eagles", away_participant="Cowboys", **kw)


def kinds(legs: list[BetLeg]) -> set[DependencyKind]:
    return {w.kind for w in detect_correlation_warnings(legs)}


# --- naive baseline ------------------------------------------------------------------------


def test_naive_baseline_is_labeled_product() -> None:
    b = naive_independent_probability([D("0.5"), D("0.4"), D("0.5")])
    assert b.probability == D("0.1")
    assert b.label == "NAIVE_INDEPENDENT_BASELINE"
    assert "independent" in b.assumption


def test_naive_baseline_zero_and_one() -> None:
    assert naive_independent_probability([D(1), D(1)]).probability == 1
    assert naive_independent_probability([D(0), D("0.9")]).probability == 0


@pytest.mark.parametrize("probs", [[D("0.5")], []])
def test_naive_baseline_needs_two_legs(probs: list[D]) -> None:
    with pytest.raises(ValueError):
        naive_independent_probability(probs)


def test_naive_baseline_rejects_out_of_bounds_and_float() -> None:
    with pytest.raises(ValueError):
        naive_independent_probability([D("0.5"), D("1.2")])
    with pytest.raises(TypeError):
        naive_independent_probability([D("0.5"), 0.5])  # type: ignore[list-item]


# --- correlation warnings ------------------------------------------------------------------


def test_independent_games_have_no_warnings() -> None:
    assert detect_correlation_warnings([leg(), other_game()]) == []


def test_same_game_different_markets() -> None:
    k = kinds([leg(), leg(market_type=MarketType.TOTAL, side=Side.OVER, line=D("47.5"))])
    assert k == {
        DependencyKind.SHARED_GAME,
        DependencyKind.SHARED_WEATHER,
        DependencyKind.GAME_SCRIPT,
    }


def test_same_game_same_market_flags_nesting() -> None:
    k = kinds([leg(), leg(side=Side.AWAY)])
    assert DependencyKind.SAME_MARKET in k
    assert DependencyKind.GAME_SCRIPT not in k


def test_same_player_props() -> None:
    props = [
        leg(market_type=MarketType.PLAYER_PROP, side=Side.OVER, player_id="p1", line=D("250.5")),
        leg(market_type=MarketType.PLAYER_PROP, side=Side.OVER, player_id="p1", line=D("1.5")),
    ]
    k = kinds(props)
    assert {DependencyKind.SHARED_PLAYER, DependencyKind.SAME_MARKET} <= k


def test_different_players_same_game_is_game_script() -> None:
    props = [
        leg(market_type=MarketType.PLAYER_PROP, side=Side.OVER, player_id="p1"),
        leg(market_type=MarketType.PLAYER_PROP, side=Side.OVER, player_id="p2"),
    ]
    k = kinds(props)
    assert DependencyKind.GAME_SCRIPT in k
    assert DependencyKind.SHARED_PLAYER not in k


def test_same_game_matched_by_participants_without_event_id() -> None:
    a = leg(event_id=None)
    b = leg(event_id=None, home_participant=" bills", away_participant="CHIEFS", side=Side.AWAY)
    assert DependencyKind.SHARED_GAME in kinds([a, b])


def test_shared_team_across_games() -> None:
    later = leg(
        event_id="g9",
        event_start_utc=KICKOFF + timedelta(days=7),
        away_participant="Jets",
    )
    w = detect_correlation_warnings([leg(), later])
    assert [x.kind for x in w] == [DependencyKind.SHARED_TEAM]
    assert "chiefs" in w[0].explanation


def test_unidentifiable_leg_warns_unknown() -> None:
    w = detect_correlation_warnings([leg(event_id=None, away_participant=None), other_game()])
    assert w[0].kind is DependencyKind.UNKNOWN_DEPENDENCY
    assert w[0].leg_indices == (0,)


def test_warnings_are_unquantified_and_indexed() -> None:
    w = detect_correlation_warnings([other_game(), leg(), leg(side=Side.AWAY)])
    assert all(x.magnitude == "UNQUANTIFIED" for x in w)
    assert {x.leg_indices for x in w} == {(1, 2)}


# --- assess_combo --------------------------------------------------------------------------


def test_assess_combo_never_claims_joint_probability() -> None:
    r = assess_combo([leg(), other_game()], [D("0.5"), D("0.6")], as_of_utc=NOW)
    assert isinstance(r, ComboAssessment)
    assert r.naive_baseline.probability == D("0.30")
    assert r.warnings == ()
    assert isinstance(r.joint_probability, InsufficientData)
    assert "no validated correlation model" in r.joint_probability.reasons[0]


def test_assess_combo_reports_warning_count() -> None:
    r = assess_combo([leg(), leg(side=Side.AWAY)], [D("0.5"), D("0.5")], as_of_utc=NOW)
    assert isinstance(r, ComboAssessment)
    assert r.warnings
    assert r.joint_probability.reasons[0].startswith(f"{len(r.warnings)} shared-dependency")


@pytest.mark.parametrize(
    "status", [LegStatus.POSTPONED, LegStatus.CANCELED, LegStatus.LIVE, LegStatus.COMPLETED]
)
def test_assess_combo_blocks_non_pregame_legs(status: LegStatus) -> None:
    r = assess_combo([leg(), other_game(status=status)], [D("0.5"), D("0.5")], as_of_utc=NOW)
    assert isinstance(r, InsufficientData)
    assert r.reasons[0].startswith("leg 1:")
    assert status.value in r.reasons[0]


def test_assess_combo_blocks_started_event() -> None:
    r = assess_combo([leg(), other_game()], [D("0.5"), D("0.5")], as_of_utc=KICKOFF)
    assert isinstance(r, InsufficientData)
    assert len(r.reasons) == 2


def test_assess_combo_length_mismatch() -> None:
    with pytest.raises(ValueError):
        assess_combo([leg(), other_game()], [D("0.5")], as_of_utc=NOW)


def test_pregame_blockers_requires_aware_as_of() -> None:
    with pytest.raises(ValueError):
        pregame_blockers(leg(), datetime(2026, 9, 21))  # noqa: DTZ001 - deliberately naive


# --- settlement ----------------------------------------------------------------------------

W, L, V, U = LegResult.WON, LegResult.LOST, LegResult.VOID, LegResult.UNRESOLVED


@pytest.mark.parametrize(
    ("results", "policy", "expected"),
    [
        ([W, W], None, ComboSettlement.WON),
        ([W, L], None, ComboSettlement.LOST),
        ([L, U], None, ComboSettlement.LOST),  # a lost leg decides even with pending legs
        ([L, V], VoidPolicy.VOID_ENTIRE_COMBO, ComboSettlement.LOST),
        ([W, U], None, ComboSettlement.UNRESOLVED),
        ([V, U], VoidPolicy.REMOVE_VOID_LEGS, ComboSettlement.UNRESOLVED),
        ([W, V], None, ComboSettlement.RULE_UNKNOWN),
        ([W, V], VoidPolicy.REMOVE_VOID_LEGS, ComboSettlement.WON_REPRICED),
        ([W, V], VoidPolicy.VOID_ENTIRE_COMBO, ComboSettlement.VOID),
        ([V, V], VoidPolicy.REMOVE_VOID_LEGS, ComboSettlement.VOID),
    ],
)
def test_settle_combo(
    results: list[LegResult], policy: VoidPolicy | None, expected: ComboSettlement
) -> None:
    assert settle_combo(results, policy) is expected


def test_settle_combo_needs_two_legs() -> None:
    with pytest.raises(ValueError):
        settle_combo([W], None)

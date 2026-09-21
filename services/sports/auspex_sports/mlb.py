"""MLB pregame coverage: full-game moneyline, 1.5 run line, and total only.

Estimates require confirmed starters and lineups, so a pregame result only becomes possible
after lineups post; any earlier request is INSUFFICIENT_DATA by construction.
"""

from datetime import timedelta
from decimal import Decimal

from auspex_contracts import MarketType, Side, Sport
from auspex_sports.adapter import (
    CoverageBoundary,
    CoverageBoundedAdapter,
    FeatureKind,
    FeatureSpec,
    MarketRule,
)

_GAME_FEATURES = (
    "home_confirmed_starting_pitcher",
    "away_confirmed_starting_pitcher",
    "home_confirmed_lineup",
    "away_confirmed_lineup",
    "weather_forecast",  # value "ROOF_CLOSED" is valid for closed roofs
    "park_factor",
)
_SCOPE = "market scope is full game (not first five innings or team total)"
_POSTPONED = "postponement, suspension, and shortened-game rules"

MLB_COVERAGE = CoverageBoundary(
    sport=Sport.MLB,
    leagues=frozenset({"MLB"}),
    max_feature_age=timedelta(hours=6),
    feature_specs={
        "park_factor": FeatureSpec(
            FeatureKind.DECIMAL, minimum=Decimal("0.5"), maximum=Decimal("1.5")
        )
    },  # ratio to league average
    markets={
        MarketType.MONEYLINE: MarketRule(
            sides=frozenset({Side.HOME, Side.AWAY}),
            required_features=_GAME_FEATURES,
            settlement_requirements=(_SCOPE, "listed-pitcher (starter change) rule", _POSTPONED),
        ),
        MarketType.SPREAD: MarketRule(
            sides=frozenset({Side.HOME, Side.AWAY}),
            required_features=_GAME_FEATURES,
            requires_line=True,
            allowed_lines=frozenset({Decimal("-1.5"), Decimal("1.5")}),
            settlement_requirements=(_SCOPE, "listed-pitcher (starter change) rule", _POSTPONED),
        ),
        MarketType.TOTAL: MarketRule(
            sides=frozenset({Side.OVER, Side.UNDER}),
            required_features=_GAME_FEATURES,
            requires_line=True,
            line_step=Decimal("0.5"),
            positive_line_only=True,
            settlement_requirements=(_SCOPE, "extra innings count toward total", _POSTPONED),
        ),
    },
    exclusions=(
        "player props excluded until the contract carries a stat type and historical data exists",
        "first-five-innings, team totals, alternate run lines, and live markets are out of scope",
        "the BetLeg contract cannot yet distinguish full-game from first-five markets; "
        "settlement_rule_ref must confirm full-game scope",
    ),
)

MLB_ADAPTER = CoverageBoundedAdapter(MLB_COVERAGE)

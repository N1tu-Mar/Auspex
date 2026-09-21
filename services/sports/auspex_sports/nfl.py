"""NFL pregame coverage: full-game moneyline, spread, and total only."""

from datetime import timedelta
from decimal import Decimal

from auspex_contracts import MarketType, Side, Sport
from auspex_sports.adapter import CoverageBoundary, CoverageBoundedAdapter, MarketRule

_TEAM_FEATURES = (
    "home_injury_report",
    "away_injury_report",
    "home_starting_qb_status",
    "away_starting_qb_status",
    "weather_forecast",  # value "DOME" is valid for closed roofs
)
_HALF = Decimal("0.5")

NFL_COVERAGE = CoverageBoundary(
    sport=Sport.NFL,
    leagues=frozenset({"NFL"}),
    max_feature_age=timedelta(hours=12),
    markets={
        MarketType.MONEYLINE: MarketRule(
            sides=frozenset({Side.HOME, Side.AWAY}),
            required_features=_TEAM_FEATURES,
            settlement_requirements=(
                "whether overtime counts toward the result",
                "how a tie settles (void, loss, or separate outcome)",
                "postponement and relocation handling",
            ),
        ),
        MarketType.SPREAD: MarketRule(
            sides=frozenset({Side.HOME, Side.AWAY}),
            required_features=_TEAM_FEATURES,
            requires_line=True,
            line_step=_HALF,
            settlement_requirements=(
                "whether overtime counts toward the margin",
                "push handling on whole-number lines",
                "postponement and relocation handling",
            ),
        ),
        MarketType.TOTAL: MarketRule(
            sides=frozenset({Side.OVER, Side.UNDER}),
            required_features=_TEAM_FEATURES,
            requires_line=True,
            line_step=_HALF,
            positive_line_only=True,
            settlement_requirements=(
                "whether overtime points count",
                "push handling on whole-number lines",
                "postponement and relocation handling",
            ),
        ),
    },
    exclusions=(
        "player props excluded until the contract carries a stat type and historical data exists",
        "halves, quarters, team totals, and live markets are out of scope",
    ),
)

NFL_ADAPTER = CoverageBoundedAdapter(NFL_COVERAGE)

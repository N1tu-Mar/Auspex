"""Price and odds conversions. All values are ``Decimal``; no floats.

Polymarket share semantics assumed here: a binary share costs ``market_price_usd`` and pays
exactly 1.00 USD if it resolves YES, else 0. The raw implied probability therefore equals the
price. Confirm per market before use; fees and slippage are handled in ``ev``.
"""

from decimal import Decimal

from auspex_prediction.core import ONE, require_decimal, require_probability

SHARE_PAYOUT_USD = Decimal("1.00")
_HUNDRED = Decimal(100)


def implied_probability_from_price(market_price_usd: Decimal) -> Decimal:
    """Raw (vig-inclusive) implied probability of a 1.00 USD binary share."""
    return require_probability("market_price_usd", market_price_usd, open_interval=True)


def decimal_odds_from_price(market_price_usd: Decimal) -> Decimal:
    """Decimal odds (gross return per 1 USD staked, stake included) for a binary share."""
    price = require_probability("market_price_usd", market_price_usd, open_interval=True)
    return SHARE_PAYOUT_USD / price


def implied_probability_from_decimal_odds(decimal_odds: Decimal) -> Decimal:
    odds = require_decimal("decimal_odds", decimal_odds)
    if odds <= ONE:
        raise ValueError(f"decimal_odds must be > 1, got {odds}")
    return ONE / odds


def implied_probability_from_american_odds(american_odds: int) -> Decimal:
    """+150 -> 0.4, -150 -> 0.6. Values in (-100, +100) are not valid American odds."""
    if isinstance(american_odds, bool) or not isinstance(american_odds, int):
        raise TypeError(f"american_odds must be int, got {type(american_odds).__name__}")
    if -100 < american_odds < 100:
        raise ValueError(f"american_odds must be <= -100 or >= +100, got {american_odds}")
    odds = Decimal(american_odds)
    if odds > 0:
        return _HUNDRED / (odds + _HUNDRED)
    return -odds / (-odds + _HUNDRED)


def decimal_odds_from_american_odds(american_odds: int) -> Decimal:
    return ONE / implied_probability_from_american_odds(american_odds)


def american_odds_from_decimal_odds(decimal_odds: Decimal) -> Decimal:
    """Exact (unrounded) American odds; 2.00 maps to +100. Round only for display."""
    odds = require_decimal("decimal_odds", decimal_odds)
    if odds <= ONE:
        raise ValueError(f"decimal_odds must be > 1, got {odds}")
    if odds >= 2:
        return (odds - ONE) * _HUNDRED
    return -_HUNDRED / (odds - ONE)

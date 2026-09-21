import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.fixtures import FIXTURE_DIR, FixtureTransport, json_fixture
from auspex_research.polymarket import (
    MarketEnvelope,
    PolymarketUSClient,
    normalize_market,
)
from auspex_research.providers import NormalizedMarket, PolymarketProvider, ProviderResponse
from auspex_research.transport import RawResponse, RetryPolicy

from auspex_contracts import MarketType

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
BASE = "https://gateway.polymarket.us/v1/market/slug/"
MONEYLINE = "polymarket_us/market_by_slug.nfl_moneyline.synthetic.json"
PROP = "polymarket_us/market_by_slug.prop_unusual.synthetic.json"


def fetch(transport: FixtureTransport, slug: str) -> ProviderResponse[NormalizedMarket]:
    client: PolymarketProvider = PolymarketUSClient(
        transport, RetryPolicy(max_attempts=1), clock=lambda: NOW
    )
    return asyncio.run(client.get_market_by_slug(slug))


@pytest.mark.parametrize("fixture", sorted(FIXTURE_DIR.glob("polymarket_us/*.json")))
def test_every_fixture_satisfies_the_upstream_contract(fixture: Path) -> None:
    MarketEnvelope.model_validate(json.loads(fixture.read_text()))


def test_moneyline_normalizes_with_source_and_timestamp() -> None:
    transport = FixtureTransport({BASE + "nfl-kc-buf-2026-09-27": json_fixture(MONEYLINE)})
    response = fetch(transport, "nfl-kc-buf-2026-09-27")
    market = response.data
    assert response.source.provider == "polymarket_us" and response.retrieved_at == NOW
    assert market.source_url == BASE + "nfl-kc-buf-2026-09-27"
    assert market.retrieved_at == NOW
    assert market.market_id == "fixture-mkt-1001"
    assert market.market_type is MarketType.MONEYLINE
    assert market.event_start_utc == datetime(2026, 9, 27, 20, 25, tzinfo=UTC)
    assert market.is_open and market.combo_enabled
    assert [(s.description, s.price_usd, s.is_long) for s in market.sides] == [
        ("Kansas City Chiefs", Decimal("0.5400"), True),
        ("Buffalo Bills", Decimal("0.4700"), False),
    ]
    assert (market.best_bid_usd, market.best_ask_usd) == (Decimal("0.53"), Decimal("0.55"))
    assert market.warnings == ()
    assert transport.calls == [BASE + "nfl-kc-buf-2026-09-27"]


def test_normalization_is_deterministic() -> None:
    raw = MarketEnvelope.model_validate_json(json_fixture(MONEYLINE).body).market
    assert normalize_market(raw, "https://x.test/", NOW) == normalize_market(
        raw, "https://x.test/", NOW
    )


def test_unusual_market_is_flagged_not_guessed() -> None:
    raw = MarketEnvelope.model_validate_json(json_fixture(PROP).body).market
    market = normalize_market(raw, "https://x.test/", NOW)
    assert market.market_type is None and market.provider_market_type == "PROP"
    assert market.event_start_utc is None  # naive upstream time is never assumed UTC
    assert not market.is_open  # closed
    assert [s.price_usd for s in market.sides] == [None, None]
    assert market.best_bid_usd is None
    assert market.warnings == (
        "gameStartTime has no timezone; ignored",
        "unsupported market type 'PROP'",
        "side fixture-side-3 price 1.20 outside (0, 1); ignored",
        "best bid currency 'EUR' is not USD; ignored",
    )


@pytest.mark.parametrize(
    "body",
    [
        b'{"markets": []}',  # envelope renamed
        b'{"market": {"question": "no id"}}',
        b'{"market": {"id": "m", "marketSides": [{"id": "s", "price": "abc"}]}}',
    ],
)
def test_breaking_upstream_change_is_a_schema_error(body: bytes) -> None:
    with pytest.raises(ProviderError) as err:
        fetch(FixtureTransport({BASE + "m": RawResponse(200, body)}), "m")
    assert err.value.kind is ProviderErrorKind.SCHEMA


def test_unknown_market_is_not_found() -> None:
    with pytest.raises(ProviderError) as err:
        fetch(FixtureTransport({}), "nfl-missing")
    assert err.value.kind is ProviderErrorKind.NOT_FOUND


@pytest.mark.parametrize("slug", ["", "../v1/orders", "a/b", "A-B", "x?y=1", "x" * 201])
def test_unsafe_slug_is_rejected_before_any_request(slug: str) -> None:
    transport = FixtureTransport({})
    with pytest.raises(ProviderError) as err:
        fetch(transport, slug)
    assert err.value.kind is ProviderErrorKind.BAD_REQUEST and transport.calls == []

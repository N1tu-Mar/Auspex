import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from auspex_contracts import MarketType
from auspex_research.cache import TTLCache
from auspex_research.catalog import (
    CatalogEvent,
    EventQuery,
    ResolutionStatus,
    normalize_name,
    resolve_event,
)
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.fixtures import FixtureTransport, json_fixture
from auspex_research.polymarket import PolymarketUSClient
from auspex_research.providers import PolymarketProvider
from auspex_research.transport import Fetcher, RawResponse, RetryPolicy

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
GW = "https://gateway.polymarket.us"
EVENTS = "polymarket_us/events.nfl_window.synthetic.json"
LIST_URL = (
    f"{GW}/v1/events?active=true&closed=false&limit=50&offset=0"
    "&startTimeMax=2026-09-29T00%3A00%3A00Z&startTimeMin=2026-09-27T00%3A00%3A00Z"
)


def client(routes: dict[str, Any], **kw: Any) -> tuple[PolymarketProvider, FixtureTransport]:
    transport = FixtureTransport(routes)
    fetcher = Fetcher(transport, RetryPolicy(max_attempts=1), clock=lambda: NOW, **kw)
    return PolymarketUSClient(fetcher), transport


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def catalog() -> tuple[CatalogEvent, ...]:
    provider, _ = client({LIST_URL: json_fixture(EVENTS)})
    page = run(
        provider.list_events(
            start_after=datetime(2026, 9, 27, tzinfo=UTC),
            start_before=datetime(2026, 9, 29, tzinfo=UTC),
        )
    ).data
    events: tuple[CatalogEvent, ...] = page.events
    return events


def test_list_events_normalizes_and_names_the_malformed_row() -> None:
    provider, transport = client({LIST_URL: json_fixture(EVENTS)})
    response = run(
        provider.list_events(
            start_after=datetime(2026, 9, 27, tzinfo=UTC),
            start_before=datetime(2026, 9, 29, tzinfo=UTC),
        )
    )
    page = response.data
    assert transport.calls == [LIST_URL]
    assert [e.event_id for e in page.events] == ["9001", "9002", "9003", "9004"]
    assert len(page.skipped) == 1 and page.skipped[0].startswith("events[4]:")
    first = page.events[0]
    assert (first.league_slug, first.sport_slug) == ("nfl", "football")
    assert first.start_utc == datetime(2026, 9, 27, 20, 25, tzinfo=UTC)
    assert [(m.market_id, m.market_type) for m in first.markets] == [
        ("1001", MarketType.MONEYLINE),
        ("1002", None),  # PROP stays unmapped
    ]
    assert first.resolution_source == "Synthetic: league official box score"  # verbatim
    assert first.retrieved_at == NOW and first.source_url == LIST_URL
    no_start = page.events[3]
    assert no_start.start_utc is None and "startTime missing" in no_start.warnings
    assert page.events[2].league_slug is None and "league missing" in page.events[2].warnings


@pytest.mark.parametrize(
    "kwargs",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"tag_slug": "nfl/../x"}],
)
def test_list_events_rejects_bad_bounds_before_any_request(kwargs: dict[str, Any]) -> None:
    provider, transport = client({})
    with pytest.raises(ProviderError) as err:
        run(provider.list_events(start_after=NOW, start_before=NOW, **kwargs))
    assert err.value.kind is ProviderErrorKind.BAD_REQUEST and transport.calls == []


def test_list_events_requires_aware_datetimes() -> None:
    provider, _ = client({})
    with pytest.raises(ValueError, match="timezone-aware"):
        run(
            provider.list_events(
                start_after=datetime.fromisoformat("2026-09-27T00:00:00"), start_before=NOW
            )
        )


def test_event_by_slug() -> None:
    provider, _ = client(
        {
            f"{GW}/v1/events/slug/nfl-kc-buf-2026-09-27": json_fixture(
                "polymarket_us/event_by_slug.nfl.synthetic.json"
            )
        }
    )
    event = run(provider.get_event_by_slug("nfl-kc-buf-2026-09-27")).data
    assert event.event_id == "9001" and next(t.name for t in event.teams) == "Kansas City Chiefs"


@pytest.mark.parametrize("slug", ["", "A", "a/../b", "a?x=1", "a b", "-a", "a" * 201])
def test_slugs_and_ids_are_validated_before_any_request(slug: str) -> None:
    provider, transport = client({})
    for call in (
        provider.get_event_by_slug,
        provider.get_market_by_slug,
        provider.get_market_settlement,
        provider.get_market_by_id,
    ):
        if (
            call == provider.get_market_by_id
            and slug
            and "/" not in slug
            and "?" not in slug
            and " " not in slug
        ):
            continue  # ids may legitimately start with any alphanumeric
        with pytest.raises(ProviderError) as err:
            run(call(slug))
        assert err.value.kind is ProviderErrorKind.BAD_REQUEST
    assert transport.calls == []


def test_market_by_id_and_rule_text_is_verbatim() -> None:
    provider, transport = client(
        {
            f"{GW}/v1/market/id/fixture-mkt-1001": json_fixture(
                "polymarket_us/market_by_slug.nfl_moneyline.synthetic.json"
            )
        }
    )
    market = run(provider.get_market_by_id("fixture-mkt-1001")).data
    assert market.market_id == "fixture-mkt-1001"
    assert (
        market.description
        == "Synthetic rules: resolves Yes if the named team wins in regulation or overtime."
    )
    assert market.rules_disclaimer == "Synthetic disclaimer."
    assert transport.calls == [f"{GW}/v1/market/id/fixture-mkt-1001"]


def test_missing_rule_text_stays_none_not_invented() -> None:
    provider, _ = client(
        {
            f"{GW}/v1/market/slug/nfl-prop": json_fixture(
                "polymarket_us/market_by_slug.prop_unusual.synthetic.json"
            )
        }
    )
    market = run(provider.get_market_by_slug("nfl-prop")).data
    assert market.rules_disclaimer is None or isinstance(market.rules_disclaimer, str)
    assert market.market_type is None and market.warnings


def test_settlement_reports_upstream_value_without_interpretation() -> None:
    slug = "nfl-kc-buf-2026-09-20"
    provider, _ = client(
        {
            f"{GW}/v1/markets/{slug}/settlement": json_fixture(
                "polymarket_us/settlement.synthetic.json"
            )
        }
    )
    settlement = run(provider.get_market_settlement(slug)).data
    assert (settlement.slug, settlement.settlement_value) == (slug, Decimal(1))


def test_settlement_404_is_not_read_as_unsettled_or_missing() -> None:
    provider, _ = client({})
    with pytest.raises(ProviderError, match="not found or not settled") as err:
        run(provider.get_market_settlement("nfl-kc-buf-2026-09-20"))
    assert err.value.kind is ProviderErrorKind.NOT_FOUND


def test_settlement_slug_mismatch_is_a_schema_error() -> None:
    provider, _ = client(
        {
            f"{GW}/v1/markets/other/settlement": json_fixture(
                "polymarket_us/settlement.synthetic.json"
            )
        }
    )
    with pytest.raises(ProviderError) as err:
        run(provider.get_market_settlement("other"))
    assert err.value.kind is ProviderErrorKind.SCHEMA


@pytest.mark.parametrize(
    ("call", "arg", "path", "fixture"),
    [
        ("get_market_settlement", "s", "/v1/markets/s/settlement", "bad.settlement.synthetic.json"),
        ("get_market_by_slug", "s", "/v1/market/slug/s", "bad.market_sides.synthetic.json"),
        ("get_market_by_id", "9", "/v1/market/id/9", "bad.market_null.synthetic.json"),
    ],
)
def test_malformed_upstream_bodies_are_schema_errors(
    call: str, arg: str, path: str, fixture: str
) -> None:
    provider, _ = client({GW + path: json_fixture(f"polymarket_us/{fixture}")})
    with pytest.raises(ProviderError) as err:
        run(getattr(provider, call)(arg))
    assert err.value.kind is ProviderErrorKind.SCHEMA and "http" not in err.value.message


@pytest.mark.parametrize("body", [b"[]", b'{"events": "x"}', b"not json", b'{"events": null}'])
def test_malformed_catalog_envelope_is_a_schema_error(body: bytes) -> None:
    provider, _ = client({LIST_URL: RawResponse(200, body)})
    with pytest.raises(ProviderError) as err:
        run(
            provider.list_events(
                start_after=datetime(2026, 9, 27, tzinfo=UTC),
                start_before=datetime(2026, 9, 29, tzinfo=UTC),
            )
        )
    assert err.value.kind is ProviderErrorKind.SCHEMA


def test_catalog_is_cached_within_ttl_via_the_client() -> None:
    provider, transport = client({LIST_URL: json_fixture(EVENTS)}, cache=TTLCache())
    start, end = datetime(2026, 9, 27, tzinfo=UTC), datetime(2026, 9, 29, tzinfo=UTC)
    first = run(provider.list_events(start_after=start, start_before=end))
    second = run(provider.list_events(start_after=start, start_before=end))
    assert len(transport.calls) == 1 and second.from_cache and not first.from_cache


# --- resolution -------------------------------------------------------------------------------


def test_normalize_name_is_deterministic() -> None:
    assert normalize_name("  São  Paulo F.C.! ") == "sao paulo f c"
    assert normalize_name("K.C.") == normalize_name("k c")


def test_resolves_one_event_by_teams_and_start_time() -> None:
    result = resolve_event(
        catalog(),
        EventQuery(
            participants=("Kansas City Chiefs", "Buffalo Bills"),
            start_utc=datetime(2026, 9, 27, 20, 0, tzinfo=UTC),
            window=timedelta(hours=1),
        ),
    )
    assert result.status is ResolutionStatus.MATCHED and [e.event_id for e in result.matches] == [
        "9001"
    ]
    assert "1 candidate(s) had no start time" in result.reason


def test_same_teams_two_games_is_ambiguous_not_guessed() -> None:
    result = resolve_event(
        catalog(), EventQuery(participants=("Kansas City Chiefs", "Buffalo Bills"))
    )
    assert result.status is ResolutionStatus.AMBIGUOUS
    assert [e.event_id for e in result.matches] == ["9001", "9002", "9004"]
    assert "user must choose" in result.reason


def test_one_team_and_wide_window_are_ambiguous_and_order_is_stable() -> None:
    query = EventQuery(participants=("Chiefs",), start_utc=datetime(2026, 9, 27, 22, 0, tzinfo=UTC))
    assert [e.event_id for e in resolve_event(catalog(), query).matches] == ["9001", "9002"]
    assert [e.event_id for e in resolve_event(tuple(reversed(catalog())), query).matches] == [
        "9001",
        "9002",
    ]


def test_narrow_window_disambiguates_and_no_partial_name_matching() -> None:
    narrow = EventQuery(
        participants=("Chiefs",),
        start_utc=datetime(2026, 9, 27, 23, 0, tzinfo=UTC),
        window=timedelta(hours=2),
    )
    assert resolve_event(catalog(), narrow).matches[0].event_id == "9002"
    for name in ("Kansas", "Chief", "Jets Bills"):  # substrings / unknown never match
        assert (
            resolve_event(catalog(), EventQuery(participants=(name,))).status
            is ResolutionStatus.NO_MATCH
        )


def test_both_participants_must_be_distinct_teams_of_the_same_event() -> None:
    assert (
        resolve_event(catalog(), EventQuery(participants=("Chiefs", "Chiefs"))).status
        is ResolutionStatus.NO_MATCH
    )
    assert (
        resolve_event(catalog(), EventQuery(participants=("Chiefs", "Jets"))).status
        is ResolutionStatus.NO_MATCH
    )
    with pytest.raises(ValueError, match="blank"):
        EventQuery(participants=("!!!",))

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.intake import CatalogEvent, get_event_catalog, get_now
from app.main import app

CATALOG = [
    CatalogEvent.model_validate(event)
    for event in json.loads((Path(__file__).parent / "fixtures/intake_events.json").read_text())
]
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
URL = "/api/v1/bet-slips/intake/paste"
client = TestClient(app)


@pytest.fixture(autouse=True)
def fixtures() -> Iterator[None]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_event_catalog] = lambda: CATALOG
    yield
    app.dependency_overrides.clear()


def paste(text: str, **extra: Any) -> dict[str, Any]:
    response = client.post(URL, json={"text": text, "stake_usd": "10.00", **extra})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def codes(body: dict[str, Any]) -> list[str]:
    return [issue["code"] for issue in body["issues"]]


def test_combo_resolves_to_normalized_slip() -> None:
    text = "Chiefs ML @ 0.56 + KC/Bills over 47.5 @ .51"
    body = paste(text, gross_payout_usd="31.25")
    assert body["state"] == "RESOLVED", body["issues"]
    assert body["original_input"] == text
    assert body["slip"]["original_input"] == text
    ml, total = body["slip"]["legs"]
    assert ml["event_id"] == total["event_id"] == "fixture-kc-buf"
    assert (ml["market_type"], ml["side"], ml["line"]) == ("MONEYLINE", "HOME", None)
    assert (total["market_type"], total["side"], total["line"]) == ("TOTAL", "OVER", "47.5")
    assert total["market_price_usd"] == "0.51"
    assert total["settlement_rule_ref"] == "fixture-nfl-total"
    assert [leg["raw_text"] for leg in body["legs"]] == [
        "Chiefs ML @ 0.56",
        "KC/Bills over 47.5 @ .51",
    ]


def test_away_team_by_full_name_maps_to_away_side() -> None:
    body = paste("Buffalo Bills ML @ 0.44")
    assert body["state"] == "RESOLVED"
    assert body["slip"]["legs"][0]["side"] == "AWAY"


def test_shared_nickname_is_ambiguous_with_candidates() -> None:
    body = paste("Giants ML @ 0.40")
    assert body["state"] == "NEEDS_RESOLUTION"
    assert codes(body) == ["AMBIGUOUS_EVENT"]
    leg = body["legs"][0]
    assert leg["event_id"] is None and leg["side"] is None
    assert {c["event_id"] for c in leg["candidates"]} == {"fixture-nyg-dal", "fixture-sf-lad"}


def test_unknown_team_is_not_found() -> None:
    body = paste("Jets ML @ 0.40")
    assert codes(body) == ["EVENT_NOT_FOUND"]
    assert body["legs"][0]["market_type"] == "MONEYLINE"


def test_total_participants_must_share_one_event() -> None:
    assert codes(paste("Chiefs/Cowboys over 44 @ 0.5")) == ["EVENT_NOT_FOUND"]


def test_missing_settlement_rule_needs_resolution() -> None:
    body = paste("Chiefs -3.5 @ 0.52")
    assert body["state"] == "NEEDS_RESOLUTION"
    assert codes(body) == ["SETTLEMENT_UNCONFIRMED"]
    assert body["legs"][0]["line"] == "-3.5"
    assert body["legs"][0]["event_id"] == "fixture-kc-buf"


def test_missing_price_needs_resolution() -> None:
    body = paste("Chiefs ML")
    assert codes(body) == ["MISSING_FIELD"]
    assert body["legs"][0]["event_id"] == "fixture-kc-buf"


@pytest.mark.parametrize(
    ("text", "code"),
    [("Yankees ML @ 0.6", "UNSUPPORTED_STATUS"), ("Seahawks ML @ 0.6", "UNSUPPORTED_STATUS")],
)
def test_live_and_completed_events_are_rejected(text: str, code: str) -> None:
    body = paste(text)
    assert body["state"] == "REJECTED"
    assert code in codes(body)
    assert body["slip"] is None


def test_bad_price_is_rejected() -> None:
    body = paste("Chiefs ML @ 1.2")
    assert body["state"] == "REJECTED"
    assert codes(body) == ["MALFORMED_INPUT"]


def test_unparseable_leg_keeps_other_legs() -> None:
    body = paste("Chiefs ML @ 0.56\nMahomes 2+ TDs @ 0.4")
    assert body["state"] == "NEEDS_RESOLUTION"
    assert [leg["state"] for leg in body["legs"]] == ["RESOLVED", "NEEDS_RESOLUTION"]
    assert body["issues"][0]["code"] == "UNPARSEABLE_LEG"
    assert body["issues"][0]["leg_index"] == 1


def test_separators_only_is_unparseable() -> None:
    assert codes(paste(" ; ")) == ["UNPARSEABLE_LEG"]


def test_empty_catalog_never_resolves() -> None:
    app.dependency_overrides.pop(get_event_catalog)
    assert codes(paste("Chiefs ML @ 0.56")) == ["EVENT_NOT_FOUND"]


def test_malformed_request_returns_structured_error() -> None:
    response = client.post(URL, json={"text": "", "stake_usd": "-1"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "MALFORMED_INPUT"
    assert {issue["field"] for issue in body["issues"]} == {"text", "stake_usd"}

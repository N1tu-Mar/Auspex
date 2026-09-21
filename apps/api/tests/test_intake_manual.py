import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.intake import get_now
from app.main import app

FIXTURE = json.loads(
    (Path(__file__).parents[3] / "packages/contracts/fixtures/bet_slip.valid.json").read_text()
)
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
URL = "/api/v1/bet-slips/intake/manual"
client = TestClient(app)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_session] = lambda: MagicMock()
    yield
    app.dependency_overrides.clear()


def resolved_slip(**leg_changes: Any) -> dict[str, Any]:
    legs = [
        {**leg, "settlement_rule_ref": "fixture-rule", **leg_changes} for leg in FIXTURE["legs"]
    ]
    return {**FIXTURE, "legs": legs}


def codes(body: dict[str, Any]) -> list[str]:
    return [issue["code"] for issue in body["issues"]]


def test_complete_pregame_slip_resolves_with_audit_fields() -> None:
    body = client.post(URL, json=resolved_slip()).json()
    assert body["state"] == "RESOLVED"
    assert body["issues"] == []
    assert body["source"] == "manual"
    assert body["original_input"] == FIXTURE["original_input"]
    assert body["received_at_utc"] == "2026-10-01T12:00:00Z"
    assert len(body["trace_id"]) == 36
    assert body["slip"]["legs"][0]["event_start_utc"] == "2026-10-05T00:25:00Z"
    assert [leg["state"] for leg in body["legs"]] == ["RESOLVED", "RESOLVED"]


def test_missing_settlement_needs_resolution_and_returns_editable_legs() -> None:
    body = client.post(URL, json=FIXTURE).json()
    assert body["state"] == "NEEDS_RESOLUTION"
    assert body["slip"] is None
    assert codes(body) == ["SETTLEMENT_UNCONFIRMED", "SETTLEMENT_UNCONFIRMED"]
    assert body["legs"][1]["line"] == "47.5"
    assert body["legs"][1]["state"] == "NEEDS_RESOLUTION"


def test_unidentified_event_is_not_guessed() -> None:
    body = client.post(URL, json=resolved_slip(event_id=None)).json()
    assert body["state"] == "NEEDS_RESOLUTION"
    assert set(codes(body)) == {"EVENT_NOT_IDENTIFIED"}


@pytest.mark.parametrize("status", ["LIVE", "COMPLETED", "POSTPONED", "CANCELED", "UNSUPPORTED"])
def test_non_pregame_status_is_rejected(status: str) -> None:
    body = client.post(URL, json=resolved_slip(status=status)).json()
    assert body["state"] == "REJECTED"
    assert set(codes(body)) == {"UNSUPPORTED_STATUS"}
    assert body["slip"] is None


def test_started_event_is_rejected() -> None:
    body = client.post(URL, json=resolved_slip(event_start_utc="2026-10-01T11:59:00Z")).json()
    assert body["state"] == "REJECTED"
    assert set(codes(body)) == {"EVENT_STARTED"}


def test_side_market_mismatch_is_rejected() -> None:
    slip = resolved_slip()
    slip["legs"][1]["side"] = "HOME"
    body = client.post(URL, json=slip).json()
    assert body["state"] == "REJECTED"
    assert body["issues"][0] == {
        "code": "INVALID_SIDE",
        "message": "HOME is invalid for TOTAL.",
        "leg_index": 1,
        "field": "side",
    }
    assert [leg["state"] for leg in body["legs"]] == ["RESOLVED", "REJECTED"]


def test_draw_only_allowed_for_soccer() -> None:
    body = client.post(URL, json=resolved_slip(side="DRAW", line=None)).json()
    assert "INVALID_SIDE" in codes(body)


def test_malformed_body_returns_structured_error() -> None:
    slip = resolved_slip()
    slip["legs"][0]["market_price_usd"] = "1.50"
    response = client.post(URL, json=slip)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "MALFORMED_INPUT"
    assert body["issues"][0]["leg_index"] == 0
    assert body["issues"][0]["field"] == "legs.0.market_price_usd"
    assert "trace_id" in body


def test_validate_endpoint_keeps_default_error_shape() -> None:
    response = client.post("/api/v1/bet-slips/validate", json={**FIXTURE, "legs": []})
    assert response.status_code == 422
    assert "detail" in response.json()

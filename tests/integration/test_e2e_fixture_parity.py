"""Routed Playwright fixtures must be exactly what the real intake API returns.

The e2e suite serves tests/e2e/fixtures/paste-*.json in place of the paste endpoint because the
production event catalog is empty. This test replays each fixture's request through the real
FastAPI app with the fixture catalog, so a backend change that alters the response fails here
instead of leaving the browser tests green against a stale fixture.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.intake import CatalogEvent, get_event_catalog, get_now
from app.main import app

FIXTURES = Path(__file__).parents[1] / "e2e" / "fixtures"
NOW = datetime(2030, 9, 1, 12, tzinfo=UTC)
# Request each fixture answers. Gross payout is echoed into the resolved slip.
REQUESTS: dict[str, dict[str, Any]] = {
    "paste-combo.json": {"stake_usd": "1.00", "gross_payout_usd": "3.50"},
    "paste-ambiguous.json": {"stake_usd": "1.00"},
}
VOLATILE = {"trace_id", "received_at_utc", "bet_slip_id"}


@pytest.fixture(autouse=True)
def fixture_catalog() -> Iterator[None]:
    catalog = json.loads((FIXTURES / "catalog.json").read_text())
    app.dependency_overrides[get_now] = lambda: NOW
    events = [CatalogEvent.model_validate(event) for event in catalog]

    async def load() -> list[CatalogEvent]:
        return events

    app.dependency_overrides[get_event_catalog] = lambda: load
    yield
    app.dependency_overrides.clear()


def strip(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key not in VOLATILE}


@pytest.mark.parametrize("name", sorted(REQUESTS))
def test_fixture_matches_live_intake(name: str) -> None:
    fixture = json.loads((FIXTURES / name).read_text())
    request = {"text": fixture["original_input"], **REQUESTS[name]}
    response = TestClient(app).post("/api/v1/bet-slips/intake/paste", json=request)
    assert response.status_code == 200, response.text
    assert strip(response.json()) == strip(fixture)


def test_every_paste_fixture_is_covered() -> None:
    assert {path.name for path in FIXTURES.glob("paste-*.json")} == set(REQUESTS)


def test_ambiguous_choice_resolves_through_manual_intake() -> None:
    """The UI's correction path: take a candidate, add side and settlement, check manually."""
    leg = json.loads((FIXTURES / "paste-ambiguous.json").read_text())["legs"][0]
    chosen = {k: v for k, v in leg["candidates"][1].items() if k != "participants"}
    slip = {
        "original_input": "Giants ML @ 0.48",
        "stake_usd": "1.00",
        "legs": [
            {
                **chosen,
                "market_type": leg["market_type"],
                "side": "HOME",
                "market_price_usd": leg["market_price_usd"],
                "settlement_rule_ref": "qa-nfl-ml",
            }
        ],
    }
    body = TestClient(app).post("/api/v1/bet-slips/intake/manual", json=slip).json()
    assert body["state"] == "RESOLVED", body["issues"]
    assert body["slip"]["legs"][0]["event_id"] == "qa-nfl-nyg-phi"

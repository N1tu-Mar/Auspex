"""Paste intake resolved through the research catalog adapter, using deterministic fixtures."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import BetSlipRecord, IntakeRecord, get_session
from app.intake import get_now
from app.main import app
from app.providers import get_polymarket
from auspex_research.fixtures import FixtureTransport, json_fixture
from auspex_research.polymarket import PolymarketUSClient
from auspex_research.transport import Fetcher, RawResponse, RetryPolicy

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
GW = "https://gateway.polymarket.us"
LIST_URL = (
    f"{GW}/v1/events?active=true&closed=false&limit=100&offset=0"
    "&startTimeMax=2026-10-05T12%3A00%3A00Z&startTimeMin=2026-09-21T12%3A00%3A00Z"
)
client = TestClient(app)


def use_provider(response: RawResponse) -> None:
    fetcher = Fetcher(FixtureTransport({LIST_URL: response}), RetryPolicy(max_attempts=1))
    app.dependency_overrides[get_polymarket] = lambda: PolymarketUSClient(fetcher)


@pytest.fixture(autouse=True)
def wiring() -> Iterator[MagicMock]:
    session = MagicMock()
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_session] = lambda: session
    yield session
    app.dependency_overrides.clear()


def paste(text: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/bet-slips/intake/paste", json={"text": text, "stake_usd": "10.00"}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_provider_event_is_identified_but_home_away_is_not_guessed(wiring: MagicMock) -> None:
    use_provider(json_fixture("polymarket_us/events.nfl_window.synthetic.json"))
    body = paste("Chiefs ML @ 0.56")
    leg = body["legs"][0]
    assert leg["event_id"] == "9001"  # 9002 has no league tag, so it is not resolvable
    assert leg["side"] is None and leg["home_participant"] is None
    assert [(i["code"], i["field"]) for i in body["issues"]] == [("MISSING_FIELD", "side")]
    assert body["state"] == "NEEDS_RESOLUTION"
    assert body["slip"] is None and body["bet_slip_id"] is None
    stored = [c.args[0] for c in wiring.add.call_args_list]
    assert [type(r) for r in stored] == [IntakeRecord]
    assert str(stored[0].id) == body["trace_id"]


def test_total_with_provider_event_still_needs_home_away_and_settlement() -> None:
    use_provider(json_fixture("polymarket_us/events.nfl_window.synthetic.json"))
    body = paste("Chiefs/Bills over 47.5 @ 0.51")
    codes = [i["code"] for i in body["issues"]]
    assert body["state"] == "NEEDS_RESOLUTION"
    assert codes.count("MISSING_FIELD") == 2 and "SETTLEMENT_UNCONFIRMED" in codes


def test_league_outside_modeled_set_is_not_found() -> None:
    use_provider(json_fixture("polymarket_us/events.nfl_window.synthetic.json"))
    body = paste("Dolphins ML @ 0.40")  # fixture event has no league tag
    assert [i["code"] for i in body["issues"]] == ["EVENT_NOT_FOUND"]


def test_provider_outage_is_explicit_not_a_missing_event() -> None:
    use_provider(RawResponse(503, b"{}"))
    body = paste("Chiefs ML @ 0.56")
    assert [i["code"] for i in body["issues"]] == ["CATALOG_UNAVAILABLE"]
    assert body["state"] == "NEEDS_RESOLUTION"
    assert "UNAVAILABLE" in body["issues"][0]["message"]


def test_resolved_manual_slip_is_stored_with_its_snapshot(wiring: MagicMock) -> None:
    fixture = json.loads(
        (Path(__file__).parents[3] / "packages/contracts/fixtures/bet_slip.valid.json").read_text()
    )
    slip = {**fixture, "legs": [{**leg, "settlement_rule_ref": "r"} for leg in fixture["legs"]]}
    body = client.post("/api/v1/bet-slips/intake/manual", json=slip).json()
    assert body["state"] == "RESOLVED" and body["bet_slip_id"]
    stored = [c.args[0] for c in wiring.add.call_args_list]
    assert [type(r) for r in stored] == [BetSlipRecord, IntakeRecord]
    assert str(stored[0].id) == body["bet_slip_id"] == str(stored[1].bet_slip_id)
    wiring.commit.assert_called_once()

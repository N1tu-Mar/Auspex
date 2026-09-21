"""End to end against PostgreSQL with deterministic provider fixtures: intake -> analysis -> read.

Requires the database (`docker compose up -d db`); run with `pnpm test:db`. Rows are append-only,
so tests use fresh trace/analysis ids and never delete.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import analysis_models as m
from app.analysis import get_clock
from app.db import get_engine
from app.intake import get_now
from app.main import app
from app.providers import get_code_version, get_evidence_providers, get_polymarket
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.evidence import ClaimKind, EvidenceCategory, EvidenceItem, SourceSnapshot
from auspex_research.fixtures import FixtureTransport, json_fixture
from auspex_research.polymarket import PolymarketUSClient
from auspex_research.providers import ProviderResponse, SourceIdentity
from auspex_research.transport import Fetcher, RawResponse, RetryPolicy

pytestmark = pytest.mark.db

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
GW = "https://gateway.polymarket.us"
MARKET_URL = f"{GW}/v1/market/id/fixture-mkt-1001"
MARKET_FIXTURE = "polymarket_us/market_by_slug.nfl_moneyline.synthetic.json"
START = "2026-09-27T20:25:00Z"
client = TestClient(app)


def leg(**changes: Any) -> dict[str, Any]:
    return {
        "sport": "NFL",
        "league": "NFL",
        "event_id": "9001",
        "event_start_utc": START,
        "home_participant": "Buffalo Bills",
        "away_participant": "Kansas City Chiefs",
        "market_type": "MONEYLINE",
        "side": "AWAY",
        "polymarket_market_id": "fixture-mkt-1001",
        "market_price_usd": "0.54",
        "settlement_rule_ref": "fixture-rule",
        "status": "PREGAME",
        **changes,
    }


def slip(*legs: dict[str, Any]) -> dict[str, Any]:
    return {"legs": list(legs), "stake_usd": "10.00", "original_input": "fixture"}


class NewsProvider:
    source = SourceIdentity("news_fixture", "Fixture News", "https://news.example")
    category = EvidenceCategory.NEWS

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def fetch_evidence(self, event: Any) -> ProviderResponse[tuple[EvidenceItem, ...]]:
        if self.fail:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "news_fixture", "no response in 5s")
        item = EvidenceItem(
            event_id=event.event_id,
            category=EvidenceCategory.NEWS,
            claim_kind=ClaimKind.RUMOR,
            extracted_fact="Fixture: a starter is questionable.",
            source=SourceSnapshot(
                provider="news_fixture",
                publisher="Fixture News",
                url="https://news.example/a",
                retrieved_at=NOW - timedelta(minutes=5),
            ),
        )
        return ProviderResponse(
            self.source, "https://news.example/a", NOW - timedelta(minutes=5), (item,)
        )


class StaleNews(NewsProvider):
    async def fetch_evidence(self, event: Any) -> ProviderResponse[tuple[EvidenceItem, ...]]:
        response = await super().fetch_evidence(event)
        old = response.data[0].source.model_copy(update={"retrieved_at": NOW - timedelta(days=3)})
        item = response.data[0].model_copy(update={"source": old, "evidence_id": ""})
        return ProviderResponse(self.source, response.url, response.retrieved_at, (item,))


def wire(market: RawResponse | None = None, evidence: list[Any] | None = None) -> None:
    routes = {
        MARKET_URL: market
        or json_fixture("polymarket_us/market_by_slug.nfl_moneyline.synthetic.json")
    }
    fetcher = Fetcher(FixtureTransport(routes), RetryPolicy(max_attempts=1), clock=lambda: NOW)
    app.dependency_overrides[get_polymarket] = lambda: PolymarketUSClient(fetcher)
    app.dependency_overrides[get_evidence_providers] = lambda: evidence or []


@pytest.fixture(autouse=True, scope="module")
def migrated() -> None:
    command.upgrade(Config(str(Path(__file__).parents[3] / "alembic.ini")), "head")


@pytest.fixture(autouse=True)
def frozen() -> Iterator[None]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    app.dependency_overrides[get_code_version] = lambda: "test-sha"
    wire()
    yield
    app.dependency_overrides.clear()


def intake(*legs: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/v1/bet-slips/intake/manual", json=slip(*legs))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def analyze(trace_id: str, **extra: Any) -> Any:
    return client.post("/api/v1/analyses", json={"intake_trace_id": trace_id, **extra})


def test_intake_is_stored_and_retrievable_by_trace_id() -> None:
    saved = intake(leg())
    fetched = client.get(f"/api/v1/bet-slips/intake/{saved['trace_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == saved
    assert saved["state"] == "RESOLVED" and saved["bet_slip_id"]


def test_unresolved_intake_is_stored_and_not_analyzable() -> None:
    saved = intake(leg(settlement_rule_ref=None))
    assert client.get(f"/api/v1/bet-slips/intake/{saved['trace_id']}").json() == saved
    assert saved["state"] == "NEEDS_RESOLUTION" and saved["bet_slip_id"] is None
    response = analyze(saved["trace_id"])
    assert response.status_code == 409
    assert response.json()["code"] == "INTAKE_NOT_RESOLVED"
    assert response.json()["trace_id"]


def test_unknown_ids_return_structured_404() -> None:
    for url in (f"/api/v1/bet-slips/intake/{uuid.uuid4()}", f"/api/v1/analyses/{uuid.uuid4()}"):
        response = client.get(url)
        assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"
    assert analyze(str(uuid.uuid4())).status_code == 404


def test_request_needs_exactly_one_id() -> None:
    response = client.post("/api/v1/analyses", json={})
    assert response.status_code == 422 and response.json()["code"] == "MALFORMED_INPUT"


def test_single_leg_without_a_model_is_insufficient_data_with_reasons_and_provenance() -> None:
    saved = intake(leg())
    response = analyze(saved["trace_id"], estimated_fees_usd="0.10", estimated_slippage_usd="0.05")
    assert response.status_code == 201, response.text
    body = response.json()
    run = body["analysis"]
    assert run["recommendation"]["recommendation"] == "INSUFFICIENT_DATA"
    reasons = run["recommendation"]["insufficient_data"]["reasons"]
    assert any("missing" in r or "feature" in r for r in reasons), reasons
    assert run["legs"][0]["estimate"] is None  # no fake probability
    assert run["legs"][0]["market_implied_probability"] == "0.54"
    assert run["code_version"] == "test-sha" and run["model_version"] == "none"
    assert run["as_of_utc"] == "2026-09-21T12:00:00Z"
    assert (
        run["bet_slip_id"] == saved["bet_slip_id"] and run["intake_record_id"] == saved["trace_id"]
    )
    assert run["expected_value"] is None and run["combo"] is None
    leg_row = run["legs"][0]
    assert body["market_snapshots"][0]["id"] == leg_row["market_snapshot_id"]
    assert body["evidence_snapshots"][0]["snapshot_id"] == leg_row["evidence_snapshot_id"]
    assert body["feature_snapshots"][0]["id"] == leg_row["feature_snapshot_id"]
    assert body["feature_snapshots"][0]["feature_set_version"] == "unassembled-v0"
    assert body["provider_failures"] == []


def test_saved_analysis_is_returned_identically_and_reruns_are_new_records() -> None:
    saved = intake(leg())
    first = analyze(saved["trace_id"]).json()
    again = client.get(f"/api/v1/analyses/{first['analysis']['id']}")
    assert again.status_code == 200 and again.json() == first
    second = analyze(saved["trace_id"]).json()
    assert second["analysis"]["id"] != first["analysis"]["id"]
    with Session(get_engine()) as session:
        count = session.scalar(
            select(func.count())
            .select_from(m.AnalysisRunRecord)
            .where(m.AnalysisRunRecord.bet_slip_id == uuid.UUID(saved["bet_slip_id"]))
        )
    assert count == 2


def test_bet_slip_id_can_start_an_analysis() -> None:
    saved = intake(leg())
    response = client.post("/api/v1/analyses", json={"bet_slip_id": saved["bet_slip_id"]})
    assert response.status_code == 201
    assert response.json()["analysis"]["intake_record_id"] == saved["trace_id"]


def test_partial_provider_failure_returns_evidence_and_explicit_failures() -> None:
    wire(evidence=[NewsProvider(), NewsProvider(fail=True)])
    body = analyze(intake(leg())["trace_id"]).json()
    evidence = body["evidence_snapshots"][0]
    assert [i["extracted_fact"] for i in evidence["items"]] == [
        "Fixture: a starter is questionable."
    ]
    assert [(f["provider"], f["kind"]) for f in body["provider_failures"]] == [
        ("news_fixture", "TIMEOUT")
    ]
    assert client.get(f"/api/v1/analyses/{body['analysis']['id']}").json() == body


def test_stale_evidence_is_dropped_and_reported_not_used() -> None:
    wire(evidence=[StaleNews()])
    body = analyze(intake(leg())["trace_id"]).json()
    assert body["evidence_snapshots"][0]["items"] == []
    (failure,) = body["provider_failures"]
    assert failure["message"].startswith("[STALE]") and failure["kind"] == "UNAVAILABLE"


def test_market_provider_failure_is_recorded_and_analysis_still_completes() -> None:
    wire(market=RawResponse(503, b"{}"))
    body = analyze(intake(leg())["trace_id"]).json()
    assert body["market_snapshots"] == []
    assert body["analysis"]["legs"][0]["market_snapshot_id"] is None
    assert [f["provider"] for f in body["provider_failures"]] == ["polymarket_us"]
    assert body["analysis"]["recommendation"]["recommendation"] == "INSUFFICIENT_DATA"


def test_combo_gets_baseline_warnings_and_no_joint_probability() -> None:
    saved = intake(
        leg(), leg(market_type="TOTAL", side="OVER", line="47.5", market_price_usd="0.50")
    )
    body = analyze(saved["trace_id"]).json()
    combo = body["analysis"]["combo"]
    assert combo["naive_baseline"]["probability"] == "0.2700"
    assert combo["naive_baseline"]["label"] == "NAIVE_INDEPENDENT_BASELINE"
    assert "SHARED_GAME" in {w["kind"] for w in combo["warnings"]}
    assert "correlation" in " ".join(combo["joint_probability"]["reasons"])
    assert body["analysis"]["recommendation"]["recommendation"] == "INSUFFICIENT_DATA"
    assert len(body["evidence_snapshots"]) == 1  # one event, one evidence snapshot


def test_unmodeled_sport_abstains_with_a_reason() -> None:
    soccer = leg(sport="SOCCER", league="EPL", side="HOME", market_type="MONEYLINE")
    body = analyze(intake(soccer)["trace_id"]).json()
    reasons = body["analysis"]["legs"][0]["insufficient_data"]["reasons"]
    assert reasons == ["no model coverage for SOCCER"]


def test_mismatched_market_blocks_the_recommendation() -> None:
    body = analyze(intake(leg(market_type="TOTAL", side="OVER", line="47.5"))["trace_id"]).json()
    reasons = body["analysis"]["recommendation"]["insufficient_data"]["reasons"]
    assert any("is MONEYLINE, not TOTAL" in r for r in reasons), reasons

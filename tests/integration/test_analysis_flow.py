"""Black-box analysis flow against PostgreSQL with deterministic provider fixtures.

intake -> persisted retrieval -> analysis -> reload by id. Requires `docker compose up -d db`
(run with `pnpm test:db`). Rows are append-only, so tests use fresh ids and never delete.
Evidence conflicts are not detected by any service yet; the conflict test pins that both claims
survive verbatim with their own provenance instead of being merged or dropped.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.analysis import get_clock
from app.intake import get_now
from app.main import app
from app.providers import get_code_version, get_evidence_providers, get_polymarket
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.evidence import ClaimKind, EvidenceCategory, EvidenceItem, SourceSnapshot
from auspex_research.fixtures import FixtureTransport, json_fixture
from auspex_research.polymarket import PolymarketUSClient
from auspex_research.providers import ProviderResponse, SourceIdentity
from auspex_research.transport import Fetcher, RetryPolicy

pytestmark = pytest.mark.db

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
MARKET_URL = "https://gateway.polymarket.us/v1/market/id/fixture-mkt-1001"
client = TestClient(app)


def leg(**changes: Any) -> dict[str, Any]:
    return {
        "sport": "NFL",
        "league": "NFL",
        "event_id": "9001",
        "event_start_utc": "2026-09-27T20:25:00Z",
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


class Provider:
    """One deterministic evidence provider: a fixed fact, a failure, or an old retrieval."""

    category = EvidenceCategory.NEWS

    def __init__(
        self,
        name: str,
        fact: str = "",
        *,
        fail: bool = False,
        age: timedelta = timedelta(minutes=5),
    ) -> None:
        self.source = SourceIdentity(name, f"{name} publisher", f"https://{name}.example")
        self.name, self.fact, self.fail, self.age = name, fact, fail, age

    async def fetch_evidence(self, event: Any) -> ProviderResponse[tuple[EvidenceItem, ...]]:
        if self.fail:
            raise ProviderError(ProviderErrorKind.TIMEOUT, self.name, "no response in 5s")
        at = NOW - self.age
        item = EvidenceItem(
            event_id=event.event_id,
            category=self.category,
            claim_kind=ClaimKind.RUMOR,
            extracted_fact=self.fact,
            source=SourceSnapshot(
                provider=self.name,
                publisher=f"{self.name} publisher",
                url=f"https://{self.name}.example/a",
                retrieved_at=at,
            ),
        )
        return ProviderResponse(self.source, item.source.url, at, (item,))


def wire(evidence: list[Any] | None = None) -> None:
    fetcher = Fetcher(
        FixtureTransport(
            {MARKET_URL: json_fixture("polymarket_us/market_by_slug.nfl_moneyline.synthetic.json")}
        ),
        RetryPolicy(max_attempts=1),
        clock=lambda: NOW,
    )
    app.dependency_overrides[get_polymarket] = lambda: PolymarketUSClient(fetcher)
    app.dependency_overrides[get_evidence_providers] = lambda: evidence or []


@pytest.fixture(autouse=True, scope="module")
def migrated() -> None:
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


@pytest.fixture(autouse=True)
def frozen() -> Iterator[None]:
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    app.dependency_overrides[get_code_version] = lambda: "qa-sha"
    wire()
    yield
    app.dependency_overrides.clear()


def analyze(*legs: dict[str, Any], **extra: Any) -> dict[str, Any]:
    intake = client.post(
        "/api/v1/bet-slips/intake/manual", json={"legs": list(legs), "stake_usd": "10.00"}
    )
    assert intake.status_code == 200, intake.text
    response = client.post(
        "/api/v1/analyses", json={"intake_trace_id": intake.json()["trace_id"], **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def facts(body: dict[str, Any]) -> list[str]:
    return [i["extracted_fact"] for i in body["evidence_snapshots"][0]["items"]]


def test_intake_is_retrievable_by_trace_id_and_resolved_slip_is_stored() -> None:
    saved = client.post(
        "/api/v1/bet-slips/intake/manual", json={"legs": [leg()], "stake_usd": "10.00"}
    ).json()
    assert saved["state"] == "RESOLVED" and saved["bet_slip_id"]
    assert client.get(f"/api/v1/bet-slips/intake/{saved['trace_id']}").json() == saved


def test_resolved_slip_becomes_a_persisted_analysis_reloadable_by_id() -> None:
    body = analyze(leg())
    run = body["analysis"]
    assert run["recommendation"]["recommendation"] == "INSUFFICIENT_DATA"
    assert run["legs"][0]["estimate"] is None
    reloaded = client.get(f"/api/v1/analyses/{run['id']}")
    assert reloaded.status_code == 200 and reloaded.json() == body


def test_evidence_carries_publisher_url_and_retrieval_time() -> None:
    wire([Provider("wire", "Starter is questionable.")])
    (item,) = analyze(leg())["evidence_snapshots"][0]["items"]
    assert item["source"]["publisher"] == "wire publisher"
    assert item["source"]["url"] == "https://wire.example/a"
    assert item["source"]["retrieved_at"] == "2026-09-21T11:55:00Z"


def test_conflicting_claims_are_both_kept_with_their_own_provenance() -> None:
    wire([Provider("north", "Starter is out."), Provider("south", "Starter will play.")])
    body = analyze(leg())
    assert sorted(facts(body)) == ["Starter is out.", "Starter will play."]
    assert {i["source"]["provider"] for i in body["evidence_snapshots"][0]["items"]} == {
        "north",
        "south",
    }
    assert body["provider_failures"] == []


def test_one_failing_provider_leaves_the_other_evidence_usable() -> None:
    wire([Provider("ok", "Dry field."), Provider("down", fail=True)])
    body = analyze(leg())
    assert facts(body) == ["Dry field."]
    assert [(f["provider"], f["kind"]) for f in body["provider_failures"]] == [("down", "TIMEOUT")]


def test_stale_evidence_is_dropped_and_the_analysis_abstains() -> None:
    wire([Provider("old", "Old news.", age=timedelta(days=3))])
    body = analyze(leg())
    assert facts(body) == []
    (failure,) = body["provider_failures"]
    assert failure["message"].startswith("[STALE]")
    assert body["analysis"]["recommendation"]["recommendation"] == "INSUFFICIENT_DATA"


def test_unsupported_model_coverage_abstains_with_the_reason() -> None:
    body = analyze(leg(sport="SOCCER", league="EPL", side="HOME"))
    reasons = body["analysis"]["legs"][0]["insufficient_data"]["reasons"]
    assert reasons == ["no model coverage for SOCCER"]


def test_same_game_combo_stores_a_correlation_warning() -> None:
    body = analyze(
        leg(), leg(market_type="TOTAL", side="OVER", line="47.5", market_price_usd="0.5")
    )
    combo = body["analysis"]["combo"]
    assert "SHARED_GAME" in {w["kind"] for w in combo["warnings"]}
    assert combo["naive_baseline"]["label"] == "NAIVE_INDEPENDENT_BASELINE"
    assert body["analysis"]["recommendation"]["recommendation"] == "INSUFFICIENT_DATA"


def test_analysis_request_needs_an_id_and_uses_the_error_envelope() -> None:
    response = client.post("/api/v1/analyses", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "MALFORMED_INPUT"

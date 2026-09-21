import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app
from app.settings import Settings

FIXTURE = json.loads(
    (Path(__file__).parents[3] / "packages/contracts/fixtures/bet_slip.valid.json").read_text()
)
client = TestClient(app)


@pytest.fixture
def session() -> Iterator[MagicMock]:
    fake = MagicMock()
    app.dependency_overrides[get_session] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def test_health_reports_database_ok(session: MagicMock) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}


def test_health_reports_database_unavailable(session: MagicMock) -> None:
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("down"))
    assert client.get("/api/health").json() == {"status": "ok", "database": "unavailable"}


def test_validate_normalizes_slip_to_utc() -> None:
    response = client.post("/api/v1/bet-slips/validate", json=FIXTURE)
    assert response.status_code == 200
    legs = response.json()["legs"]
    assert [leg["event_start_utc"] for leg in legs] == ["2026-10-05T00:25:00Z"] * 2


def test_validate_rejects_invalid_slip() -> None:
    response = client.post("/api/v1/bet-slips/validate", json={**FIXTURE, "legs": []})
    assert response.status_code == 422


def test_settings_require_psycopg_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="mysql://u:p@h/db")
    ok = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost:5432/db")
    assert ok.database_url.scheme == "postgresql+psycopg"

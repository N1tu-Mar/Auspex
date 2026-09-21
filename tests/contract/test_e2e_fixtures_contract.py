"""Every JSON fixture the browser suite serves must validate against the API's own models."""

import json
from pathlib import Path

import pytest

from app.intake import CatalogEvent, IntakeResult

FIXTURES = Path(__file__).parents[1] / "e2e" / "fixtures"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("paste-*.json")), ids=lambda p: p.name)
def test_paste_fixture_is_an_intake_result(path: Path) -> None:
    IntakeResult.model_validate_json(path.read_text())


def test_catalog_fixture_is_valid_and_future_dated() -> None:
    events = [
        CatalogEvent.model_validate(e) for e in json.loads((FIXTURES / "catalog.json").read_text())
    ]
    assert events
    # Real manual intake rejects started events; keep fixture events well in the future.
    assert all(event.event_start_utc.year >= 2030 for event in events)

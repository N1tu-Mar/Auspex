import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from auspex_contracts import BetSlip

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/bet_slip.valid.json").read_text())


def test_fixture_validates_and_normalizes_to_utc() -> None:
    slip = BetSlip.model_validate(FIXTURE)
    starts = {leg.event_start_utc for leg in slip.legs}
    assert starts == {datetime(2026, 10, 5, 0, 25, tzinfo=UTC)}
    assert all(leg.event_start_utc.utcoffset() is not None for leg in slip.legs)


def test_json_round_trip_is_lossless() -> None:
    slip = BetSlip.model_validate(FIXTURE)
    assert BetSlip.model_validate_json(slip.model_dump_json()) == slip


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("legs", 0, "event_start_utc"), "2026-10-04T20:25:00"),  # naive datetime
        (("legs", 0, "market_price_usd"), "1.00"),  # price must be < 1
        (("legs", 0, "market_price_usd"), "0"),
        (("legs", 0, "side"), "LEFT"),
        (("legs", 0, "unknown_field"), "x"),
        (("stake_usd",), "-1"),
        (("legs",), []),
    ],
)
def test_rejects_invalid_input(path: tuple[str | int, ...], value: object) -> None:
    data = json.loads(json.dumps(FIXTURE))
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        BetSlip.model_validate(data)

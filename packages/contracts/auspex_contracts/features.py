"""Feature snapshots: the exact model inputs for one event at one moment. Append-only."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, field_validator, model_validator

from auspex_contracts._base import Contract
from auspex_contracts.bet_slip import Sport


class FeatureObservation(Contract):
    """One feature value. Set at most one of the two values; neither means "source says unknown"."""

    value_decimal: Decimal | None = None
    value_text: str | None = None
    observed_at: AwareDatetime
    source_ref: str = Field(min_length=1, description="Evidence snapshot or source identifier.")

    @field_validator("observed_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _one_value(self) -> Self:
        if self.value_decimal is not None and self.value_text is not None:
            raise ValueError("set value_decimal or value_text, not both")
        return self


class FeatureSnapshot(Contract):
    id: UUID = Field(default_factory=uuid4)
    event_id: str = Field(min_length=1)
    sport: Sport
    captured_at: AwareDatetime
    feature_set_version: str = Field(
        min_length=1, description="Sport adapter feature definition version."
    )
    evidence_snapshot_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", description="Evidence the features derive from."
    )
    features: dict[str, FeatureObservation]

    @field_validator("captured_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _observed_before_capture(self) -> Self:
        for name, obs in self.features.items():
            if obs.observed_at > self.captured_at:
                raise ValueError(f"feature {name} observed after snapshot capture")
        return self

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Strict, immutable base for every contract: unknown fields are errors, instances frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

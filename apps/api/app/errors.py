"""Structured error envelope for non-validation failures (unknown ids, unmet preconditions)."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    INTAKE_NOT_RESOLVED = "INTAKE_NOT_RESOLVED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: uuid.UUID
    received_at_utc: AwareDatetime
    code: ErrorCode
    message: str


class ApiFailure(Exception):
    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


async def api_failure_handler(_: Request, exc: ApiFailure) -> JSONResponse:
    body = ApiError(
        trace_id=uuid.uuid4(), received_at_utc=datetime.now(UTC), code=exc.code, message=exc.message
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=exc.status)

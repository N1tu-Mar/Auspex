from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.intake import intake_error
from app.intake import router as intake_router
from app.settings import get_settings
from auspex_contracts import BetSlip


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_settings()  # fail fast on invalid environment
    yield


app = FastAPI(
    title="Auspex API",
    version="0.1.0",
    lifespan=lifespan,
    separate_input_output_schemas=False,
)
app.include_router(intake_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> Response:
    # Intake routes return the structured IntakeError envelope; others keep FastAPI's default.
    if request.url.path.startswith(intake_router.prefix):
        return JSONResponse(intake_error(exc).model_dump(mode="json"), status_code=422)
    return await request_validation_exception_handler(request, exc)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok", "unavailable"]


@app.get("/api/health")
def health(session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        database: Literal["ok", "unavailable"] = "ok"
    except SQLAlchemyError:
        database = "unavailable"
    return HealthResponse(status="ok", database=database)


@app.post("/api/v1/bet-slips/validate")
def validate_bet_slip(slip: BetSlip) -> BetSlip:
    """Validate and normalize a slip without persisting it. 422 on invalid input."""
    return slip

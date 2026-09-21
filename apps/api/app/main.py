from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
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

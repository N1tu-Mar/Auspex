"""Phase 1 market intake: manual and pasted pregame slips.

Intake never guesses. A leg is RESOLVED only when every event, participant, market,
and settlement detail is explicit; otherwise it is returned editable with issues.
Nothing here is persisted yet (see docs/workstreams/requests/backend-intake-persistence.md).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from auspex_contracts import BetLeg, BetSlip, LegStatus, MarketType, Side, Sport


class IntakeState(StrEnum):
    RESOLVED = "RESOLVED"
    NEEDS_RESOLUTION = "NEEDS_RESOLUTION"
    REJECTED = "REJECTED"


class IssueCode(StrEnum):
    MALFORMED_INPUT = "MALFORMED_INPUT"
    UNPARSEABLE_LEG = "UNPARSEABLE_LEG"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_SIDE = "INVALID_SIDE"
    UNEXPECTED_LINE = "UNEXPECTED_LINE"
    EVENT_NOT_IDENTIFIED = "EVENT_NOT_IDENTIFIED"
    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    AMBIGUOUS_EVENT = "AMBIGUOUS_EVENT"
    SETTLEMENT_UNCONFIRMED = "SETTLEMENT_UNCONFIRMED"
    UNSUPPORTED_STATUS = "UNSUPPORTED_STATUS"
    EVENT_STARTED = "EVENT_STARTED"


# Codes that make a leg unusable as submitted; everything else can be fixed by editing.
REJECTING = {
    IssueCode.MALFORMED_INPUT,
    IssueCode.INVALID_SIDE,
    IssueCode.UNEXPECTED_LINE,
    IssueCode.UNSUPPORTED_STATUS,
    IssueCode.EVENT_STARTED,
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntakeIssue(_Model):
    code: IssueCode
    message: str
    leg_index: int | None = None
    field: str | None = None


class EventCandidate(_Model):
    event_id: str
    sport: Sport
    league: str
    event_start_utc: AwareDatetime
    home_participant: str
    away_participant: str


class LegDraft(_Model):
    """Editable leg. Fields mirror BetLeg; unknown values stay null rather than guessed."""

    index: int
    state: IntakeState
    raw_text: str | None = None
    sport: Sport | None = None
    league: str | None = None
    event_id: str | None = None
    event_start_utc: AwareDatetime | None = None
    home_participant: str | None = None
    away_participant: str | None = None
    player_id: str | None = None
    market_type: MarketType | None = None
    side: Side | None = None
    line: Decimal | None = None
    polymarket_market_id: str | None = None
    market_price_usd: Decimal | None = None
    settlement_rule_ref: str | None = None
    status: LegStatus | None = None
    candidates: list[EventCandidate] = Field(default_factory=list)


class IntakeResult(_Model):
    trace_id: uuid.UUID
    received_at_utc: AwareDatetime
    source: Literal["manual", "paste"]
    state: IntakeState
    original_input: str | None
    legs: list[LegDraft]
    issues: list[IntakeIssue]
    slip: BetSlip | None = Field(
        default=None, description="Present only when state is RESOLVED; ready for analysis."
    )


class IntakeError(_Model):
    """Provider-independent error envelope for requests that cannot be read at all."""

    trace_id: uuid.UUID
    received_at_utc: AwareDatetime
    code: IssueCode
    message: str
    issues: list[IntakeIssue]


def get_now() -> datetime:
    return datetime.now(UTC)


Now = Annotated[datetime, Depends(get_now)]

ALLOWED_SIDES: dict[MarketType, set[Side]] = {
    MarketType.MONEYLINE: {Side.HOME, Side.AWAY, Side.DRAW},
    MarketType.SPREAD: {Side.HOME, Side.AWAY},
    MarketType.TOTAL: {Side.OVER, Side.UNDER},
    MarketType.PLAYER_PROP: {Side.OVER, Side.UNDER, Side.YES, Side.NO},
}


def check_leg(index: int, leg: BetLeg, now: datetime) -> list[IntakeIssue]:
    """Pregame intake rules for one fully typed leg."""
    issues: list[IntakeIssue] = []

    def add(code: IssueCode, message: str, field: str | None = None) -> None:
        issues.append(IntakeIssue(code=code, message=message, leg_index=index, field=field))

    if leg.status is not LegStatus.PREGAME:
        add(IssueCode.UNSUPPORTED_STATUS, f"{leg.status} legs are not supported.", "status")
    if leg.event_start_utc <= now:
        add(IssueCode.EVENT_STARTED, "Event has started; only pregame is supported.")
    if leg.side not in ALLOWED_SIDES[leg.market_type] or (
        leg.side is Side.DRAW and leg.sport is not Sport.SOCCER
    ):
        add(IssueCode.INVALID_SIDE, f"{leg.side} is invalid for {leg.market_type}.", "side")
    if leg.market_type is MarketType.MONEYLINE and leg.line is not None:
        add(IssueCode.UNEXPECTED_LINE, "Moneyline legs have no line.", "line")
    if leg.market_type in (MarketType.SPREAD, MarketType.TOTAL) and leg.line is None:
        add(IssueCode.MISSING_FIELD, "Line is required.", "line")
    if leg.market_type is MarketType.PLAYER_PROP and leg.player_id is None:
        add(IssueCode.MISSING_FIELD, "Player is required.", "player_id")
    if leg.market_type is not MarketType.PLAYER_PROP:
        for field in ("home_participant", "away_participant"):
            if getattr(leg, field) is None:
                add(IssueCode.MISSING_FIELD, "Both participants are required.", field)
    if leg.event_id is None:
        add(IssueCode.EVENT_NOT_IDENTIFIED, "Event is not identified.", "event_id")
    if leg.settlement_rule_ref is None:
        add(
            IssueCode.SETTLEMENT_UNCONFIRMED,
            "Settlement rule is not confirmed.",
            "settlement_rule_ref",
        )
    return issues


def state_of(issues: list[IntakeIssue]) -> IntakeState:
    if any(issue.code in REJECTING for issue in issues):
        return IntakeState.REJECTED
    return IntakeState.NEEDS_RESOLUTION if issues else IntakeState.RESOLVED


def build_result(
    source: Literal["manual", "paste"],
    original_input: str | None,
    legs: list[LegDraft],
    issues: list[IntakeIssue],
    slip: BetSlip | None,
    now: datetime,
) -> IntakeResult:
    state = state_of(issues)
    return IntakeResult(
        trace_id=uuid.uuid4(),
        received_at_utc=now,
        source=source,
        state=state,
        original_input=original_input,
        legs=legs,
        issues=issues,
        slip=slip if state is IntakeState.RESOLVED else None,
    )


router = APIRouter(prefix="/api/v1/bet-slips/intake", responses={422: {"model": IntakeError}})


@router.post("/manual")
def intake_manual(slip: BetSlip, now: Now) -> IntakeResult:
    """Check a manually entered slip against pregame intake rules. Not persisted."""
    issues: list[IntakeIssue] = []
    drafts: list[LegDraft] = []
    for index, leg in enumerate(slip.legs):
        leg_issues = check_leg(index, leg, now)
        issues += leg_issues
        drafts.append(LegDraft(index=index, state=state_of(leg_issues), **leg.model_dump()))
    return build_result("manual", slip.original_input, drafts, issues, slip, now)


def intake_error(exc: RequestValidationError) -> IntakeError:
    issues = []
    for error in exc.errors():
        loc = [str(part) for part in error["loc"] if part != "body"]
        leg_index = int(loc[1]) if len(loc) > 1 and loc[0] == "legs" and loc[1].isdigit() else None
        issues.append(
            IntakeIssue(
                code=IssueCode.MALFORMED_INPUT,
                message=error["msg"],
                leg_index=leg_index,
                field=".".join(loc) or None,
            )
        )
    return IntakeError(
        trace_id=uuid.uuid4(),
        received_at_utc=get_now(),
        code=IssueCode.MALFORMED_INPUT,
        message="Request body is malformed.",
        issues=issues,
    )

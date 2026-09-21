"""Phase 1 market intake: manual and pasted pregame slips.

Intake never guesses. A leg is RESOLVED only when every event, participant, market,
and settlement detail is explicit; otherwise it is returned editable with issues.
Every result, including unresolved and rejected ones, is persisted append-only and can be read
back by trace ID.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import BetSlipRecord, IntakeRecord, get_session
from app.errors import ApiError, ApiFailure, ErrorCode
from app.providers import get_polymarket
from auspex_contracts import BetLeg, BetSlip, LegStatus, MarketType, Side, Sport
from auspex_contracts.bet_slip import MarketPriceUsd, PositiveUsd
from auspex_research import catalog as research_catalog
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.providers import PolymarketProvider


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
    CATALOG_UNAVAILABLE = "CATALOG_UNAVAILABLE"
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
    home_participant: str | None = None
    away_participant: str | None = None
    participants: list[str] = Field(default_factory=list)


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
    bet_slip_id: uuid.UUID | None = Field(
        default=None, description="Stored slip snapshot; present only when state is RESOLVED."
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
    resolved = state is IntakeState.RESOLVED
    return IntakeResult(
        trace_id=uuid.uuid4(),
        received_at_utc=now,
        source=source,
        state=state,
        original_input=original_input,
        legs=legs,
        issues=issues,
        slip=slip if resolved else None,
        bet_slip_id=uuid.uuid4() if resolved and slip is not None else None,
    )


def persist(session: Session, result: IntakeResult) -> None:
    """Insert-only: one intake row, plus the slip snapshot when resolved."""
    try:
        if result.slip is not None:
            session.add(
                BetSlipRecord(
                    id=result.bet_slip_id,
                    original_input=result.slip.original_input,
                    slip=result.slip.model_dump(mode="json"),
                )
            )
            session.flush()
        session.add(
            IntakeRecord(
                id=result.trace_id,
                received_at=result.received_at_utc,
                source=result.source,
                state=result.state.value,
                original_input=result.original_input,
                result=result.model_dump(mode="json"),
                bet_slip_id=result.bet_slip_id,
            )
        )
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise ApiFailure(
            503, ErrorCode.PERSISTENCE_FAILED, "Result could not be stored; nothing was saved."
        ) from exc


router = APIRouter(prefix="/api/v1/bet-slips/intake", responses={422: {"model": IntakeError}})
Db = Annotated[Session, Depends(get_session)]


@router.post("/manual")
def intake_manual(slip: BetSlip, now: Now, session: Db) -> IntakeResult:
    """Check a manually entered slip against pregame intake rules and store the result."""
    issues: list[IntakeIssue] = []
    drafts: list[LegDraft] = []
    for index, leg in enumerate(slip.legs):
        leg_issues = check_leg(index, leg, now)
        issues += leg_issues
        drafts.append(LegDraft(index=index, state=state_of(leg_issues), **leg.model_dump()))
    result = build_result("manual", slip.original_input, drafts, issues, slip, now)
    persist(session, result)
    return result


@router.get("/{trace_id}", responses={404: {"model": ApiError}})
def get_intake(trace_id: uuid.UUID, session: Db) -> IntakeResult:
    """The stored intake result (editable legs, issues, normalized slip) for a trace ID."""
    record = session.get(IntakeRecord, trace_id)
    if record is None:
        raise ApiFailure(404, ErrorCode.NOT_FOUND, f"No intake record {trace_id}.")
    return IntakeResult.model_validate(record.result)


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


class CatalogEvent(_Model):
    """Known event used to resolve pasted participant names.

    `home_participant`/`away_participant` stay null when the provider does not say which side is
    which; a pasted moneyline/spread leg then stays unresolved instead of guessing a side.
    """

    event_id: str
    sport: Sport
    league: str
    event_start_utc: AwareDatetime
    home_participant: str | None = None
    away_participant: str | None = None
    teams: list[str] = Field(default_factory=list, description="Used when home/away is unknown.")
    aliases: dict[str, list[str]] = Field(
        default_factory=dict, description="Participant name -> accepted short names."
    )
    status: LegStatus = LegStatus.PREGAME
    settlement_rule_refs: dict[MarketType, str] = Field(default_factory=dict)

    def participants(self) -> list[str]:
        known = [self.home_participant, self.away_participant]
        return self.teams or [name for name in known if name]

    def identify(self, name: str) -> str | None:
        """The participant `name` refers to: exact match after normalization, else None."""
        wanted = research_catalog.normalize_name(name)
        for participant in self.participants():
            names = [participant, *self.aliases.get(participant, [])]
            if wanted in (research_catalog.normalize_name(n) for n in names):
                return participant
        return None

    def side_of(self, name: str) -> Side | None:
        participant = self.identify(name)
        if participant is None:
            return None
        if participant == self.home_participant:
            return Side.HOME
        return Side.AWAY if participant == self.away_participant else None

    def candidate(self) -> EventCandidate:
        return EventCandidate(
            **self.model_dump(include=set(EventCandidate.model_fields) - {"participants"}),
            participants=self.participants(),
        )


EventCatalog = Callable[[], Awaitable[list[CatalogEvent]]]

# Provider league slug -> (sport, league). Leagues outside the modeled set are not resolvable.
LEAGUES = {"nfl": (Sport.NFL, "NFL"), "mlb": (Sport.MLB, "MLB")}
CATALOG_WINDOW = timedelta(days=14)
CATALOG_PAGE = 100
CATALOG_MAX_PAGES = 10


def to_local(event: research_catalog.CatalogEvent) -> CatalogEvent | None:
    """Provider event -> resolvable event, or None if it lacks a start, league, or two teams."""
    league = LEAGUES.get(event.league_slug or "")
    if league is None or event.start_utc is None or len(event.teams) != 2:
        return None
    status = LegStatus.PREGAME
    if event.ended:
        status = LegStatus.COMPLETED
    elif event.live or not event.is_open:
        status = LegStatus.LIVE if event.live else LegStatus.UNSUPPORTED
    return CatalogEvent(
        event_id=event.event_id,
        sport=league[0],
        league=league[1],
        event_start_utc=event.start_utc,
        teams=[team.name for team in event.teams],
        aliases={
            team.name: [n for n in (team.abbreviation, team.alias, team.safe_name) if n]
            for team in event.teams
        },
        status=status,
    )


async def load_catalog(
    provider: PolymarketProvider, now: datetime, *, max_pages: int = CATALOG_MAX_PAGES
) -> list[CatalogEvent]:
    """Open provider events starting within the window. Raises ProviderError; never truncates."""
    events: list[CatalogEvent] = []
    for page_no in range(max_pages):
        response = await provider.list_events(
            start_after=now,
            start_before=now + CATALOG_WINDOW,
            limit=CATALOG_PAGE,
            offset=page_no * CATALOG_PAGE,
        )
        page = response.data
        events += [e for raw in page.events if (e := to_local(raw)) is not None]
        if len(page.events) + len(page.skipped) < CATALOG_PAGE:
            return events
    raise ProviderError(
        ProviderErrorKind.UNAVAILABLE, provider.source.provider, "catalog exceeds page cap"
    )


def get_event_catalog(
    provider: Annotated[PolymarketProvider, Depends(get_polymarket)], now: Now
) -> EventCatalog:
    return partial(load_catalog, provider, now)


class PasteIntakeRequest(_Model):
    text: str = Field(min_length=1, max_length=2000, description="Verbatim pasted slip text.")
    stake_usd: PositiveUsd
    gross_payout_usd: PositiveUsd | None = None


LEG_SPLIT = re.compile(r"\s*(?:\n|;|\s\+\s)\s*")
PRICE = re.compile(r"\s*@\s*(?P<price>\S+)$")
TOTAL = re.compile(
    r"^(?P<a>.+?)\s*/\s*(?P<b>.+?)\s+(?P<side>over|under|o|u)\s*(?P<line>\d+(?:\.\d+)?)$", re.I
)
MONEYLINE = re.compile(r"^(?P<team>.+?)\s+(?:ml|moneyline)$", re.I)
SPREAD = re.compile(r"^(?P<team>.+?)\s+(?P<line>[+-]\d+(?:\.\d+)?)$")


PRICE_ADAPTER: TypeAdapter[Decimal] = TypeAdapter(MarketPriceUsd)


def resolve_leg(
    index: int, raw: str, catalog: list[CatalogEvent], now: datetime
) -> tuple[LegDraft, list[IntakeIssue], BetLeg | None]:
    """Parse one pasted leg and resolve it against the catalog, or explain why not."""
    draft = LegDraft(index=index, state=IntakeState.NEEDS_RESOLUTION, raw_text=raw)

    def fail(
        code: IssueCode, message: str, field: str | None = None
    ) -> tuple[LegDraft, list[IntakeIssue], None]:
        issues = [IntakeIssue(code=code, message=message, leg_index=index, field=field)]
        return draft.model_copy(update={"state": state_of(issues)}), issues, None

    body, price = raw, None
    if match := PRICE.search(raw):
        body = raw[: match.start()]
        try:
            price = PRICE_ADAPTER.validate_python(match["price"])
        except ValidationError:
            return fail(
                IssueCode.MALFORMED_INPUT, "Price must be in (0, 1) USD.", "market_price_usd"
            )

    names: list[str]
    if match := TOTAL.match(body):
        names = [match["a"], match["b"]]
        market, line = MarketType.TOTAL, Decimal(match["line"])
        side: Side | None = Side.OVER if match["side"].lower().startswith("o") else Side.UNDER
    elif match := MONEYLINE.match(body):
        names, market, line, side = [match["team"]], MarketType.MONEYLINE, None, None
    elif match := SPREAD.match(body):
        names, market, line, side = [match["team"]], MarketType.SPREAD, Decimal(match["line"]), None
    else:
        return fail(
            IssueCode.UNPARSEABLE_LEG,
            "Use 'Team ML', 'Team -3.5', or 'Team A/Team B over 47.5', each with '@ price'.",
        )
    draft = draft.model_copy(
        update={"market_type": market, "line": line, "side": side, "market_price_usd": price}
    )

    matches = [event for event in catalog if all(event.identify(name) for name in names)]
    if not matches:
        return fail(IssueCode.EVENT_NOT_FOUND, f"No known event matches {' / '.join(names)}.")
    if len(matches) > 1:
        draft = draft.model_copy(update={"candidates": [event.candidate() for event in matches]})
        return fail(
            IssueCode.AMBIGUOUS_EVENT, f"{len(matches)} events match; choose one.", "event_id"
        )
    event = matches[0]
    if side is None:
        side = event.side_of(names[0])
    draft = draft.model_copy(
        update={
            **event.candidate().model_dump(exclude={"participants"}),
            "side": side,
            "status": event.status,
            "settlement_rule_ref": event.settlement_rule_refs.get(market),
        }
    )
    if side is None:
        return fail(
            IssueCode.MISSING_FIELD,
            "The provider does not say which team is home or away; choose the side.",
            "side",
        )
    if price is None:
        return fail(
            IssueCode.MISSING_FIELD, "Quoted price is required ('@ 0.55').", "market_price_usd"
        )

    leg = BetLeg(
        **draft.model_dump(
            exclude={"index", "state", "raw_text", "candidates", "market_price_usd"},
            exclude_none=True,
        ),
        market_price_usd=price,
    )
    issues = check_leg(index, leg, now)
    return draft.model_copy(update={"state": state_of(issues)}), issues, leg


Catalog = Annotated[EventCatalog, Depends(get_event_catalog)]


@router.post("/paste")
async def intake_paste(
    request: PasteIntakeRequest, catalog: Catalog, now: Now, session: Db
) -> IntakeResult:
    """Parse pasted slip text into editable legs; resolve only exact, unique provider matches.

    If the provider catalog cannot be read, every leg stays unresolved with CATALOG_UNAVAILABLE.
    """
    events: list[CatalogEvent] = []
    outage: IntakeIssue | None = None
    try:
        events = await catalog()
    except ProviderError as exc:
        outage = IntakeIssue(
            code=IssueCode.CATALOG_UNAVAILABLE,
            message=f"Event catalog unavailable ({exc.kind}); try again.",
        )
    issues: list[IntakeIssue] = []
    drafts: list[LegDraft] = []
    legs: list[BetLeg] = []
    for index, raw in enumerate(part for part in LEG_SPLIT.split(request.text.strip()) if part):
        draft, leg_issues, leg = resolve_leg(index, raw, events, now)
        if outage is not None and any(i.code is IssueCode.EVENT_NOT_FOUND for i in leg_issues):
            leg_issues = [outage.model_copy(update={"leg_index": index})]
        drafts.append(draft)
        issues += leg_issues
        if leg is not None:
            legs.append(leg)
    if not drafts:
        issues.append(IntakeIssue(code=IssueCode.UNPARSEABLE_LEG, message="No legs found."))
    slip = None
    if not issues:
        slip = BetSlip(
            original_input=request.text,
            legs=legs,
            stake_usd=request.stake_usd,
            gross_payout_usd=request.gross_payout_usd,
        )
    result = build_result("paste", request.text, drafts, issues, slip, now)
    persist(session, result)
    return result

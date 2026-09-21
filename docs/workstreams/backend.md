# Workstream: backend

## Objective

Phase 1 market-intake API slice: manual and pasted pregame slips become editable, normalized
results with explicit ambiguity/rejection states. Never guess events, participants, or settlement.

## Owned paths

`apps/api/**`, `docs/workstreams/backend.md`, `docs/workstreams/requests/backend-*.md`.

## Current base commit

`55611ba` (`main`). Branch `work/backend`, worktree `../auspex-backend`.

## Decisions made

- Endpoints (in `apps/api/app/intake.py`, router included in `app/main.py`):
  - `POST /api/v1/bet-slips/intake/manual`: body is the existing `BetSlip`; applies pregame intake rules.
  - `POST /api/v1/bet-slips/intake/paste`: body `{text, stake_usd, gross_payout_usd?}`; parses legs
    split on newline, `;`, or ` + `. Grammar: `Team ML @ 0.56`, `Team -3.5 @ 0.52`,
    `Team A/Team B over 47.5 @ .51`. Anything else is `UNPARSEABLE_LEG` (e.g. player props: use manual).
  - `POST /api/v1/bet-slips/validate` unchanged (still FastAPI default 422 shape).
- Response `IntakeResult`: `trace_id`, `received_at_utc`, `source`, `state`, `original_input`,
  editable `legs` (`LegDraft`, BetLeg fields all nullable + `raw_text`, `candidates`), `issues`
  (`code`, `message`, `leg_index`, `field`), and `slip` (a `BetSlip`) only when `RESOLVED`.
- States: `RESOLVED`; `NEEDS_RESOLUTION` (editable gaps: `EVENT_NOT_IDENTIFIED`, `EVENT_NOT_FOUND`,
  `AMBIGUOUS_EVENT` with candidates, `MISSING_FIELD`, `SETTLEMENT_UNCONFIRMED`, `UNPARSEABLE_LEG`);
  `REJECTED` (`UNSUPPORTED_STATUS` for LIVE/COMPLETED/POSTPONED/CANCELED/UNSUPPORTED,
  `EVENT_STARTED`, `INVALID_SIDE`, `UNEXPECTED_LINE`, `MALFORMED_INPUT`). Rejection wins over resolution.
- Missing `settlement_rule_ref` blocks resolution (settlement is never assumed).
- Unreadable intake bodies return 422 `IntakeError` (`trace_id`, `code=MALFORMED_INPUT`, per-field issues).
- Paste resolution uses an injectable `get_event_catalog` dependency (`list[CatalogEvent]`): exact,
  case-insensitive match on full participant name or listed alias; a leg resolves only if exactly one
  event matches (totals require both names in the same event). Production catalog is empty until a
  provider exists, so pasted legs return `EVENT_NOT_FOUND` rather than a guess.
- Clock is an injectable `get_now` dependency for deterministic tests.
- No persistence in this slice (see requests).

## Contracts consumed or produced

Consumed: `auspex_contracts.BetSlip`, `BetLeg`, enums, `MarketPriceUsd`, `PositiveUsd`.
Produced (API-local, appear in OpenAPI): `IntakeResult`, `IntakeError`, `IntakeIssue`, `IntakeState`,
`IssueCode`, `LegDraft`, `EventCandidate`, `PasteIntakeRequest`.

## Commands and tests

Run 2026-09-21 in `../auspex-backend`:

- `uv run pytest apps/api -m 'not db'` → 32 pass (new: `tests/test_intake_manual.py`, `tests/test_intake_paste.py`, fixture `tests/fixtures/intake_events.json`)
- `pnpm lint` → pass; `pnpm typecheck` → pass (mypy strict); `pnpm test` → 41 pytest + Vitest pass
- `pnpm contracts:check` → **fails (expected)**: OpenAPI drift from new routes; foundation must regenerate
- `git diff --check` → clean
- `pnpm test:db` not run (no DB changes in this slice)

## Known issues

- `pnpm check`/CI red on this branch until foundation regenerates contracts.
- Intake results are not persisted; trace IDs exist only in responses.
- No real event catalog; paste resolution only works with an injected catalog (tests use fixtures).
- Manual intake trusts a supplied `event_id`; it is not verified against a provider.
- Paste grammar is deliberately narrow: no player props, soccer draw, or American odds.

## Integration order

Merge `work/backend` into `main`, then foundation serves
`requests/backend-intake-contracts-regen.md`; frontend consumes regenerated types afterwards.

## Last completed commit

See `git log work/backend` — implementation `bfda657`, requests `0790572`; this note lands in the next commit.

## Next smallest task

Persist intake records once `requests/backend-intake-persistence.md` lands; wire catalog to the research
stream's Polymarket US adapter when available.

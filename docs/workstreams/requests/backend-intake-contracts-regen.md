# Request: regenerate contracts for intake endpoints

- From: backend (`work/backend`)
- To: foundation
- Blocking: `pnpm contracts:check` (and therefore `pnpm check` / CI) fails on `work/backend` until served.

## Change

Backend added two routes in `apps/api/app/intake.py`, which change the rendered OpenAPI document:

- `POST /api/v1/bet-slips/intake/manual` — body `BetSlip`, returns `IntakeResult`
- `POST /api/v1/bet-slips/intake/paste` — body `PasteIntakeRequest`, returns `IntakeResult`
- Both declare `422` as `IntakeError`.

New API-local schemas: `IntakeResult`, `IntakeError`, `IntakeIssue`, `IntakeState`, `IssueCode`,
`LegDraft`, `EventCandidate`, `PasteIntakeRequest`. No change to `auspex_contracts`.

## Ask

After merging `work/backend`, run `pnpm contracts` and commit the regenerated
`packages/contracts/openapi/openapi.json` and `packages/contracts/generated/api.d.ts`.

Open question for foundation: should `IntakeResult`/`LegDraft`/`IssueCode` move into
`auspex_contracts` as shared contracts? Backend kept them API-local to avoid editing shared contracts.

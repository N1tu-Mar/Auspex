# Workstream: frontend

## Objective

First user-facing slice: the New Analysis screen. Paste slip text or enter legs by hand, check them
against the backend intake API, fix unresolved legs, and review the resolved `BetSlip`. No
probability, price analysis, or recommendation is shown until the prediction engine is integrated.

## Owned paths

`apps/web/**`, `docs/workstreams/frontend.md`, `docs/workstreams/requests/frontend-*.md`.

## Current base commit

`a67506b` (`main`). Branch `work/frontend`, worktree `../auspex-frontend`.

## Decisions made

- Files: `src/api.ts` (typed fetch client), `src/slipForm.ts` (Zod schema, enum labels, draft/form/
  `BetSlip` conversion), `src/NewAnalysis.tsx` (form, leg editor, candidate picker),
  `src/CheckPanel.tsx` (result states, resolved-slip review), `src/App.tsx` (shell, health).
- Flow: **Parse into legs** → `POST /api/v1/bet-slips/intake/paste`; returned `LegDraft`s replace the
  legs. **Check legs** → `POST /api/v1/bet-slips/intake/manual` with the edited `BetSlip`. The
  resolved slip table renders `IntakeResult.slip` from the API, never local form state.
- Types come only from `@auspex/contracts`. Enum label maps are `Record<GeneratedEnum, string>`,
  so a new contract enum value fails `tsc` until a label is added.
- Zod checks shape and bounds only (price in (0, 1) with ≤4 decimals, USD > 0 with ≤2 decimals,
  required fields). Pregame, side, line, event, and settlement rules stay with the API.
- Decimal values are sent as strings to avoid float rounding.
- Event start uses `datetime-local` in browser time, sent as UTC ISO; review shows UTC.
- Server issues map to fields via `IntakeIssue.field` (`event_start_utc` → start input) and set
  `aria-invalid` and `aria-describedby`. Issues with no field show at the leg level; issues with
  no leg show at the slip level. Issue/leg mapping uses a client `uid` per leg, so removing a leg
  does not move issues to the wrong leg.
- States: empty; loading (`role=status`, buttons disabled); needs resolution; ambiguous (radio
  list of `candidates`, nothing preselected); rejected, with an explicit pregame-only message for
  `UNSUPPORTED_STATUS`/`EVENT_STARTED`; invalid (422 `IntakeError` field list); provider failure
  (network or non-422 error, input kept, **Try again**); stale (any edit after a check shows
  "Out of date" and hides the resolved slip until you check again).
- **Run analysis** is shown disabled, with a note that the prediction engine is not connected.
- Styling: Tailwind v4 via `@tailwindcss/vite`, with tokens in `src/index.css` `@theme`. IBM Plex
  Sans/Mono come from Google Fonts, with system fallbacks. Neutral surfaces, a left state rail per
  leg, and tabular monospace numbers.
- shadcn/ui was not added. Native inputs, selects, radios, and tables cover this slice. Add it
  when a dialog/drawer/combobox (e.g. the evidence drawer) needs Radix behaviour.
- `apps/web/biome.json` (nested, `extends: "//"`) enables Biome's Tailwind directive parsing
  without touching root tooling.

## Contracts consumed or produced

Consumed: `IntakeResult`, `IntakeError`, `IntakeIssue`, `LegDraft`, `EventCandidate`,
`PasteIntakeRequest`, `BetSlip`, `BetLeg`, `Sport`, `MarketType`, `Side`, `LegStatus`,
`IntakeState`, `HealthResponse`, `paths`. Produced: none.

## Commands and tests

Run 2026-09-21 in `../auspex-frontend`:

- `pnpm --filter web test` → 12 pass (`tests/NewAnalysis.test.tsx`: 10 tests covering
  paste-to-resolved-slip, ambiguity, live rejection, network failure + retry, 503, 422 fields,
  client validation, loading, add/remove; `tests/App.test.tsx`: 2 health tests)
- `pnpm --filter web typecheck` → pass; `pnpm --filter web build` → pass
- `pnpm lint` → pass; `pnpm contracts:check` → up to date
- Browser (Playwright/Chromium against host uvicorn + Vite, real intake API): paste two legs →
  `EVENT_NOT_FOUND` drafts → fill leg → `RESOLVED` slip → set LIVE → rejected. No console errors,
  no horizontal overflow at 390px. `pnpm test:e2e` smoke → 1 pass.
- `git diff --check` → clean

## Known issues

- The production event catalog is empty, so pasted legs always come back `EVENT_NOT_FOUND`. You
  must fill in event ID, participants, start time, side, and settlement ref by hand. Manual
  intake trusts the event ID you enter.
- There is no server-side staleness signal yet. "Stale" means the form changed after the last
  check. An event that starts after a check is only caught on the next check (`EVENT_STARTED`).
- Intake results are not persisted, and the page has no router or history. Refreshing the page
  loses its state.
- No dark theme. No Analysis Workspace, evidence drawer, or paper-trade screens yet.
- Dependency adds (`@tanstack/react-query`, `react-hook-form`, `zod`, `@hookform/resolvers`,
  `tailwindcss`, `@tailwindcss/vite`, dev `@testing-library/user-event`) changed the root
  `pnpm-lock.yaml`. That change is mechanical and limited to the `apps/web` importer. The
  integrator should confirm it against foundation's lockfile ownership.
- Paste-to-slip browser coverage lives in unit/integration tests and a throwaway local script.
  `tests/e2e/**` belongs to QA.

## Integration order

After backend and foundation (already on `main`). Merge `work/frontend` into `main`. QA can then add
`tests/e2e` coverage for the paste → resolve → review flow.

## Last completed commit

See `git log work/frontend`. This note lands with the final commit on the branch.

## Next smallest task

Analysis Workspace shell, once a prediction/analysis endpoint exists in the contract. Wire **Run
analysis** to it, with loading, partial, and insufficient-data states.

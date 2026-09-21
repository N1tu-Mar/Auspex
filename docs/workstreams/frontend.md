# Workstream: frontend

## Objective

The first polished Auspex interface. **New Analysis** takes pasted or manual input and checks it
through backend intake. **Intake review** shows every leg with its state and a recovery path. The
**Analysis Workspace** shell (`/analysis`) follows a resolved slip and reports `INSUFFICIENT_DATA`
until the analysis pipeline exists. No probabilities, EV, sources, or recommendations are
invented.

## Owned paths

`apps/web/**`, `docs/workstreams/frontend.md`, `docs/workstreams/requests/frontend-*.md`, and
the `pnpm-lock.yaml` entries for `apps/web` dependencies.

## Current base commit

`a67506b` (`main`). Branch `work/frontend`, worktree `../auspex-frontend`.

## Decisions made

- **Files** (`apps/web/src/`):
  - `api.ts`: typed fetch client. A network error or non-422 response is `unavailable`; a 422 with
    `IntakeError` is `invalid`.
  - `slipForm.ts`: Zod schema, enum label maps, and draft ↔ form ↔ `BetSlip` conversion.
  - `NewAnalysis.tsx`: Position, Paste, and leg editor with the candidate picker.
  - `CheckPanel.tsx`: intake summary aside, `LegReview` table, recovery hints, shared helpers.
  - `Workspace.tsx`: the analysis workspace shell.
  - `router.ts`: two routes on the History API.
  - `App.tsx`: header, primary nav, health, and view switching.
- **Flow:**
  1. **Parse into legs** calls `POST /api/v1/bet-slips/intake/paste`, and the returned
     `LegDraft`s become editable legs.
  2. **Check legs** calls `POST /api/v1/bet-slips/intake/manual`.
  3. A `RESOLVED` result shows **Open analysis workspace**, which pushes `/analysis` with the
     `IntakeResult` in `history.state`.
  4. The workspace survives a same-tab reload.
  5. The New Analysis view stays mounted (hidden), so the slip being edited survives a trip to
     the workspace and back.
- **Source is always visible:** a "From pasted text" or "Manual entry" badge on the summary, the
  review table, and the workspace. Leg cards say "Pasted: …" or "Entered by hand".
- **Review table** (`LegReview`) renders every `LegDraft`, whatever the state. Columns: event
  (participants or player, league · start UTC), market · side, line, price (USD), settlement rule
  (referenced/unconfirmed), and status (leg status · intake state). The region is named
  `Resolved slip` only when current and resolved; otherwise `Intake legs` or
  `Intake legs (out of date)`.
- **Recovery:** `RECOVERY: Record<IssueCode, string>`, typed from the generated enum so every code
  has a fix. It appears as a "How to fix" list in the summary and under leg-level issues.
- **Stated in the UI:**
  - "Partly resolved: N of M legs are ready" for partial success.
  - A pregame-only explanation for `UNSUPPORTED_STATUS` and `EVENT_STARTED`.
  - "No live event catalog is connected yet" in the paste section and in the `EVENT_NOT_FOUND`
    hint, so the fixture-backed or empty catalog is never presented as coverage.
- **Workspace panels:**
  - Recommendation header: `INSUFFICIENT_DATA` plus "Analysis pipeline not yet connected".
  - Probability versus price: the entered market price, with "Not estimated" for model
    probability and edge.
  - Legs, strongest to weakest: "Not ranked", entry order.
  - Correlation warnings: "Not checked". Detection belongs to the prediction service and is not
    duplicated in the UI.
  - Freshness and missing data: price age, with a warning after 15 min, plus a missing-inputs list.
  - Explanation and sources: empty. No unsourced claims.
  - Evidence drawer: native `<dialog>` that says none has been collected.
  - Record paper trade: `aria-disabled`, with the reason in its description.
- **Money and prices stay strings:**
  - Validation is by pattern only: USD `^\d+(\.\d{1,2})?$` and non-zero; price `^0?\.\d{1,4}$` and
    non-zero.
  - No `Number`, `parseFloat`, or `toFixed` on financial values.
  - Only elapsed time uses arithmetic.
- **Focus:**
  - Submit buttons use `aria-disabled` plus a pending guard, not `disabled`, so keyboard focus
    survives a request. This fixes QA's defect.
  - A route change moves focus to the start of the view. The first load keeps default focus.
  - Every control shows a `:focus-visible` outline.
- **shadcn/ui not added.** Native inputs, selects, radios, tables, and `<dialog>` (focus handling,
  Escape, backdrop) covered every need. Add shadcn when a combobox or popover needs Radix
  behaviour.
- **No new dependencies in this slice.** The router is ~20 lines on the History API. Switch to a
  router library when routes need params.

## Contracts consumed or produced

- **Consumed** (all from `@auspex/contracts`): `IntakeResult`, `IntakeError`, `IntakeIssue`,
  `IssueCode`, `IntakeState`, `LegDraft`, `EventCandidate`, `PasteIntakeRequest`, `BetSlip`,
  `BetLeg`, `Sport`, `MarketType`, `Side`, `LegStatus`, `HealthResponse`, `paths`.
- **Produced:** none.
- `INSUFFICIENT_DATA` is display copy only, because `Recommendation` is not in the generated
  OpenAPI yet.

## Commands and tests

Run 2026-09-21 in `../auspex-frontend`:

- `pnpm --filter web test` → 17 pass.
  - `NewAnalysis.test.tsx` (11):
    - paste → intake → edit → resolved review → open workspace
    - ambiguous candidate choice
    - live rejection with recovery path
    - partial resolution
    - network failure and retry
    - 503
    - 422 fields
    - browser validation
    - loading with `aria-disabled` and no double submit
    - add/remove
    - empty
  - `Workspace.test.tsx` (4):
    - `INSUFFICIENT_DATA` with no invented metrics or percentages
    - stale-price warning
    - empty workspace
    - nav round trip with `aria-current`
  - `App.test.tsx` (2).
- `pnpm --filter web typecheck`, `pnpm --filter web build`, `pnpm lint`, and
  `pnpm contracts:check` → pass.
- `git diff --check` → clean.

## Visual and accessibility checks

Playwright/Chromium, run against the host `uvicorn` API and Vite with the real intake API, at
1360×900 and 390×844:

- Paste 3 legs (2 not found, 1 unparseable) → review table and "How to fix" → complete the leg →
  resolved slip → workspace → evidence dialog → reload.
- Results:
  - No console or page errors.
  - No horizontal overflow on either view at 390px. This was fixed during the check: the
    workspace grid track grew to the table's `min-w`.
  - Keyboard: Enter on Parse keeps focus on the button. A route change focuses the view start,
    and Tab reaches "Back to slip" with a visible outline. The evidence dialog opens with Enter,
    closes with Escape, and returns focus to "Open evidence". "Record paper trade" stays
    focusable and described.
- QA's suite (`../auspex-qa`, `d68d344`) against this build: 15 pass, 3 fail, 2 skipped. All
  three failures come from intended changes; see `requests/frontend-qa-e2e-updates.md`.
- Not run: automated axe or contrast scan (not installed). The palette was chosen for contrast on
  `#fbfcfb`, but that has not been measured.

## Known issues

- The production event catalog is empty, so every pasted leg comes back `EVENT_NOT_FOUND` and
  must be completed by hand. Manual intake trusts the event ID you enter.
- Conflicting evidence and partial provider failure exist only as described states in the
  evidence drawer. There is no evidence contract to render (see
  `requests/frontend-analysis-contracts.md`). Partial success is covered at intake level.
- "Stale" means the form was edited after the last check, or prices are more than 15 min old
  (a fixed threshold) in the workspace. There is no server freshness signal.
- Nothing is persisted. A reload keeps the workspace but clears the New Analysis form.
- No dark theme. The History, Paper Trading, and Model Performance screens do not exist yet.

## Integration order

After backend and foundation (already on `main`). Merge `work/frontend`, then QA applies
`requests/frontend-qa-e2e-updates.md`.

## Last completed commit

`5a36d44` feat(web): intake leg review, recovery paths, analysis workspace shell. This note and the
requests land in the next commit.

## Next smallest task

Wire the workspace panels to the analysis endpoint once `requests/frontend-analysis-contracts.md`
is served.

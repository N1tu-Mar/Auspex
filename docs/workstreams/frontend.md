# Workstream: frontend

## Objective

The first polished Auspex interface. **New Analysis** takes pasted or manual input and checks it
through backend intake. **Intake review** shows every leg with its state and a recovery path. The
**Analysis Workspace** (`/analysis`) runs the typed analysis API for a resolved, saved slip, or
reloads a saved analysis (`/analysis?id=<uuid>`), and renders only what the record contains.
`INSUFFICIENT_DATA` shows its reasons and no invented numbers.

## Owned paths

`apps/web/**`, `docs/workstreams/frontend.md`, `docs/workstreams/requests/frontend-*.md`, and
the `pnpm-lock.yaml` entries for `apps/web` dependencies.

## Current base commit

`a67506b` (`main`). Branch `work/frontend`, worktree `../auspex-frontend`.

## Decisions made

- **Files** (`apps/web/src/`), plus `decimal.ts` and `Evidence.tsx`:
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
- **Workspace lifecycle** (`Workspace.tsx`):
  - Resolved intake with `bet_slip_id` shows **Run analysis** with optional fees and slippage
    (USD string pattern; never assumed, blank keeps EV unknown). `POST /api/v1/analyses`; on
    success the URL moves to `?id=` and the record is cached (`staleTime: Infinity`, records are
    immutable).
  - Pending guard plus `aria-disabled`, so no double submit and focus survives. Failure shows the
    server message with **Retry**. 409/422 read "Analysis refused".
  - `?id=` reloads via `GET /api/v1/analyses/{id}`: loading status, final "No saved analysis" on
    404, retry on outage. With no slip or id, the workspace offers an id field.
  - A resolved slip without `bet_slip_id` says it was not saved and cannot be analysed.
  - Leg names come from the open slip only when its `bet_slip_id` matches the record, else the
    market snapshot title.
- **Workspace panels** (all from `AnalysisRecord`): Recommendation with reasons; probability versus
  price per leg (market-implied, consensus, model with interval, edge; "Not available" when null,
  plus per-leg reasons); Expected value (break-even, edge, profit, return, costs); Combo and
  correlation (labelled naive baseline with its assumption, joint probability reasons,
  warnings as "size unquantified"); Freshness and versions; Evidence and paper trade.
- **Banners:** partial provider failure (each failed call, kind, time; `[STALE]`-prefixed messages
  shown as STALE), conflicting evidence, and a stale-analysis notice after 15 min.
- **Evidence drawer** (`Evidence.tsx`, native `<dialog>`): per item category, claim kind, fact,
  publisher (link only for http/https), published and retrieved times, age before cutoff,
  provider and hash prefixes, derived-from ids.
- **Paper trade:** `aria-disabled` with "the paper-trade endpoint does not exist yet".
- **Decimals** (`decimal.ts`): `fixed/pct/usd/signed` use BigInt string maths, half-up rounding;
  unparseable input is shown as is.
- **Money and prices stay strings:**
  - Validation is by pattern only: USD `^\d+(\.\d{1,2})?$` and non-zero; price `^0?\.\d{1,4}$` and
    non-zero.
  - No `Number`, `parseFloat`, or `toFixed` on financial values or probabilities.
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

- **Consumed** (all from `@auspex/contracts`): intake types as before, plus `AnalysisRequest`,
  `AnalysisRecord`, `AnalysisRun`, `LegAnalysis`, `LegEstimate`, `ExpectedValue`, `ComboAssessment`,
  `CorrelationWarning`, `EvidenceItem`, `SourceSnapshot`, `ProviderFailure`, `MarketSnapshot`,
  `Recommendation`, `ClaimKind`, `paths`.
- **Produced:** none. Regenerating `api.d.ts` needed a fix in `scripts/render_openapi.py` (foundation
  owned; see Known issues).

## Commands and tests

Run 2026-09-21 in `../auspex-frontend`:

- `pnpm --filter web test` → 29 pass. `Workspace.test.tsx` (16): decimal formatting; run → all
  panels; money validation, pending guard, and retry; refused (409); unsaved slip; reload by id;
  404 versus outage retry; INSUFFICIENT_DATA with no invented numbers; stale analysis and stale
  provider; partial provider failure; conflicting evidence with drawer provenance; non-web source
  URL not linked; combo baseline and warnings; paper trade disabled; open-by-id; `?id=` route.
- `pnpm --filter web typecheck`, `pnpm --filter web build`, `pnpm lint`, `pnpm contracts:check`
  → pass. `git diff --check` → clean.

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

- **Contract regeneration is uncommitted foundation work.** `pnpm contracts` failed with
  `schema name collision with an API model: AnalysisRun`. I changed `scripts/render_openapi.py` to
  let FastAPI's copy win (the only difference is `default: null`) and regenerated `api.d.ts` and
  `openapi.json`. Foundation should review and land that; see
  `requests/backend-to-foundation-analysis-contracts.md`.
- Conflict detection is a heuristic (the contract has no flag): same event and category
  (INJURY, LINEUP, WEATHER), different facts. Other categories are not compared.
- STALE provider failures are recognised by the backend's `[STALE]` message prefix until the
  contract has a `STALE` kind.
- Old-analysis warning is a fixed 15-minute threshold. Evidence age is shown, not judged: the
  backend drops evidence outside its category window.
- Leg names are unavailable on reload without the slip in tab state (market title is used).
- `tests/e2e/intake.spec.ts` (QA) still asserts the old placeholder workspace text.
- No dark theme. The History, Paper Trading, and Model Performance screens do not exist yet.

## Integration order

After backend and foundation (already on `main`). Merge `work/frontend`, then QA applies
`requests/frontend-qa-e2e-updates.md`.

## Last completed commit

See `git log` on `work/frontend`.

## Next smallest task

Add the paper-trade action when its endpoint exists; QA updates the e2e workspace assertions.

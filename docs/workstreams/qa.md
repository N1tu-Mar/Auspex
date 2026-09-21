# Workstream: qa

## Objective

Deterministic browser, integration, and contract coverage for the Phase 1 intake slice:
paste → resolve → review, plus its failure, ambiguity, stale, loading, and accessibility states.

## Owned paths

`tests/e2e/**`, `tests/integration/**`, `tests/contract/**`, `docs/workstreams/qa.md`,
`docs/workstreams/requests/qa-*.md`.

## Current base commit

`a67506b` (`main`). Branch `work/qa`, worktree `../auspex-qa`.

**Dependency:** the browser specs exercise the New Analysis UI on `work/frontend` (`4401441`), which is
not on `main` yet. Until it merges, `pnpm test:e2e` on `main` passes only `smoke.spec.ts`. Run the
suite against a stack served from the frontend worktree (see Commands).

## Decisions made

- Where possible, tests hit the real API. The production event catalog is empty, so pasted legs
  always return `EVENT_NOT_FOUND`. Single-market, combo-inspection, validation, unsupported,
  stale, and keyboard tests complete legs by hand and then check them with the real
  `/intake/manual`.
- Two scenarios need a catalog: a resolved pasted combo and an ambiguous event. For these, only
  `/intake/paste` is routed, via `page.route`, to `tests/e2e/fixtures/paste-*.json`. Those
  fixtures were generated from the real intake code with `fixtures/catalog.json`.
  `tests/integration/test_e2e_fixture_parity.py` replays them and fails if the real response
  drifts. The follow-up `/intake/manual` check stays real.
- Provider failure, loading, and unreachable-service states use `page.route`: fulfill 503,
  abort, or hold the request on a promise the test releases. No sleeps anywhere.
- `timezoneId: "UTC"` keeps `datetime-local` values equal to the UTC values shown in review.
- Fixture events are dated 2030 so real pregame checks stay valid. The contract test fails if one
  is older.
- Locators are role, label, and text only, scoped to `group "Leg N"` and the `complementary
  "Intake check"` landmark. There are no CSS selectors.
- Known defects are pinned with `test.fail()` and a request file. Unbuilt features use
  `test.fixme()` so the report shows the gap.

## Tests added

- `tests/e2e/support.ts`: helpers (`paste`, `fillLeg`, `servePaste`, `intakeCalls`,
  `resolveSingleMarket`).
- `tests/e2e/intake.spec.ts` (7):
  - single market resolved and reviewed
  - 4-leg pasted combo inspected per leg, including an unparseable leg
  - resolved combo review table, re-checked through the real API
  - ambiguous event corrected by choosing a candidate
  - browser-side validation with zero requests
  - API validation (`MALFORMED_INPUT`)
  - unsupported markets: `UNSUPPORTED_STATUS`, `EVENT_STARTED`, `INVALID_SIDE`
- `tests/e2e/states.spec.ts` (5 + 2 fixme):
  - empty
  - loading (announced, double submit blocked)
  - stale after edit
  - failed re-check keeps the earlier resolved result and the input, then retry
  - unreachable service keeps pasted text, then retry
- `tests/e2e/a11y.spec.ts` (5):
  - landmarks and headings
  - every leg control named
  - keyboard-only paste flow, with Enter-to-submit focusing the first invalid field
  - arrow-key candidate choice
  - `test.fail` focus-loss defect
- `tests/integration/test_e2e_fixture_parity.py` (4): fixture parity, fixture coverage, and the
  ambiguous → manual resolution path.
- `tests/contract/test_e2e_fixtures_contract.py` (3): fixtures validate against the API models.

## Commands and tests

Run 2026-09-21:

```bash
uv run pytest tests/integration tests/contract              # 7 passed
set -a; . ./.env.example; set +a; FE=../auspex-frontend
uv run --project $FE uvicorn app.main:app --app-dir $FE/apps/api --port 8000 &
pnpm --dir $FE --filter web exec vite --port 5173 --strictPort &
pnpm test:e2e                                                # 18 passed, 2 skipped (fixme)
pnpm exec playwright test --repeat-each=5                    # 90 passed, 10 skipped, 0 flaky
```

Also: `pnpm exec biome check .`, `uv run ruff check tests`, `uv run ruff format --check tests`,
and `uv run mypy --strict tests/integration tests/contract` all pass. `git diff --check` is clean.
Chromium, one worker (root `playwright.config.ts`, unchanged). After `docker compose up` on an
integrated `main`, the same suite runs against the Compose stack.

## Known issues

- **Resolved during frontend integration:** submit controls now use `aria-disabled` with a pending
  guard, so keyboard focus stays on the control. The formerly expected-failure test is active.
- Evidence, conflicting-evidence, and per-provider partial-failure scenarios cannot be tested:
  no evidence API or UI exists. They are tracked as `test.fixme`. The partial-failure test that
  does exist covers intake: a failed re-check keeps the earlier successful result.
- The frontend now has a small History API router and restores the current workspace after a
  same-tab reload. Persistence beyond the tab is still unimplemented.
- `tests/integration` and `tests/contract` are not in root pytest `testpaths` yet. See
  `requests/qa-foundation-pytest-testpaths.md`.
- CI's `stack` job will fail these specs until `work/frontend` merges to `main`.
- Only Chromium is covered. There are no visual-regression or automated axe/contrast checks.

## Integration order

Merge after `work/frontend`. Then `pnpm test:e2e` on `main` against Compose should report
18 passed and 2 skipped.

## Last completed commit

See `git log work/qa`. This note lands in the same commit as the tests.

## Next smallest task

Add e2e coverage for the Analysis Workspace, evidence drawer, and paper-trade capture as each
lands. Replace the two `fixme` evidence tests with real ones.

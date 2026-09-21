# Workstream: qa

## Objective

Deterministic browser, integration, and contract coverage for the Phase 1 intake slice:
paste → resolve → review, plus its failure, ambiguity, stale, loading, and accessibility states.

## Owned paths

`tests/e2e/**`, `tests/integration/**`, `tests/contract/**`, `docs/workstreams/qa.md`,
`docs/workstreams/requests/qa-*.md`.

## Current base commit

`main` after `merge(backend)` (intake persistence + `/api/v1/analyses`). Work landed directly on `main`.

**Dependency:** the browser specs need the web app from `main`. The API for e2e is
`tests/e2e/serve_api.py` (see Decisions), not plain uvicorn.

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
- Provider-backed paste (backend merge) calls the live Polymarket gateway, so plain `uvicorn` makes
  every paste `CATALOG_UNAVAILABLE` offline. `tests/e2e/serve_api.py` runs the real app with an empty
  catalog override (no app change) and restores the `EVENT_NOT_FOUND` behavior the specs assume.
- Analysis coverage is API-level (`tests/integration/test_analysis_flow.py`): fixture market + fake
  evidence providers injected through the app's dependency overrides, real PostgreSQL, frozen clock.
- The web workspace calls `/api/v1/analyses`. Live market data is not deterministic, so e2e serves
  those two routes from `tests/e2e/fixtures/analysis-<scenario>.json` (`serveAnalysis`). The fixtures
  are produced by the real flow: `test_e2e_analysis_fixture_matches_real_flow` fails on drift (UUIDs
  masked); `QA_REGEN=1 uv run pytest tests/integration/test_analysis_flow.py` rewrites them.
- The browser clock is pinned (`page.clock.setFixedTime`) one minute after the fixtures' cutoff.
- Known defects are pinned with `test.fail()` and a request file. Unbuilt features use
  `test.fixme()` so the report shows the gap.

## Tests added

Intake (unchanged): `intake.spec.ts` (7), `states.spec.ts` (5), `a11y.spec.ts` (5), see git history.

- `tests/e2e/workspace.spec.ts` (21, no fixme): run sends saved slip id and no assumed fees; fee
  validation blocks the request; no-evidence text; evidence publisher link, retrieval time and age;
  conflicting evidence with both sources; one provider failing keeps the other's evidence; stale
  evidence listed as too old with INSUFFICIENT_DATA; old-analysis banner; unsupported model reason;
  combo correlation warnings with no joint probability; single leg; failed run retry; saved analysis
  id (reload, fresh tab, open-by-id form, unknown id, loading announced); evidence dialog keyboard
  open, focus, Escape, modal Tab, Close, paper trade unavailable with description.
- `tests/integration/test_analysis_flow.py` (16, PostgreSQL; 7 are fixture-parity cases): intake retrievable by trace id; resolved
  slip to persisted analysis and identical reload by id; evidence publisher/url/retrieval time;
  conflicting claims both kept; one provider failing keeps the other's evidence; stale evidence
  dropped with `[STALE]` and INSUFFICIENT_DATA; unsupported sport abstains with reason; same-game
  combo stores `SHARED_GAME`; empty request uses the error envelope.
- `tests/integration/test_e2e_fixture_parity.py` (4) and `tests/contract/test_e2e_fixtures_contract.py`
  (3+7): analysis fixtures validate against `AnalysisRecord`; paste fixture regenerated for `participants`, `bet_slip_id` ignored as volatile.
- `tests/contract/test_analysis_contract.py` (2, no DB): OpenAPI routes and `AnalysisRecord` provenance
  collections.

## Commands and tests

Run 2026-09-21 (DB from `docker compose up -d db`):

```bash
set -a; . ./.env.example; set +a
uv run pytest tests/integration tests/contract              # 32 passed (contract-only: 12 without DATABASE_URL)
uv run python tests/e2e/serve_api.py &        # needs the DB: docker compose up -d db
pnpm --filter web exec vite --port 5173 --strictPort &
pnpm test:e2e                                               # 39 passed, 0 skipped
pnpm exec playwright test --repeat-each=3 workspace         # 63 passed, 0 flaky
```

Full-suite repeat check was not run (too slow); only the workspace spec was repeated.

Also `pnpm exec biome check .`, `uv run ruff check tests`, `uv run mypy --strict tests/integration
tests/contract` pass.

## Known issues

- Evidence conflicts are detected by a web heuristic (same event and category, different facts, for
  INJURY/LINEUP/WEATHER), not by a service. Tests cover that heuristic only.
- Every real analysis is INSUFFICIENT_DATA (no model/features). No test reaches CONSIDER/AVOID/PASS,
  expected value, or edge in e2e against real backend output.
- `contracts:check` is red on main (`AnalysisRun` name collision, request filed by backend).
- CI `stack` job and Compose run plain uvicorn: paste hits live Polymarket, so intake e2e specs fail
  offline or on catalog drift. Needs a test catalog switch in the API or a Compose override.
- `tests/integration` and `tests/contract` are not in root pytest `testpaths`
  (`requests/qa-foundation-pytest-testpaths.md`).
- Chromium only. No visual regression or automated axe checks. Screen-reader coverage is by
  accessible name/description assertions, not a real screen reader.

## Integration order

Merged into `main` after `work/backend`.

## Last completed commit

See `git log`. This note lands in the same commit as the tests.

## Next smallest task

Add a stubbed-estimator fixture (CONSIDER with EV) once a model can be ACTIVE, and paper-trade capture
when its endpoint exists.

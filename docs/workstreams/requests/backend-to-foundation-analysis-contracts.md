# Request: regenerate contracts and fix three contract gaps for the analysis workflow

- From: backend (`work/backend`)
- To: foundation (`scripts/**`, `packages/contracts/**`, migrations)
- Blocking: frontend consumption of the new routes. `pnpm contracts:check` fails on this branch.

## 1. `render_openapi.py` collision (blocking regeneration)

Now that routes return `AnalysisRun` (nested in `AnalysisRecord`), `pnpm contracts` aborts with
`schema name collision with an API model: AnalysisRun`. The only difference between FastAPI's schema
and the `models_json_schema` one is `"default": null` on optional fields (FastAPI drops it), plus key
order; also affects `EvidenceItem`, `FeatureSnapshot`, `Market`, `MarketSnapshot`, `LegAnalysis`,
`RecommendationResult`, `SourceSnapshot`, `MarketSideQuote`, `FeatureObservation`. Suggest: skip the
comparison for names already in the FastAPI document (they come from the same class), or compare
after dropping `default: null`. Then run `pnpm contracts`.

New/changed routes and API-local models to be picked up:
`POST /api/v1/analyses`, `GET /api/v1/analyses/{id}`, `GET /api/v1/bet-slips/intake/{trace_id}`;
`AnalysisRequest`, `AnalysisRecord`, `ApiError`, `ErrorCode`; `IntakeResult.bet_slip_id`;
`EventCandidate.participants` (home/away now optional); `IssueCode.CATALOG_UNAVAILABLE`.

## 2. `ProviderErrorKind` lacks `AUTH` and `STALE`

Research emits both. The contract enum and `ck_provider_failures_kind` only allow six kinds, so
backend maps `AUTH -> BAD_REQUEST` and `STALE -> UNAVAILABLE` and prefixes the message with the
original kind (`[STALE] ...`). Please add both kinds to the contract and the check constraint
(new migration), then backend drops the mapping (`KIND_MAP` in `app/analysis.py`).

## 3. Not linkable to a run

- `provider_failures.snapshot_id` is the only link from a failure to an analysis, so backend
  stores every failure (including market fetch failures) inside the event's evidence snapshot.
  A direct `analysis_id` on failures would be cleaner but is not required.
- Research `SourceRun` (per-call provenance: cache hit, attempts, item count) has no table or
  contract; it is not persisted. Ask only if the audit trail needs it.
- No `EventSnapshot` is produced: providers give no event-by-id lookup, and the contract's
  `SourceSnapshot.url` must be http(s), so a slip-derived snapshot cannot cite a source.
  `LegAnalysis.event_snapshot_id` stays null.

## Also touched outside `apps/api/**` (mechanical)

`uv.lock` (+6 lines: `auspex-api` now depends on research, prediction, sports workspace members).

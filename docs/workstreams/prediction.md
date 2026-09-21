# Workstream: prediction

## Objective

Phase 3 deterministic prediction foundation: typed, unit-tested pricing/EV/de-vig/combo primitives, a transparent correlation-warning framework, and the `SportAdapter` contract with narrow NFL/MLB pregame coverage. Phase 4 model-readiness layer: typed feature gates, model registry, estimate orchestration, uncertainty/confidence, recommendation policy, and evaluation primitives. No API endpoints, provider retrieval, persistence, UI, or LLM math.

## Owned paths

`services/prediction/**`, `services/sports/**`, this note, and `docs/workstreams/requests/prediction-*.md`.

## Current base commit

`55611ba` (`main`), branch `work/prediction`, worktree `../auspex-prediction`.

## Decisions made

- **Two failure channels.** Malformed input (wrong type, out of bounds, non-finite) raises `TypeError`/`ValueError`. Well-formed input that can't support an estimate returns `InsufficientData(reasons)`, with `status = Recommendation.INSUFFICIENT_DATA`.
- **No floats.** Every money and probability input must be `Decimal`. `float`, `int`, `str`, and `bool` are rejected; the one exception is American odds, which are `int`. Results are unrounded `Decimal` (28-digit context); round only for display.
- **Share semantics** (`odds.py`): a binary share costs `market_price_usd` in (0, 1) and pays 1.00 USD, so raw implied probability = price. This is an assumption, to be confirmed per market from Polymarket US settlement rules.
- **EV** (`ev.py`): `gross_payout_usd` includes the returned stake. `break_even_probability = (stake + fees + slippage) / gross_payout`, which can exceed 1. `expected_profit_usd = p * gross_payout - stake - fees - slippage`. `expected_return_pct` is expected profit / `stake_usd` × 100. Fees and slippage are always caller-supplied, never assumed.
- **De-vig** (`devig.py`): proportional method only. Requires the complete outcome set (≥2 outcomes) and rejects an underround, which means stale or mismatched quotes. Consensus is the median of per-book de-vigged probabilities across all fresh books, renormalized to sum to 1. It excludes stale, future-dated, and outcome-mismatched quotes, and returns `InsufficientData` below `min_books` (default 2).
- **Combos** (`combo.py`): `naive_independent_probability` is labeled `NAIVE_INDEPENDENT_BASELINE` and is for comparison only. `assess_combo` always returns `joint_probability = InsufficientData`, because no validated correlation model exists. Any leg that isn't pregame-priceable (not `PREGAME`, or already started) blocks the whole assessment.
- **Settlement** (`settle_combo`): any lost leg → `LOST`. Otherwise any unresolved leg (including postponed) → `UNRESOLVED`, never assumed void. A void leg with no confirmed `VoidPolicy` → `RULE_UNKNOWN`.
- **Correlation** (`correlation.py`): pairwise detection of `SHARED_GAME`, `SAME_MARKET` (nested or mutually exclusive), `SHARED_TEAM`, `SHARED_PLAYER`, `SHARED_WEATHER` (same game only), and `GAME_SCRIPT`. A leg with no event id or participant pair gets `UNKNOWN_DEPENDENCY`. Magnitude is always `UNQUANTIFIED`.
- **SportAdapter** (`services/sports/auspex_sports/adapter.py`): a Protocol with `sport`, `coverage`, `validate_coverage`, `estimate_leg`, and `settlement_requirements`. Each sport is a data-only `CoverageBoundary` run by one `CoverageBoundedAdapter`. `estimate_leg` returns `InsufficientData` even for covered legs, because no model is registered. `normalize_market`, `collect_features`, and `simulate_combo` from the prompt.md sketch are deferred until their inputs exist.
- **Coverage requirements:** pregame status, a future start, a supported league/market/side/line, a `settlement_rule_ref`, and a feature snapshot where every required feature is present, non-null, and fresh.
  - **NFL** (league `NFL`): moneyline, spread, and total in 0.5 steps; features must be ≤12h old.
  - **MLB** (league `MLB`): moneyline, ±1.5 run line, and total in 0.5 steps. Confirmed starters and lineups are required, and features must be ≤6h old.
  - Player props and partial-game markets are excluded for both.

### Model-readiness layer

- **Feature gates** (`adapter.py`): `FeatureSpec` (TEXT non-empty, or DECIMAL with bounds) per `CoverageBoundary.feature_specs`; every required feature must also carry a `source_ref`. MLB `park_factor` is a Decimal ratio in [0.5, 1.5]; all other features are non-empty text. Bounds are a sanity gate, not a domain claim.
- **Registry** (`registry.py`): `ModelMetadata` (version, code version, sport/leagues/markets coverage, model-specific max interval width, `TrainingProvenance`, `ModelStatus`, `EvaluationArtifact`). `ACTIVE` is only constructible with an artifact matching model and code version that beats its baseline on an adequate sample. Versions are immutable; one ACTIVE model per league/market. Metadata only: predictor code is bound separately in `EstimationContext`.
- **Orchestration** (`services/sports/.../estimator.py`, `estimate_leg`): coverage gate, ACTIVE model lookup, predictor bound, interval validation, abstention on width (model limit and global limit), then `LegEstimate` carrying model id/version, code version, evaluation artifact id, snapshot time, `as_of_utc`, and both confidence tiers. No registered model exists, so every real leg is still `INSUFFICIENT_DATA`. `CoverageBoundedAdapter.estimate_leg` is unchanged and still always abstains.
- **Two confidences** (`uncertainty.py`): evidence confidence (freshness fraction and distinct sources) is independent of prediction confidence (interval width, capped at LOW without an adequate validated sample).
- **Malformed model output** (interval with point outside [low, high], out of [0, 1], float) raises `ValueError`; a valid but too-wide interval abstains.
- **Policy** (`policy.py`): precedence INSUFFICIENT_DATA (no estimate, no or future market time, unknown dependency), AVOID (stale market, `SAME_MARKET`, point edge ≤ -0.05), PASS (any other correlation warning, since magnitude is unquantified; conservative edge < 0.02; confidence below minimums), else CONSIDER. Conservative edge = interval low bound − break-even. Boundaries are inclusive.
- **Evaluation** (`evaluation.py`): Brier, log loss (probabilities clipped to [1e-15, 1−1e-15]; `Decimal.ln`), ROI, calibration bins (bins under 30 samples suppress the observed frequency), sample-size warnings (default minimum 300), baseline comparison (`beats_baseline = None` under the minimum), and `EvaluationArtifact`. No artifact exists, so no model can be active or called calibrated.

## Contracts consumed or produced

- **Consumed:** `auspex_contracts.BetLeg`, `LegStatus`, `MarketType`, `Side`, `Sport`, `Recommendation`. Shared contracts are unchanged.
- **Produced** (internal Python only, not yet in OpenAPI): `InsufficientData`, `PositionCosts`, `ExpectedValue`, `DevigResult`, `BookQuote`, `ConsensusResult`, `NaiveIndependentBaseline`, `ComboAssessment`, `CorrelationWarning`, `LegResult`, `VoidPolicy`, `ComboSettlement`, `SportAdapter`, `CoverageBoundary`, `MarketRule`, `CoverageResult`, `FeatureSnapshot`, `FeatureObservation`, `LegEstimate` (now with provenance and both confidence tiers), plus `ProbabilityInterval`, `ConfidenceTier`, `UncertaintyPolicy`, `ModelMetadata`, `ModelRegistry`, `ModelStatus`, `EvaluationArtifact`, `BaselineComparison`, `CalibrationBin`, `PolicyConfig`, `PolicyDecision`, `EstimationContext`, `Predictor`. Promotion request: `requests/prediction-to-foundation-estimate-contracts.md`.

## Commands and tests

Run on 2026-09-21 (macOS, Python 3.13 via uv):

```bash
PYTHONPATH=services/prediction:services/sports uv run pytest -q services/prediction/tests services/sports/tests
MYPYPATH=services/prediction:services/sports:packages/contracts uv run mypy services/prediction services/sports
uv run ruff check services && uv run ruff format --check services
pnpm check
git diff --check
```

Results:

- pytest: 182 pass.
- mypy `--strict`: clean (25 files).
- ruff: clean.
- `pnpm check`: pass (the existing 14 pytest + 2 Vitest, and no contract drift). Root pytest and mypy do not include `services/**` yet; see the request.

## Known issues

- Root uv workspace, pytest, and mypy config do not include `services/**` yet (foundation request filed), so `pnpm check` does not run these tests.
- The binary-share payout, fee, and void semantics are assumptions until confirmed against Polymarket US rules.
- The contract has no period, prop stat type, or venue/roof fields. MLB full-game scope relies on `settlement_rule_ref`, and weather correlation is only flagged for legs in the same game.
- There is no probability model, evaluation artifact, or correlation-aware joint probability; every leg estimate is `INSUFFICIENT_DATA`.
- Policy, uncertainty, and evaluation thresholds are conservative defaults, not calibrated; they need product sign-off.
- Correlation-aware combo recommendations are not implemented; the policy treats any non-`SAME_MARKET` warning as PASS.
- Participant matching is a normalized string match. It does not resolve entities, so aliases such as "KC" and "Chiefs" won't match.
- Result types are internal dataclasses. Backend needs Pydantic contracts to serialize them.

## Integration order

After foundation and backend; alongside research; before frontend. No migrations, and no generated-type changes.

## Last completed commit

Implementation: `629e244`; model-readiness layer: `d520d86` on `work/prediction`.

## Next smallest task

Add a transparent market-baseline estimator (de-vigged consensus → `LegEstimate` with an explicit interval) behind the NFL moneyline coverage gate.

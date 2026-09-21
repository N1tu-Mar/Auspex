# Workstream: prediction

## Objective

Phase 3 deterministic prediction foundation: typed, unit-tested pricing/EV/de-vig/combo primitives, a transparent correlation-warning framework, and the `SportAdapter` contract with narrow NFL/MLB pregame coverage. No API endpoints, provider retrieval, persistence, UI, or LLM math.

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

## Contracts consumed or produced

- **Consumed:** `auspex_contracts.BetLeg`, `LegStatus`, `MarketType`, `Side`, `Sport`, `Recommendation`. Shared contracts are unchanged.
- **Produced** (internal Python only, not yet in OpenAPI): `InsufficientData`, `PositionCosts`, `ExpectedValue`, `DevigResult`, `BookQuote`, `ConsensusResult`, `NaiveIndependentBaseline`, `ComboAssessment`, `CorrelationWarning`, `LegResult`, `VoidPolicy`, `ComboSettlement`, `SportAdapter`, `CoverageBoundary`, `MarketRule`, `CoverageResult`, `FeatureSnapshot`, `FeatureObservation`, `LegEstimate`.

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

- pytest: 135 pass.
- mypy `--strict`: clean (15 files).
- ruff: clean.
- `pnpm check`: pass (the existing 14 pytest + 2 Vitest, and no contract drift). Root pytest and mypy do not include `services/**` yet; see the request.

## Known issues

- Root uv workspace, pytest, and mypy config do not include `services/**` yet (foundation request filed), so `pnpm check` does not run these tests.
- The binary-share payout, fee, and void semantics are assumptions until confirmed against Polymarket US rules.
- The contract has no period, prop stat type, or venue/roof fields. MLB full-game scope relies on `settlement_rule_ref`, and weather correlation is only flagged for legs in the same game.
- There is no probability model, no correlation-aware joint probability, and no uncertainty interval yet; every leg estimate is `INSUFFICIENT_DATA`.
- Participant matching is a normalized string match. It does not resolve entities, so aliases such as "KC" and "Chiefs" won't match.
- Result types are internal dataclasses. Backend needs Pydantic contracts to serialize them.

## Integration order

After foundation and backend; alongside research; before frontend. No migrations, and no generated-type changes.

## Last completed commit

Implementation: `629e244`. Docs: `cb4a561`, plus the follow-up commit that records these SHAs, on `work/prediction`.

## Next smallest task

After foundation wires `services/**` into root tooling, add a transparent market-baseline estimator (de-vigged consensus → `LegEstimate` with an explicit interval) behind the NFL moneyline coverage gate.

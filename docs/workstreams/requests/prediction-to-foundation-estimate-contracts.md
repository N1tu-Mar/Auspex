# Request: prediction → foundation

**From:** prediction (`work/prediction`)
**To:** foundation (owns `packages/contracts/**`), then backend
**Blocking:** no. Nothing here is served yet; there is no API route.

## Contracts to promote (Pydantic, then OpenAPI and generated types)

Current internal dataclasses in `services/**` that a future recommendation API must serialize:

- `LegEstimate` (`auspex_sports.adapter`): `model_probability`, `probability_low`, `probability_high` (Decimal, 0–1), `model_id`, `model_version`, `code_version`, `evaluation_artifact_id`, `snapshot_captured_at_utc`, `as_of_utc`, `evidence_confidence`, `prediction_confidence`.
- `ConfidenceTier` (`LOW | MEDIUM | HIGH`). Two separate fields on every estimate; the UI must never merge them.
- `PolicyDecision` (`recommendation`, `reasons: list[str]`); `Recommendation` already exists in `bet_slip.py`.
- `InsufficientData` (`status = INSUFFICIENT_DATA`, `reasons`).
- `EvaluationArtifact` summary, only if the UI shows model provenance: `artifact_id`, `model_version`, `code_version`, `dataset_ref`, `sample_size`, Brier/log loss, baseline name, `beats_baseline` (nullable = suppressed), warnings.
- `CalibrationBin` (nullable `observed_frequency` when suppressed) for the calibration plot.

Decimals should serialize as strings, matching existing money/probability fields.

## Assumptions to confirm

- Threshold defaults are conservative policy, not calibrated values: interval width limit 0.30, CONSIDER needs a conservative edge (interval low bound minus break-even) of at least 0.02, AVOID at point edge of -0.05 or worse, market price stale after 15 minutes, minimum evaluation sample 300 (30 per calibration bin). Confirm or override per product decision.
- `BetLeg` still lacks period/scope, player-prop stat type, and venue/roof (see the earlier request).

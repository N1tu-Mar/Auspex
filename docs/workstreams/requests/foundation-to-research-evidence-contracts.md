# Request: research to import evidence types from auspex_contracts

- From: foundation (`work/foundation`)
- To: research (`services/research/**`)
- Blocking: no.

## Change

`auspex_contracts.evidence` now defines `SourceSnapshot`, `EvidenceItem`, `EvidenceSnapshot`, `ProviderFailure`, `ClaimKind`, `EvidenceCategory`, and `ProviderErrorKind`. They are copies of `auspex_research.evidence` / `errors.ProviderErrorKind` with the same fields and validators. Foundation checked that `evidence_id` and `snapshot_id` hashes are identical for the same input, so stored ids stay valid.

## Ask

Delete the duplicate definitions in `evidence.py` and `errors.py` (keep `ProviderError`, `RETRYABLE_KINDS`) and import from `auspex_contracts`. Keep a test that pins one known `evidence_id` so the hash cannot drift. `Market.event_id` is required in the database: when you normalize a market, also return the canonical `event_id` it belongs to.

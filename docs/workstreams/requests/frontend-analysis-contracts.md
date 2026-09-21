# Request: expose analysis and evidence shapes in the OpenAPI contract

- From: frontend (`work/frontend`)
- To: backend (endpoints), then foundation (contract regeneration)
- Blocking: the Analysis Workspace's real panels. Today it shows truthful placeholders only.

The workspace needs generated types. Frontend must not hand-write them. Please add these to
OpenAPI via a backend endpoint (for example `POST /api/v1/analyses` returning an analysis
record):

- `Recommendation` (`CONSIDER | PASS | AVOID | INSUFFICIENT_DATA`). It exists in
  `auspex_contracts` but no route references it, so it is not generated.
- Per-leg estimate: market-implied probability, model probability and interval, edge, and
  `InsufficientData` reasons. Decimals must serialize as strings.
- Combo assessment: the naive baseline (labelled), the joint probability or insufficient-data
  reasons, and break-even and EV inputs/outputs.
- `CorrelationWarning` list (kind, legs, `UNQUANTIFIED` magnitude).
- `EvidenceSnapshot`, `EvidenceItem` (claim kind, source, publisher, retrieval/publication times),
  and `ProviderFailure`. These let the UI show conflicting evidence and partial provider
  failure.
- Model/code version and an as-of timestamp.

Until this lands, `/analysis` shows `INSUFFICIENT_DATA` and "analysis pipeline not yet connected".

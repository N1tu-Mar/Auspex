# Request: schema for persisted intake records

- From: backend (`work/backend`)
- To: foundation (migrations)
- Blocking: intake draft persistence. Intake endpoints currently return results without persisting.

## Why

`bet_slips` (migration `0001`) stores only `original_input` and a valid `slip`. Intake results that
need resolution or are rejected have no valid `BetSlip`, and there is no column for trace ID,
source, or state. Stuffing these into `slip` jsonb would mix shapes in an audit table.

## Proposed table `intake_records` (append-only)

| column | type | notes |
|---|---|---|
| `id` | uuid PK | equals the response `trace_id` |
| `received_at` | timestamptz not null | request time (UTC) |
| `source` | text not null | `manual` or `paste` |
| `state` | text not null | `RESOLVED`, `NEEDS_RESOLUTION`, `REJECTED` |
| `original_input` | text null | verbatim submission |
| `result` | jsonb not null | full `IntakeResult` (legs, issues, candidates) |
| `bet_slip_id` | uuid null FK `bet_slips.id` | set when `RESOLVED` and the slip is stored |
| `supersedes_id` | uuid null FK `intake_records.id` | edit/resubmission chain; no in-place updates |

Index on `received_at`. Backend will add the SQLAlchemy model in `apps/api/app/db.py` to match
whatever foundation lands, then persist from both intake endpoints.

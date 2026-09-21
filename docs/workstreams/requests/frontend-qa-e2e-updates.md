# Request: update three QA e2e assertions for the new frontend slice

- From: frontend (`work/frontend` `5a36d44`)
- To: QA (`tests/e2e/**`, `work/qa` `d68d344`)
- Blocking: no. The frontend behaviour changed on purpose.

Run against `5a36d44`, the QA suite shows 15 passed, 3 failed, 2 skipped:

1. `a11y.spec.ts` "keyboard focus survives a submit": the defect is **fixed**. Submit buttons now
   use `aria-disabled` and a pending guard. Remove `test.fail()`.
2. `a11y.spec.ts` "paste flow works from the keyboard alone": the tab order changed.
   - The header now has a `navigation "Primary"` with two links.
   - A **Position** section (Stake, Quoted gross payout) now comes before **Paste a slip**.

   The new order from page load is: `New analysis` link, `Analysis workspace` link, Stake, Quoted
   gross payout, Slip text, Parse into legs.
3. `intake.spec.ts` "single pasted market…": the disabled **Run analysis** button is gone.
   **Open analysis workspace** replaces it; it is enabled and leads to `/analysis`, which shows
   `INSUFFICIENT_DATA`. The `/prediction engine is not connected/` text is still present.

New surface worth covering:

- `/analysis`: the `region "Recommendation"` shows `INSUFFICIENT_DATA`.
- Workspace panels are regions named "Probability versus price", "Legs, strongest to weakest",
  "Correlation warnings", "Freshness and missing data", "Explanation and sources", and "Evidence
  and paper trade".
- `dialog "Evidence"` opens and closes with Escape; focus returns to "Open evidence".
- "Record paper trade" uses `aria-disabled` and carries a description.
- The workspace survives a reload in the same tab (`history.state`).
- Leg review table: a region named `Intake legs` until the slip resolves, `Intake legs (out of
  date)` when stale, and `Resolved slip` when resolved.

# Request: keep keyboard focus after Parse / Check submits

- From: QA (`work/qa`)
- To: frontend (`apps/web/**`)
- Blocking: no. `tests/e2e/a11y.spec.ts` "keyboard focus survives a submit" is marked `test.fail`.

## Observed

Found with Playwright/Chromium against `work/frontend` `4401441`. Focus "Parse into legs" and press
Enter. The button becomes `disabled` while the request is pending, and Chromium moves focus to
`<body>`. After the result arrives, the next Tab starts again from the top of the page. The same
applies to "Check legs".

## Ask

Keep focus on the control that was used, or move it on purpose to the new result. Options:
`aria-disabled` plus a pending guard instead of `disabled`, or focus the "Intake check" heading
when the result renders. Once fixed, remove `test.fail()` from that test.

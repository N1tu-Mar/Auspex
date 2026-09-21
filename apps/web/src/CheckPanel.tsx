import { useEffect, useRef } from "react";
import { type IntakeIssue, IntakeRequestError, type IntakeResult, type Schemas } from "./api";
import { MARKET_TYPES, SIDES, STATUSES } from "./slipForm";

export type Check = { result: IntakeResult; legUids: string[]; snapshot: string };

type State = Schemas["IntakeState"];

export const STATE_LABEL: Record<State, string> = {
  RESOLVED: "Resolved",
  NEEDS_RESOLUTION: "Needs resolution",
  REJECTED: "Rejected",
};

const HEADLINE: Record<State, [string, string]> = {
  RESOLVED: ["text-ok", "Every leg is identified and pregame. Review it before analysis."],
  NEEDS_RESOLUTION: [
    "text-warn",
    "Some legs are incomplete or ambiguous. Fix the marked fields and check again.",
  ],
  REJECTED: ["text-bad", "At least one leg cannot be analysed as entered. Change or remove it."],
};

export const SOURCE_LABEL: Record<IntakeResult["source"], string> = {
  paste: "From pasted text",
  manual: "Manual entry",
};

/** What the user can do about each intake issue. Keyed by the generated enum: complete by type. */
export const RECOVERY: Record<Schemas["IssueCode"], string> = {
  MALFORMED_INPUT: "Correct the marked value. Prices are USD above 0 and below 1.",
  UNPARSEABLE_LEG:
    "Rewrite it as 'Team ML @ 0.56', 'Team -3.5 @ 0.52', or 'Team A/Team B over 47.5 @ 0.51', or fill the leg in by hand.",
  MISSING_FIELD: "Fill in the marked field, then check legs again.",
  INVALID_SIDE:
    "Pick a side that fits the market: Home or Away for spreads, Over or Under for totals, Draw only for soccer moneylines.",
  UNEXPECTED_LINE: "Clear the line. Moneyline legs have none.",
  EVENT_NOT_IDENTIFIED: "Enter the Polymarket US event ID.",
  EVENT_NOT_FOUND:
    "No live event catalog is connected yet, so events are not matched automatically. Enter sport, league, start, participants, and event ID by hand.",
  AMBIGUOUS_EVENT: "Choose the intended event from the list. Auspex will not pick one for you.",
  SETTLEMENT_UNCONFIRMED: "Enter the settlement rule reference from the market's rules.",
  UNSUPPORTED_STATUS:
    "Only pregame markets can be analysed. If the market has not started, set status to Pregame; otherwise remove the leg.",
  EVENT_STARTED: "The event has started. Remove the leg or correct its start time.",
};

const UNSUPPORTED = new Set(["UNSUPPORTED_STATUS", "EVENT_STARTED"]);

export function CheckPanel({
  check,
  stale,
  pending,
  error,
  onRetry,
}: {
  check: Check | null;
  stale: boolean;
  pending: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  // On narrow screens the panel sits below the legs; bring each new outcome into view.
  useEffect(() => {
    if (check || error) panel.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [check, error]);
  return (
    <aside
      ref={panel}
      aria-labelledby="check-heading"
      className="flex flex-col gap-4 rounded-sm border border-rule bg-panel p-4 lg:sticky lg:top-4"
    >
      <h3 id="check-heading" className="text-sm font-semibold">
        Intake check
      </h3>
      <div role="status" className="empty:hidden text-sm text-muted">
        {pending ? "Checking with the intake service…" : ""}
      </div>
      {error && <Failure error={error} onRetry={onRetry} />}
      {!check && !error && !pending && (
        <p className="text-sm text-muted">
          Nothing checked yet. Paste a slip or add legs, then check them. Analysis starts only after
          every leg resolves.
        </p>
      )}
      {check && <Summary check={check} stale={stale} />}
    </aside>
  );
}

function Failure({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const invalid = error instanceof IntakeRequestError && error.kind === "invalid";
  return (
    <div role="alert" className="rounded-sm border border-bad/40 bg-bad/5 p-3 text-sm">
      <p className="font-semibold text-bad">
        {invalid ? "The intake service could not read this slip" : "Intake service unavailable"}
      </p>
      <p className="mt-1">{error.message}</p>
      {invalid && error.detail && error.detail.issues.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {error.detail.issues.map((issue) => (
            <li key={`${issue.field}-${issue.message}`} className="text-xs">
              <span className="font-mono text-muted">{issue.field ?? "slip"}</span> {issue.message}
            </li>
          ))}
        </ul>
      )}
      {invalid && error.detail && (
        <p className="mt-2 font-mono text-[0.7rem] text-muted">trace {error.detail.trace_id}</p>
      )}
      {!invalid && (
        <div className="mt-2 flex items-center gap-3">
          <span className="text-xs text-muted">Your legs are kept.</span>
          <button type="button" onClick={onRetry} className={quiet}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

function Summary({ check, stale }: { check: Check; stale: boolean }) {
  const { result } = check;
  const [tone, summary] = HEADLINE[result.state];
  const slipIssues = result.issues.filter((i) => i.leg_index == null);
  const unsupported = result.issues.some((i) => UNSUPPORTED.has(i.code));
  const counts = (Object.keys(STATE_LABEL) as State[]).flatMap((state) => {
    const n = result.legs.filter((leg) => leg.state === state).length;
    return n ? [`${n} ${STATE_LABEL[state].toLowerCase()}`] : [];
  });
  const resolvedLegs = result.legs.filter((leg) => leg.state === "RESOLVED").length;
  const partial = resolvedLegs > 0 && resolvedLegs < result.legs.length;
  const codes = [...new Set(result.issues.map((i) => i.code))];

  return (
    <section aria-label="Latest intake result" className="flex flex-col gap-3">
      {stale && (
        <p role="alert" className="rounded-sm border border-warn/40 bg-warn/5 p-2 text-xs">
          <span className="font-semibold text-warn">Out of date.</span> The slip changed after this
          check. Check legs again before relying on it.
        </p>
      )}
      <div className={stale ? "opacity-60" : undefined}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className={`font-mono text-sm font-semibold uppercase tracking-wide ${tone}`}>
            {STATE_LABEL[result.state]}
          </p>
          <Badge>{SOURCE_LABEL[result.source]}</Badge>
        </div>
        <p className="mt-1 text-sm">{summary}</p>
        {counts.length > 0 && (
          <p className="mt-1 font-mono text-xs text-muted">{counts.join(" · ")}</p>
        )}
        {partial && (
          <p className="mt-2 text-sm">
            Partly resolved: {resolvedLegs} of {result.legs.length} legs are ready. The rest need
            attention before the slip can be analysed.
          </p>
        )}
        {unsupported && (
          <p className="mt-2 text-sm text-bad">
            Only pregame markets are supported. Live, started, completed, postponed, and canceled
            markets cannot be analysed yet.
          </p>
        )}
        {slipIssues.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1">
            {slipIssues.map((issue) => (
              <IssueLine key={issue.message} issue={issue} />
            ))}
          </ul>
        )}
        {codes.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-semibold">How to fix</p>
            <ul className="mt-1 flex flex-col gap-1.5">
              {codes.map((code) => (
                <li key={code} className="text-xs">
                  <span className="font-mono text-muted">{code}</span> {RECOVERY[code]}
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="mt-3 border-t border-rule pt-2 font-mono text-[0.7rem] text-muted">
          Checked {utc(result.received_at_utc, true)} · {result.source} · trace {result.trace_id}
        </p>
      </div>
    </section>
  );
}

/** Leg table for the latest check. Named "Resolved slip" only when it is current and resolved. */
export function LegReview({
  check,
  stale,
  onContinue,
}: {
  check: Check;
  stale: boolean;
  onContinue: (result: IntakeResult) => void;
}) {
  const { result } = check;
  const ready = result.state === "RESOLVED" && result.slip && !stale;
  const name = ready ? "Resolved slip" : stale ? "Intake legs (out of date)" : "Intake legs";
  if (result.legs.length === 0) return null;
  return (
    <section
      aria-labelledby="review-heading"
      className={`flex flex-col gap-3 rounded-sm border border-rule bg-panel p-4 ${stale ? "opacity-60" : ""}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="review-heading" className="text-sm font-semibold">
          {name}
        </h3>
        <span className="font-mono text-[0.7rem] text-muted">
          {SOURCE_LABEL[result.source]} · received {utc(result.received_at_utc, true)}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-xs">
          <thead className="text-left text-muted">
            <tr>
              <Th>Event</Th>
              <Th>Market · side</Th>
              <Th right>Line</Th>
              <Th right>Price (USD)</Th>
              <Th>Settlement rule</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {result.legs.map((leg) => (
              <tr key={leg.index} className="border-t border-rule align-top">
                <td className="py-1.5 pr-3">
                  <span className="block">{participants(leg)}</span>
                  <span className="block font-mono text-[0.7rem] text-muted">
                    {leg.league ?? "League not set"} ·{" "}
                    {leg.event_start_utc ? utc(leg.event_start_utc) : "start not set"}
                  </span>
                </td>
                <td className="py-1.5 pr-3">
                  {leg.market_type ? MARKET_TYPES[leg.market_type] : "Market not set"} ·{" "}
                  {leg.side ? SIDES[leg.side] : "side not set"}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{leg.line ?? "—"}</td>
                <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                  {leg.market_price_usd ?? "—"}
                </td>
                <td className="py-1.5 pr-3">
                  {leg.settlement_rule_ref ? (
                    <>
                      Referenced{" "}
                      <span className="font-mono text-[0.7rem] text-muted">
                        {leg.settlement_rule_ref}
                      </span>
                    </>
                  ) : (
                    <span className="text-warn">Unconfirmed</span>
                  )}
                </td>
                <td className="py-1.5">
                  {leg.status ? STATUSES[leg.status] : "Status unknown"} ·{" "}
                  <span className={HEADLINE[leg.state][0]}>{STATE_LABEL[leg.state]}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ready && result.slip && (
        <>
          <table className="w-full max-w-sm text-xs">
            <tbody>
              <tr>
                <th scope="row" className="py-0.5 text-left font-medium text-muted">
                  Stake (USD)
                </th>
                <td className="py-0.5 text-right font-mono tabular-nums">
                  {String(result.slip.stake_usd)}
                </td>
              </tr>
              <tr>
                <th scope="row" className="py-0.5 text-left font-medium text-muted">
                  Quoted gross payout (USD)
                </th>
                <td className="py-0.5 text-right font-mono tabular-nums">
                  {result.slip.gross_payout_usd == null
                    ? "Not quoted"
                    : String(result.slip.gross_payout_usd)}
                </td>
              </tr>
            </tbody>
          </table>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => onContinue(result)}
              className="rounded-sm bg-ink px-3 py-1.5 text-sm font-medium text-panel hover:bg-ink/85"
            >
              Open analysis workspace
            </button>
            <p className="text-xs text-muted">
              The prediction engine is not connected yet, so the workspace reports INSUFFICIENT_DATA
              instead of a probability, edge, or recommendation.
            </p>
          </div>
        </>
      )}
    </section>
  );
}

const quiet = "rounded-sm border border-rule px-2 py-1 text-xs font-medium hover:bg-rule/40";

function Th({ children, right }: { children: string; right?: boolean }) {
  return (
    <th scope="col" className={`py-1 pr-3 font-medium ${right ? "text-right" : ""}`}>
      {children}
    </th>
  );
}

export function Badge({ children }: { children: string }) {
  return (
    <span className="rounded-sm border border-rule px-1.5 py-0.5 font-mono text-[0.65rem] uppercase tracking-wide text-muted">
      {children}
    </span>
  );
}

export function participants(leg: {
  player_id?: string | null;
  home_participant?: string | null;
  away_participant?: string | null;
  raw_text?: string | null;
}): string {
  if (leg.player_id) return leg.player_id;
  if (leg.home_participant && leg.away_participant)
    return `${leg.away_participant} at ${leg.home_participant}`;
  return leg.raw_text ?? "Event not identified";
}

export function IssueLine({ issue }: { issue: IntakeIssue }) {
  return (
    <li className="flex gap-2 text-xs">
      <span className="shrink-0 font-mono text-muted">{issue.code}</span>
      <span>
        <span>{issue.message}</span>
        <span className="block text-muted">{RECOVERY[issue.code]}</span>
      </span>
    </li>
  );
}

/** Deterministic UTC rendering, e.g. "2026-09-21 14:02 UTC". */
export function utc(iso: string, seconds = false): string {
  return `${new Date(iso)
    .toISOString()
    .slice(0, seconds ? 19 : 16)
    .replace("T", " ")} UTC`;
}

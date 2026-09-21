import { type IntakeIssue, IntakeRequestError, type IntakeResult } from "./api";
import { MARKET_TYPES, SIDES } from "./slipForm";

export type Check = { result: IntakeResult; legUids: string[]; snapshot: string };

const HEADLINE = {
  RESOLVED: [
    "Resolved",
    "text-ok",
    "Every leg is identified and pregame. Review it before analysis.",
  ],
  NEEDS_RESOLUTION: [
    "Needs resolution",
    "text-warn",
    "Some legs are incomplete or ambiguous. Fix the marked fields and check again.",
  ],
  REJECTED: [
    "Rejected",
    "text-bad",
    "At least one leg cannot be analysed as entered. Change or remove it.",
  ],
} as const;

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
  return (
    <aside
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
      {check && <Result check={check} stale={stale} />}
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
      {!invalid && (
        <div className="mt-2 flex items-center gap-3">
          <span className="text-xs text-muted">Your legs are kept.</span>
          <button
            type="button"
            onClick={onRetry}
            className="rounded-sm border border-rule px-2 py-1 text-xs font-medium hover:bg-rule/40"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

function Result({ check, stale }: { check: Check; stale: boolean }) {
  const { result } = check;
  const [label, tone, summary] = HEADLINE[result.state];
  const slipIssues = result.issues.filter((i) => i.leg_index == null);
  const unsupported = result.issues.some((i) => UNSUPPORTED.has(i.code));
  const counts = (Object.keys(HEADLINE) as (keyof typeof HEADLINE)[]).flatMap((state) => {
    const n = result.legs.filter((leg) => leg.state === state).length;
    return n ? [`${n} ${HEADLINE[state][0].toLowerCase()}`] : [];
  });

  return (
    <section aria-label="Latest intake result" className="flex flex-col gap-3">
      {stale && (
        <p role="alert" className="rounded-sm border border-warn/40 bg-warn/5 p-2 text-xs">
          <span className="font-semibold text-warn">Out of date.</span> The slip changed after this
          check. Check legs again before relying on it.
        </p>
      )}
      <div className={stale ? "opacity-60" : undefined}>
        <p className={`font-mono text-sm font-semibold uppercase tracking-wide ${tone}`}>{label}</p>
        <p className="mt-1 text-sm">{summary}</p>
        {counts.length > 0 && (
          <p className="mt-1 font-mono text-xs text-muted">{counts.join(" · ")}</p>
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
        <p className="mt-3 border-t border-rule pt-2 font-mono text-[0.7rem] text-muted">
          Checked {utc(result.received_at_utc, true)} · {result.source} · trace {result.trace_id}
        </p>
      </div>
      {result.slip && !stale && <ResolvedSlip slip={result.slip} />}
    </section>
  );
}

function ResolvedSlip({ slip }: { slip: NonNullable<IntakeResult["slip"]> }) {
  return (
    <section
      aria-labelledby="slip-heading"
      className="flex flex-col gap-3 border-t border-rule pt-3"
    >
      <h4 id="slip-heading" className="text-sm font-semibold">
        Resolved slip
      </h4>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted">
            <tr>
              <th scope="col" className="py-1 pr-2 font-medium">
                Leg
              </th>
              <th scope="col" className="py-1 pr-2 font-medium">
                Market
              </th>
              <th scope="col" className="py-1 pr-2 text-right font-medium">
                Line
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Price (USD)
              </th>
            </tr>
          </thead>
          <tbody>
            {slip.legs.map((leg, index) => (
              <tr key={`${leg.event_id}-${index}`} className="border-t border-rule align-top">
                <td className="py-1.5 pr-2">
                  <span className="block">
                    {leg.player_id ?? `${leg.away_participant} at ${leg.home_participant}`}
                  </span>
                  <span className="block font-mono text-[0.7rem] text-muted">
                    {leg.league} · {utc(leg.event_start_utc)}
                  </span>
                </td>
                <td className="py-1.5 pr-2">
                  {MARKET_TYPES[leg.market_type]} · {SIDES[leg.side]}
                </td>
                <td className="py-1.5 pr-2 text-right font-mono tabular-nums">{leg.line ?? "—"}</td>
                <td className="py-1.5 text-right font-mono tabular-nums">
                  {String(leg.market_price_usd)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <table className="w-full text-xs">
        <tbody>
          <tr>
            <th scope="row" className="py-0.5 text-left font-medium text-muted">
              Stake (USD)
            </th>
            <td className="py-0.5 text-right font-mono tabular-nums">{String(slip.stake_usd)}</td>
          </tr>
          <tr>
            <th scope="row" className="py-0.5 text-left font-medium text-muted">
              Quoted gross payout (USD)
            </th>
            <td className="py-0.5 text-right font-mono tabular-nums">
              {slip.gross_payout_usd == null ? "Not quoted" : String(slip.gross_payout_usd)}
            </td>
          </tr>
        </tbody>
      </table>
      <button
        type="button"
        disabled
        aria-describedby="analysis-note"
        className="rounded-sm bg-ink px-3 py-1.5 text-sm font-medium text-panel disabled:opacity-50"
      >
        Run analysis
      </button>
      <p id="analysis-note" className="text-xs text-muted">
        The prediction engine is not connected yet. No probability, edge, or recommendation is shown
        until it is.
      </p>
    </section>
  );
}

export function IssueLine({ issue }: { issue: IntakeIssue }) {
  return (
    <li className="flex gap-2 text-xs">
      <span className="shrink-0 font-mono text-muted">{issue.code}</span>
      <span>{issue.message}</span>
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

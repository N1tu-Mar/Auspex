import { type ReactNode, useRef } from "react";
import type { IntakeResult } from "./api";
import { Badge, participants, SOURCE_LABEL, utc } from "./CheckPanel";
import { MARKET_TYPES, SIDES } from "./slipForm";

// ponytail: fixed threshold for the "prices may be stale" note; move to config if it varies by market.
const STALE_AFTER_MINUTES = 15;

type Resolved = IntakeResult & { slip: NonNullable<IntakeResult["slip"]> };

export function isResolved(value: unknown): value is Resolved {
  const result = value as IntakeResult | null;
  return !!result && result.state === "RESOLVED" && !!result.slip;
}

/**
 * Analysis Workspace shell. Every panel is wired to the resolved slip, but nothing downstream
 * (evidence, prediction, EV, correlation, paper trading) is connected, so each panel says so
 * rather than showing a number.
 */
export function Workspace({
  intake,
  onBack,
  now = new Date(),
}: {
  intake: unknown;
  onBack: () => void;
  now?: Date;
}) {
  if (!isResolved(intake)) {
    return (
      <section aria-labelledby="workspace-heading" className="flex flex-col gap-3">
        <h2 id="workspace-heading" className="text-xl font-semibold">
          Analysis workspace
        </h2>
        <p className="rounded-sm border border-dashed border-rule p-4 text-sm text-muted">
          No resolved slip in this tab. Resolve every leg in New analysis, then open the workspace
          from the resolved slip.
        </p>
        <div>
          <button type="button" onClick={onBack} className={quiet}>
            Go to New analysis
          </button>
        </div>
      </section>
    );
  }

  const { slip } = intake;
  const minutes = Math.floor((now.getTime() - Date.parse(intake.received_at_utc)) / 60_000);
  const age = minutes < 1 ? "under a minute ago" : `${minutes} min ago`;

  return (
    <section aria-labelledby="workspace-heading" className="flex flex-col gap-4">
      <div>
        <button type="button" onClick={onBack} className={quiet}>
          Back to slip
        </button>
      </div>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="workspace-heading" className="text-xl font-semibold">
          Analysis workspace
        </h2>
        <p className="flex flex-wrap items-center gap-2 font-mono text-[0.7rem] text-muted">
          <Badge>{SOURCE_LABEL[intake.source]}</Badge>
          <span>received {utc(intake.received_at_utc, true)}</span>
          <span>trace {intake.trace_id}</span>
        </p>
      </header>

      <section
        aria-labelledby="recommendation-heading"
        className="rounded-sm border border-rule border-l-4 border-l-warn bg-panel p-4"
      >
        <h3 id="recommendation-heading" className="text-xs font-medium text-muted">
          Recommendation
        </h3>
        <p className="mt-1 font-mono text-lg font-semibold tracking-wide text-warn">
          INSUFFICIENT_DATA
        </p>
        <p className="mt-1 text-sm">
          Analysis pipeline not yet connected. No evidence, model probability, or expected value has
          been computed, so no recommendation is made.
        </p>
        <p className="mt-2 text-xs text-muted">
          Estimates, when available, will carry uncertainty. They are never guarantees.
        </p>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Probability versus price">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[26rem] text-xs">
              <thead className="text-left text-muted">
                <tr>
                  <th scope="col" className="py-1 pr-3 font-medium">
                    Leg
                  </th>
                  <th scope="col" className="py-1 pr-3 text-right font-medium">
                    Market price (USD)
                  </th>
                  <th scope="col" className="py-1 pr-3 text-right font-medium">
                    Model probability
                  </th>
                  <th scope="col" className="py-1 text-right font-medium">
                    Edge
                  </th>
                </tr>
              </thead>
              <tbody>
                {slip.legs.map((leg, index) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: read-only rows, never reordered.
                  <tr key={index} className="border-t border-rule">
                    <td className="py-1.5 pr-3">
                      {index + 1}. {participants(leg)}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                      {String(leg.market_price_usd)}
                    </td>
                    <td className="py-1.5 pr-3 text-right text-muted">Not estimated</td>
                    <td className="py-1.5 text-right text-muted">Not estimated</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Note>
            Market price is the quote entered at intake. Model probability, break-even, and edge
            need the prediction service.
          </Note>
        </Panel>

        <Panel title="Legs, strongest to weakest">
          <ol className="flex flex-col gap-1 text-sm">
            {slip.legs.map((leg, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: read-only rows, never reordered.
              <li key={index} className="flex flex-wrap gap-x-2">
                <span>{participants(leg)}</span>
                <span className="text-muted">
                  {MARKET_TYPES[leg.market_type]} · {SIDES[leg.side]}
                  {leg.line == null ? "" : ` ${leg.line}`}
                </span>
              </li>
            ))}
          </ol>
          <Note>Not ranked. Ranking needs model estimates, so legs are shown in entry order.</Note>
        </Panel>

        <Panel title="Correlation warnings">
          <p className="text-sm">Not checked.</p>
          <Note>
            Shared-game, team, player, weather, and game-script checks run in the prediction
            service, which is not connected.
            {slip.legs.length > 1 &&
              " Until it is, treat the legs' joint probability as unknown, not independent."}
          </Note>
        </Panel>

        <Panel title="Freshness and missing data">
          <ul className="flex flex-col gap-1.5 text-sm">
            <li>
              Prices were entered by you and checked {age} ({utc(intake.received_at_utc)}). They are
              not live quotes.
              {minutes >= STALE_AFTER_MINUTES && (
                <span className="mt-0.5 block text-warn">
                  Older than {STALE_AFTER_MINUTES} minutes. Recheck prices before relying on them.
                </span>
              )}
            </li>
            <li>
              Missing: evidence snapshot, model estimate and uncertainty interval, external
              consensus odds, and settlement rule text (only a reference is recorded).
            </li>
          </ul>
        </Panel>

        <Panel title="Explanation and sources">
          <p className="text-sm">No explanation yet.</p>
          <Note>
            Explanations will cite each source with its publisher and retrieval time once evidence
            collection is connected. Nothing is shown rather than unsourced claims.
          </Note>
        </Panel>

        <Panel title="Evidence and paper trade">
          <EvidenceDrawer />
          <div className="flex flex-col gap-1">
            <button
              type="button"
              aria-disabled="true"
              aria-describedby="paper-trade-reason"
              className="self-start cursor-not-allowed rounded-sm bg-ink px-3 py-1.5 text-sm font-medium text-panel opacity-50"
            >
              Record paper trade
            </button>
            <p id="paper-trade-reason" className="text-xs text-muted">
              Unavailable: a paper trade records the model estimate and evidence behind it, and
              neither exists for this slip yet.
            </p>
          </div>
        </Panel>
      </div>
    </section>
  );
}

function EvidenceDrawer() {
  const dialog = useRef<HTMLDialogElement>(null);
  return (
    <>
      <button
        type="button"
        onClick={() => dialog.current?.showModal?.()}
        className={`${quiet} self-start`}
      >
        Open evidence
      </button>
      <dialog
        ref={dialog}
        aria-labelledby="evidence-heading"
        className="ml-auto mr-0 h-full max-h-none w-full max-w-md bg-panel p-5 text-ink backdrop:bg-ink/30"
      >
        <div className="flex items-baseline justify-between gap-3">
          <h3 id="evidence-heading" className="text-sm font-semibold">
            Evidence
          </h3>
          <button type="button" onClick={() => dialog.current?.close()} className={quiet}>
            Close
          </button>
        </div>
        <p className="mt-4 text-sm">No evidence collected for this slip.</p>
        <p className="mt-2 text-xs text-muted">
          The research pipeline is not connected. When it is, each item will show its source,
          publisher, retrieval time, and whether it is confirmed, projected, rumor, or opinion.
          Conflicting reports and failed sources will be listed, not dropped.
        </p>
      </dialog>
    </>
  );
}

const quiet = "rounded-sm border border-rule px-2 py-1 text-xs font-medium hover:bg-rule/40";

function Panel({ title, children }: { title: string; children: ReactNode }) {
  const id = `panel-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section
      aria-labelledby={id}
      className="flex flex-col gap-3 rounded-sm border border-rule bg-panel p-4"
    >
      <h3 id={id} className="text-sm font-semibold">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted">{children}</p>;
}

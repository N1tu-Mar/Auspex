import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import {
  type AnalysisRecord,
  AnalysisRequestError,
  createAnalysis,
  getAnalysis,
  type IntakeResult,
  type Schemas,
} from "./api";
import { Badge, participants, SOURCE_LABEL, utc } from "./CheckPanel";
import { pct, signed, usd } from "./decimal";
import {
  age,
  allItems,
  ConflictNotice,
  conflicts,
  EvidenceDrawer,
  ProviderProblems,
  quiet,
} from "./Evidence";

// ponytail: fixed threshold for the "may be stale" note; move to config if it varies by market.
const STALE_AFTER_MINUTES = 15;
const USD_PATTERN = /^\d+(\.\d{1,2})?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Resolved = IntakeResult & { slip: NonNullable<IntakeResult["slip"]> };

export function isResolved(value: unknown): value is Resolved {
  const result = value as IntakeResult | null;
  return !!result && result.state === "RESOLVED" && !!result.slip;
}

/**
 * Analysis Workspace. Runs the analysis API for a resolved, saved slip, or reloads a saved
 * analysis by id. Everything shown comes from the returned record; missing data stays missing.
 */
export function Workspace({
  intake,
  analysisId,
  onBack,
  onOpen,
  now = new Date(),
}: {
  intake: unknown;
  analysisId?: string;
  onBack: () => void;
  onOpen: (id: string) => void;
  now?: Date;
}) {
  const resolved = isResolved(intake) ? intake : undefined;
  const client = useQueryClient();
  const saved = useQuery({
    queryKey: ["analysis", analysisId],
    queryFn: () => getAnalysis(analysisId as string),
    enabled: !!analysisId,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY, // stored analyses never change
  });
  const run = useMutation({
    mutationFn: createAnalysis,
    onSuccess(record) {
      const id = record.analysis.id;
      if (id) {
        client.setQueryData(["analysis", id], record);
        onOpen(id);
      }
    },
  });

  const record = analysisId ? saved.data : run.data;
  // Leg names come from the slip only when it is the slip this analysis ran on.
  const labels =
    resolved && record && resolved.bet_slip_id === record.analysis.bet_slip_id
      ? resolved.slip.legs.map(participants)
      : undefined;

  return (
    <section aria-labelledby="workspace-heading" className="flex flex-col gap-4">
      <div>
        <button type="button" onClick={onBack} className={quiet}>
          {resolved ? "Back to slip" : "Go to New analysis"}
        </button>
      </div>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="workspace-heading" className="text-xl font-semibold">
          Analysis workspace
        </h2>
        {resolved && (
          <p className="flex flex-wrap items-center gap-2 font-mono text-[0.7rem] text-muted">
            <Badge>{SOURCE_LABEL[resolved.source]}</Badge>
            <span>received {utc(resolved.received_at_utc, true)}</span>
            <span>trace {resolved.trace_id}</span>
          </p>
        )}
      </header>

      {analysisId && saved.isPending && (
        <p role="status" className="text-sm text-muted">
          Loading saved analysis {analysisId}…
        </p>
      )}
      {analysisId && saved.isError && (
        <Failure
          title={
            saved.error instanceof AnalysisRequestError && saved.error.kind === "not_found"
              ? "No saved analysis with that id"
              : "Could not load the saved analysis"
          }
          message={saved.error.message}
          onRetry={
            saved.error instanceof AnalysisRequestError && saved.error.kind === "not_found"
              ? undefined
              : () => saved.refetch()
          }
        />
      )}
      {record && <AnalysisView record={record} labels={labels} now={now} />}
      {!analysisId && !run.data && resolved && <RunForm intake={resolved} run={run} />}
      {!analysisId && !resolved && <OpenSaved onOpen={onOpen} />}
    </section>
  );
}

function RunForm({
  intake,
  run,
}: {
  intake: Resolved;
  run: ReturnType<typeof useMutation<AnalysisRecord, Error, Schemas["AnalysisRequest"]>>;
}) {
  const [fees, setFees] = useState("");
  const [slippage, setSlippage] = useState("");
  const invalid = [fees, slippage].some((v) => v !== "" && !USD_PATTERN.test(v));
  const submit = () => {
    if (run.isPending || invalid || !intake.bet_slip_id) return;
    run.mutate({
      bet_slip_id: intake.bet_slip_id,
      ...(fees && { estimated_fees_usd: fees }),
      ...(slippage && { estimated_slippage_usd: slippage }),
    });
  };
  if (!intake.bet_slip_id)
    return (
      <p className="rounded-sm border border-dashed border-rule p-4 text-sm text-muted">
        This slip was not saved by the intake service, so it cannot be analysed. Check the legs
        again from New analysis.
      </p>
    );
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex flex-col gap-3 rounded-sm border border-rule bg-panel p-4"
    >
      <h3 className="text-sm font-semibold">Run analysis</h3>
      <p className="text-xs text-muted">
        {intake.slip.legs.length} {intake.slip.legs.length === 1 ? "leg" : "legs"} · stake{" "}
        {intake.slip.stake_usd == null ? "not entered" : usd(intake.slip.stake_usd)}
        {intake.slip.gross_payout_usd != null && ` · payout ${usd(intake.slip.gross_payout_usd)}`}.
        Fees and slippage are never assumed: leave them blank and expected value stays unknown.
      </p>
      <div className="flex flex-wrap gap-4">
        <Field label="Estimated fees (USD, optional)" value={fees} onChange={setFees} />
        <Field label="Estimated slippage (USD, optional)" value={slippage} onChange={setSlippage} />
      </div>
      {run.isError && (
        <Failure
          title={
            run.error instanceof AnalysisRequestError && run.error.kind === "unavailable"
              ? "Analysis did not complete"
              : "Analysis refused"
          }
          message={run.error.message}
        />
      )}
      <button
        type="submit"
        aria-disabled={run.isPending || invalid}
        className="self-start rounded-sm bg-ink px-3 py-1.5 text-sm font-medium text-panel aria-disabled:opacity-60"
      >
        {run.isPending
          ? "Analysing… this can take a while"
          : run.isError
            ? "Retry"
            : "Run analysis"}
      </button>
      <p role="status" className="sr-only">
        {run.isPending ? "Analysis running" : ""}
      </p>
    </form>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const bad = value !== "" && !USD_PATTERN.test(value);
  return (
    <label className="flex flex-col gap-1 text-xs font-medium">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        inputMode="decimal"
        aria-invalid={bad}
        className="w-48 rounded-sm border border-rule bg-panel px-2 py-1 font-mono text-sm"
      />
      {bad && <span className="font-normal text-bad">Use dollars and cents, like 0.50.</span>}
    </label>
  );
}

function OpenSaved({ onOpen }: { onOpen: (id: string) => void }) {
  const [id, setId] = useState("");
  const bad = id !== "" && !UUID.test(id.trim());
  return (
    <div className="flex flex-col gap-3">
      <p className="rounded-sm border border-dashed border-rule p-4 text-sm text-muted">
        No resolved slip in this tab. Resolve every leg in New analysis, then open the workspace
        from the resolved slip, or open a saved analysis by its id.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (id && !bad) onOpen(id.trim());
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="flex flex-col gap-1 text-xs font-medium">
          Saved analysis id
          <input
            value={id}
            onChange={(event) => setId(event.target.value)}
            aria-invalid={bad}
            className="w-80 max-w-full rounded-sm border border-rule bg-panel px-2 py-1 font-mono text-sm"
          />
          {bad && <span className="font-normal text-bad">That is not an analysis id.</span>}
        </label>
        <button type="submit" aria-disabled={!id || bad} className={quiet}>
          Open saved analysis
        </button>
      </form>
    </div>
  );
}

function Failure({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="rounded-sm border border-rule border-l-4 border-l-bad p-3 text-sm">
      <p className="font-medium">{title}</p>
      <p className="text-xs">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className={`${quiet} mt-2`}>
          Retry
        </button>
      )}
    </div>
  );
}

const TONE: Record<Schemas["Recommendation"], string> = {
  CONSIDER: "border-l-ok text-ok",
  PASS: "border-l-muted text-ink",
  AVOID: "border-l-bad text-bad",
  INSUFFICIENT_DATA: "border-l-warn text-warn",
};

function AnalysisView({
  record,
  labels,
  now,
}: {
  record: AnalysisRecord;
  labels?: string[];
  now: Date;
}) {
  const { analysis } = record;
  const result = analysis.recommendation;
  const items = allItems(record);
  const groups = conflicts(items);
  const minutes = Math.floor((now.getTime() - Date.parse(analysis.as_of_utc)) / 60_000);
  const snapshotTitle = (id?: string | null) =>
    record.market_snapshots.find((s) => s.id === id)?.title ?? undefined;
  const name = (leg: Schemas["LegAnalysis"]) =>
    labels?.[leg.leg_index] ?? snapshotTitle(leg.market_snapshot_id) ?? "Market not named";
  const [toneBorder, toneText] = (TONE[result.recommendation] ?? "").split(" ");

  return (
    <div className="flex flex-col gap-4">
      <section
        aria-labelledby="recommendation-heading"
        className={`rounded-sm border border-rule border-l-4 bg-panel p-4 ${toneBorder}`}
      >
        <h3 id="recommendation-heading" className="text-xs font-medium text-muted">
          Recommendation
        </h3>
        <p className={`mt-1 font-mono text-lg font-semibold tracking-wide ${toneText}`}>
          {result.recommendation}
        </p>
        <p className="mt-1 text-sm">{result.reason}</p>
        {result.insufficient_data && (
          <ul className="mt-2 list-disc pl-5 text-xs">
            {result.insufficient_data.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted">
          Estimates carry uncertainty. They are never guarantees. As of {utc(analysis.as_of_utc)}.
        </p>
      </section>

      {minutes >= STALE_AFTER_MINUTES && (
        <p
          role="status"
          className="rounded-sm border border-rule border-l-4 border-l-warn p-3 text-sm"
        >
          Stale: this analysis is {age(analysis.as_of_utc, now.toISOString())} old. Prices and
          evidence may have moved. Run a new analysis before relying on it.
        </p>
      )}
      <ProviderProblems failures={record.provider_failures} />
      <ConflictNotice groups={groups} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Probability versus price">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[30rem] text-xs">
              <thead className="text-left text-muted">
                <tr>
                  {["Leg", "Market-implied", "Consensus", "Model (interval)", "Edge"].map(
                    (h, i) => (
                      <th
                        key={h}
                        scope="col"
                        className={`py-1 pr-3 font-medium ${i ? "text-right" : ""}`}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {analysis.legs.map((leg) => (
                  <tr key={leg.leg_index} className="border-t border-rule align-top">
                    <td className="py-1.5 pr-3">
                      {leg.leg_index + 1}. {name(leg)}
                    </td>
                    <Num>{pct(leg.market_implied_probability)}</Num>
                    <Num>
                      {leg.consensus_probability == null ? null : pct(leg.consensus_probability)}
                    </Num>
                    <Num>
                      {leg.estimate
                        ? `${pct(leg.estimate.model_probability)} (${pct(leg.estimate.interval.low)}–${pct(leg.estimate.interval.high)})`
                        : null}
                    </Num>
                    <Num>
                      {leg.edge_probability_points == null
                        ? null
                        : signed(leg.edge_probability_points, " pts")}
                    </Num>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {analysis.legs.some((leg) => leg.insufficient_data) && (
            <ul className="flex flex-col gap-1 text-xs">
              {analysis.legs.map(
                (leg) =>
                  leg.insufficient_data && (
                    <li key={leg.leg_index}>
                      <span className="font-medium">Leg {leg.leg_index + 1}, no estimate: </span>
                      {leg.insufficient_data.reasons.join("; ")}
                    </li>
                  ),
              )}
            </ul>
          )}
          <Note>
            Market-implied is the price read as a probability. “Not available” means the value was
            not computed, not zero.
          </Note>
        </Panel>

        <Panel title="Expected value">
          {analysis.expected_value ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <Row
                label="Model probability"
                value={pct(analysis.expected_value.model_probability)}
              />
              <Row
                label="Break-even probability"
                value={pct(analysis.expected_value.break_even_probability)}
              />
              <Row
                label="Edge"
                value={signed(analysis.expected_value.edge_probability_points, " pts")}
              />
              <Row
                label="Expected profit"
                value={usd(analysis.expected_value.expected_profit_usd)}
              />
              <Row
                label="Expected return"
                value={signed(analysis.expected_value.expected_return_pct, "%")}
              />
              <Row label="Stake" value={usd(analysis.expected_value.costs.stake_usd)} />
              <Row
                label="Gross payout"
                value={usd(analysis.expected_value.costs.gross_payout_usd)}
              />
              <Row label="Fees" value={usd(analysis.expected_value.costs.estimated_fees_usd)} />
              <Row
                label="Slippage"
                value={usd(analysis.expected_value.costs.estimated_slippage_usd)}
              />
            </dl>
          ) : (
            <p className="text-sm">Expected value not computed.</p>
          )}
          <Note>
            Fees and slippage are the amounts you supplied. Break-even can exceed 100%, meaning no
            probability makes the position pay.
          </Note>
        </Panel>

        <Panel title="Combo and correlation">
          {analysis.combo ? (
            <>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <Row
                  label="Naive independent baseline"
                  value={pct(analysis.combo.naive_baseline.probability)}
                />
                <Row
                  label="Joint probability"
                  value={`Not estimated: ${analysis.combo.joint_probability.reasons.join("; ")}`}
                />
              </dl>
              <Note>
                Baseline: {analysis.combo.naive_baseline.assumption}. A comparison only, never a
                recommendation input.
              </Note>
              {analysis.combo.warnings.length ? (
                <ul className="flex flex-col gap-1.5 text-sm">
                  {analysis.combo.warnings.map((warning) => (
                    <li key={`${warning.kind}|${warning.leg_indices.join()}`}>
                      <span className="font-mono text-xs">{warning.kind}</span> · legs{" "}
                      {warning.leg_indices.map((i) => i + 1).join(", ")}: {warning.explanation}{" "}
                      <span className="text-xs text-muted">(size unquantified)</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <Note>
                  No correlation warnings were raised. Absence of a warning is not proof of
                  independence.
                </Note>
              )}
            </>
          ) : (
            <p className="text-sm">Single leg: no combo to assess.</p>
          )}
        </Panel>

        <Panel title="Freshness and versions">
          <ul className="flex flex-col gap-1.5 text-sm">
            <li>
              Data cutoff {utc(analysis.as_of_utc)}; saved {utc(analysis.created_at)}.
            </li>
            <li className="font-mono text-xs">
              model {analysis.model_version} · code {analysis.code_version.slice(0, 12)}
            </li>
            {record.market_snapshots.map((snapshot) => (
              <li key={snapshot.id} className="text-xs">
                {snapshot.title ?? snapshot.market_id} ({snapshot.provider}): quoted{" "}
                {age(snapshot.captured_at, analysis.as_of_utc)} before cutoff
                {snapshot.is_open ? "" : ", market closed"}
                {snapshot.warnings.map((w) => (
                  <span key={w} className="block text-warn">
                    {w}
                  </span>
                ))}
              </li>
            ))}
            {record.market_snapshots.length === 0 && (
              <li className="text-xs">No market quote was captured.</li>
            )}
          </ul>
        </Panel>

        <Panel title="Evidence and paper trade">
          <p className="text-sm">
            {items.length
              ? `${items.length} evidence ${items.length === 1 ? "item" : "items"} from ${new Set(items.map((i) => i.source.publisher)).size} publishers.`
              : "No evidence was collected, so nothing here is sourced."}
          </p>
          <EvidenceDrawer record={record} />
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
              Unavailable: the paper-trade endpoint does not exist yet, so nothing can be recorded.
            </p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Num({ children }: { children: ReactNode }) {
  return (
    <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
      {children ?? <span className="font-sans text-muted">Not available</span>}
    </td>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  const id = `panel-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section
      aria-labelledby={id}
      className="flex min-w-0 flex-col gap-3 rounded-sm border border-rule bg-panel p-4"
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

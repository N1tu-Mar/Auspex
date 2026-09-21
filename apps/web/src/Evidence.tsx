import { useRef } from "react";
import type { AnalysisRecord, Schemas } from "./api";
import { Badge, utc } from "./CheckPanel";

type Item = Schemas["EvidenceItem"];
type Failure = Schemas["ProviderFailure"];

const CLAIM: Record<Schemas["ClaimKind"], string> = {
  CONFIRMED_FACT: "Confirmed fact",
  PROJECTION: "Projection",
  RUMOR: "Rumor",
  OPINION: "Opinion",
  INFERENCE: "Inference",
};

// Categories with a single true state at a time: two publishers stating different facts disagree.
// ponytail: heuristic (the contract has no conflict flag); other categories differ by nature.
const SINGLE_STATE = new Set<Schemas["EvidenceCategory"]>(["INJURY", "LINEUP", "WEATHER"]);

export const quiet = "rounded-sm border border-rule px-2 py-1 text-xs font-medium hover:bg-rule/40";

export const allItems = (record: AnalysisRecord): Item[] =>
  record.evidence_snapshots.flatMap((snapshot) => snapshot.items);

/** Groups of evidence that may contradict each other: same event and category, different facts. */
export function conflicts(items: Item[]): Item[][] {
  const groups = new Map<string, Item[]>();
  for (const item of items) {
    if (!SINGLE_STATE.has(item.category)) continue;
    const key = `${item.event_id}|${item.category}`;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.values()].filter((g) => new Set(g.map((i) => i.extracted_fact)).size > 1);
}

/** Failures the backend marks stale carry a "[STALE]" prefix (the contract has no STALE kind yet). */
export const isStale = (failure: Failure) => failure.message.startsWith("[STALE]");

export function age(fromIso: string, toIso: string): string {
  const minutes = Math.max(0, Math.floor((Date.parse(toIso) - Date.parse(fromIso)) / 60_000));
  if (minutes < 1) return "under a minute";
  if (minutes < 120) return `${minutes} min`;
  if (minutes < 2880) return `${Math.floor(minutes / 60)} h`;
  return `${Math.floor(minutes / 1440)} days`;
}

const isWeb = (url: string) => /^https?:\/\//i.test(url);

export function ProviderProblems({ failures }: { failures: Failure[] }) {
  if (!failures.length) return null;
  const stale = failures.filter(isStale).length;
  return (
    <section
      aria-labelledby="problems-heading"
      className="rounded-sm border border-rule border-l-4 border-l-warn bg-panel p-4"
    >
      <h3 id="problems-heading" className="text-sm font-semibold">
        Partial result: {failures.length} source {failures.length === 1 ? "call" : "calls"} failed
      </h3>
      <p className="mt-1 text-xs text-muted">
        The analysis used only the sources that answered. Anything these sources would have added is
        missing, not assumed.
        {stale > 0 && ` ${stale} returned data too old to use (stale).`}
      </p>
      <ul className="mt-2 flex flex-col gap-1.5 text-xs">
        {failures.map((failure) => (
          <li
            key={`${failure.provider}|${failure.occurred_at}|${failure.message}`}
            className="flex flex-wrap gap-x-2"
          >
            <span className="font-mono">{failure.provider}</span>
            <Badge>{isStale(failure) ? "STALE" : failure.kind}</Badge>
            <span>{failure.message.replace(/^\[STALE\]\s*/, "")}</span>
            <span className="text-muted">{utc(failure.occurred_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ConflictNotice({ groups }: { groups: Item[][] }) {
  if (!groups.length) return null;
  return (
    <section
      aria-labelledby="conflict-heading"
      className="rounded-sm border border-rule border-l-4 border-l-bad bg-panel p-4"
    >
      <h3 id="conflict-heading" className="text-sm font-semibold">
        Conflicting evidence: sources disagree
      </h3>
      <p className="mt-1 text-xs text-muted">
        Both sides are kept. Treat the affected legs as uncertain until a source is confirmed.
      </p>
      <ul className="mt-2 flex flex-col gap-2 text-xs">
        {groups.map((group) => (
          <li key={`${group[0]?.event_id}|${group[0]?.category}`}>
            <span className="font-mono">
              {group[0]?.category} · {group[0]?.event_id}
            </span>
            <ul className="ml-4 list-disc">
              {group.map((item) => (
                <li key={item.evidence_id}>
                  {item.extracted_fact}{" "}
                  <span className="text-muted">
                    ({item.source.publisher}, {CLAIM[item.claim_kind].toLowerCase()})
                  </span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function EvidenceDrawer({ record }: { record: AnalysisRecord }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const items = allItems(record);
  const asOf = record.analysis.as_of_utc;
  return (
    <>
      <button
        type="button"
        onClick={() => dialog.current?.showModal?.()}
        className={`${quiet} self-start`}
      >
        Open evidence ({items.length})
      </button>
      <dialog
        ref={dialog}
        aria-labelledby="evidence-heading"
        className="ml-auto mr-0 h-full max-h-none w-full max-w-md overflow-y-auto bg-panel p-5 text-ink backdrop:bg-ink/30"
      >
        <div className="flex items-baseline justify-between gap-3">
          <h3 id="evidence-heading" className="text-sm font-semibold">
            Evidence
          </h3>
          <button type="button" onClick={() => dialog.current?.close()} className={quiet}>
            Close
          </button>
        </div>
        {items.length === 0 ? (
          <p className="mt-4 text-sm">No evidence was collected for this analysis.</p>
        ) : (
          <>
            <p className="mt-2 text-xs text-muted">
              Every item is kept exactly as retrieved. Age is measured to the analysis cutoff, and
              evidence older than the allowed window was excluded before analysis.
            </p>
            <ul className="mt-3 flex flex-col gap-3">
              {items.map((item) => (
                <EvidenceCard key={item.evidence_id} item={item} asOf={asOf} />
              ))}
            </ul>
          </>
        )}
      </dialog>
    </>
  );
}

function EvidenceCard({ item, asOf }: { item: Item; asOf: string }) {
  const { source } = item;
  return (
    <li className="rounded-sm border border-rule p-3 text-xs">
      <p className="flex flex-wrap gap-1.5">
        <Badge>{item.category}</Badge>
        <Badge>{CLAIM[item.claim_kind]}</Badge>
      </p>
      <p className="mt-1.5 text-sm">{item.extracted_fact}</p>
      {item.excerpt && <blockquote className="mt-1 text-muted">“{item.excerpt}”</blockquote>}
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        <dt className="text-muted">Publisher</dt>
        <dd>
          {isWeb(source.url) ? (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
            >
              {source.publisher}
            </a>
          ) : (
            source.publisher
          )}
        </dd>
        <dt className="text-muted">Published</dt>
        <dd>{source.published_at ? utc(source.published_at) : "not stated by the source"}</dd>
        <dt className="text-muted">Retrieved</dt>
        <dd>
          {utc(source.retrieved_at)} · {age(source.retrieved_at, asOf)} before cutoff
        </dd>
        <dt className="text-muted">Provenance</dt>
        <dd className="break-all font-mono">
          {source.provider} · evidence {item.evidence_id.slice(0, 12)}
          {source.content_sha256 && ` · content ${source.content_sha256.slice(0, 12)}`}
        </dd>
        {item.derived_from.length > 0 && (
          <>
            <dt className="text-muted">Derived from</dt>
            <dd className="break-all font-mono">
              {item.derived_from.map((id) => id.slice(0, 12)).join(", ")}
            </dd>
          </>
        )}
      </dl>
    </li>
  );
}

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { FormProvider, useFieldArray, useForm, useFormContext, useWatch } from "react-hook-form";
import {
  type BetSlip,
  type IntakeIssue,
  type IntakeResult,
  intakeManual,
  intakePaste,
  type Schemas,
} from "./api";
import { type Check, CheckPanel, IssueLine, LegReview, utc } from "./CheckPanel";
import {
  emptyLeg,
  fromDraft,
  ISSUE_FIELD,
  type LegValues,
  MARKET_TYPES,
  type ParsedSlip,
  SIDES,
  type SlipValues,
  SPORTS,
  STATUSES,
  slipSchema,
  toBetSlip,
  toLocalInput,
} from "./slipForm";

type Sent<T> = { body: T; snapshot: string; legUids: string[] };

const input =
  "w-full rounded-sm border border-rule bg-white px-2 py-1.5 text-sm text-ink aria-[invalid=true]:border-bad";

export function NewAnalysis({ onContinue }: { onContinue: (result: IntakeResult) => void }) {
  const form = useForm<SlipValues, unknown, ParsedSlip>({
    resolver: zodResolver(slipSchema),
    defaultValues: { text: "", stake_usd: "", gross_payout_usd: "", legs: [] },
  });
  const legs = useFieldArray({ control: form.control, name: "legs", keyName: "key" });
  const values = useWatch({ control: form.control });
  const [check, setCheck] = useState<Check | null>(null);

  const paste = useMutation({
    mutationFn: (body: Schemas["PasteIntakeRequest"]) => intakePaste(body),
    onSuccess: (result) => {
      const drafted = result.legs.map(fromDraft);
      form.reset({ ...form.getValues(), legs: drafted });
      setCheck({
        result,
        legUids: drafted.map((leg) => leg.uid),
        snapshot: JSON.stringify(form.getValues()),
      });
    },
  });
  const manual = useMutation({
    mutationFn: ({ body }: Sent<BetSlip>) => intakeManual(body),
    onSuccess: (result, { snapshot, legUids }) => setCheck({ result, snapshot, legUids }),
  });

  const pending = paste.isPending || manual.isPending;

  async function submitPaste() {
    if (pending) return;
    const ok = await form.trigger(["text", "stake_usd", "gross_payout_usd"]);
    const { text, stake_usd, gross_payout_usd } = form.getValues();
    if (!text.trim()) {
      form.setError("text", { message: "Paste at least one leg, e.g. Chiefs ML @ 0.56." });
      return;
    }
    if (!ok) return;
    manual.reset();
    paste.mutate({
      text,
      stake_usd: stake_usd.trim(),
      gross_payout_usd: gross_payout_usd.trim() || null,
    });
  }

  const submitManual = form.handleSubmit((parsed) => {
    if (pending) return;
    paste.reset();
    manual.mutate({
      body: toBetSlip(parsed),
      snapshot: JSON.stringify(form.getValues()),
      legUids: parsed.legs.map((leg) => leg.uid),
    });
  });

  const stale = check !== null && JSON.stringify(values) !== check.snapshot;
  const legIndexOf = (uid: string) => (check ? check.legUids.indexOf(uid) : -1);
  const error = paste.error ?? manual.error;
  const retry = paste.isError
    ? () => paste.variables && paste.mutate(paste.variables)
    : () => manual.variables && manual.mutate(manual.variables);
  const { errors } = form.formState;

  return (
    <FormProvider {...form}>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-start">
        <form
          onSubmit={submitManual}
          noValidate
          className="flex flex-col gap-6"
          aria-busy={pending}
        >
          <section
            aria-labelledby="position-heading"
            className="rounded-sm border border-rule bg-panel p-4"
          >
            <h3 id="position-heading" className="text-sm font-semibold">
              Position
            </h3>
            <p className="mt-1 text-xs text-muted">
              Used for pasted and manual slips alike. Amounts are kept exactly as typed.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-[10rem_14rem]">
              <SlipField name="stake_usd" label="Stake (USD)" />
              <SlipField name="gross_payout_usd" label="Quoted gross payout (USD, optional)" />
            </div>
          </section>

          <section
            aria-labelledby="paste-heading"
            className="rounded-sm border border-rule bg-panel p-4"
          >
            <h3 id="paste-heading" className="text-sm font-semibold">
              Paste a slip
            </h3>
            <p className="mt-1 text-xs text-muted">
              One leg per line, or separate with ; or +. Formats: <Code>Team ML @ 0.56</Code>{" "}
              <Code>Team -3.5 @ 0.52</Code> <Code>Team A/Team B over 47.5 @ 0.51</Code>. Player
              props: add them as legs below.
            </p>
            <p className="mt-1 text-xs text-warn">
              No live event catalog is connected yet. Pasted legs are parsed, but their events must
              be completed by hand.
            </p>
            <label htmlFor="slip-text" className="sr-only">
              Slip text
            </label>
            <textarea
              id="slip-text"
              rows={4}
              className={`${input} mt-3 font-mono`}
              aria-invalid={errors.text ? true : undefined}
              aria-describedby={errors.text ? "slip-text-error" : undefined}
              {...form.register("text")}
            />
            {errors.text && (
              <p id="slip-text-error" className="mt-1 text-xs text-bad">
                {errors.text.message}
              </p>
            )}
            <div className="mt-3 flex flex-wrap items-center justify-end gap-3">
              {legs.fields.length > 0 && (
                <span className="text-xs text-muted">Replaces the legs below.</span>
              )}
              <button
                type="button"
                onClick={submitPaste}
                aria-disabled={pending || undefined}
                className={button}
              >
                {paste.isPending ? "Parsing…" : "Parse into legs"}
              </button>
            </div>
          </section>

          <section aria-labelledby="legs-heading" className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between">
              <h3 id="legs-heading" className="text-sm font-semibold">
                Legs <span className="font-mono text-muted">({legs.fields.length})</span>
              </h3>
              <button type="button" onClick={() => legs.append(emptyLeg())} className={quiet}>
                Add leg
              </button>
            </div>
            {legs.fields.length === 0 && (
              <p className="rounded-sm border border-dashed border-rule p-4 text-sm text-muted">
                No legs yet. Parse pasted text or add a leg by hand.
              </p>
            )}
            {errors.legs?.root?.message || errors.legs?.message ? (
              <p className="text-xs text-bad">{errors.legs.root?.message ?? errors.legs.message}</p>
            ) : null}
            {legs.fields.map((field, index) => {
              const at = legIndexOf(field.uid);
              return (
                <LegCard
                  key={field.key}
                  index={index}
                  stale={stale}
                  onRemove={() => legs.remove(index)}
                  draft={at >= 0 ? check?.result.legs[at] : undefined}
                  issues={
                    at >= 0 ? (check?.result.issues.filter((i) => i.leg_index === at) ?? []) : []
                  }
                />
              );
            })}
            <div className="flex justify-end">
              <button type="submit" aria-disabled={pending || undefined} className={button}>
                {manual.isPending ? "Checking…" : "Check legs"}
              </button>
            </div>
          </section>
        </form>
        <CheckPanel check={check} stale={stale} pending={pending} error={error} onRetry={retry} />
      </div>
      {check && (
        <div className="mt-6">
          <LegReview check={check} stale={stale} onContinue={onContinue} />
        </div>
      )}
    </FormProvider>
  );
}

const button =
  "rounded-sm bg-ink px-3 py-1.5 text-sm font-medium text-panel hover:bg-ink/85 aria-disabled:cursor-not-allowed aria-disabled:opacity-50";
const quiet = "rounded-sm border border-rule px-2 py-1 text-xs font-medium hover:bg-rule/40";

function Code({ children }: { children: string }) {
  return <code className="rounded-sm bg-rule/50 px-1 font-mono text-[0.7rem]">{children}</code>;
}

function SlipField({ name, label }: { name: "stake_usd" | "gross_payout_usd"; label: string }) {
  const { register, formState } = useFormContext<SlipValues>();
  const id = useId();
  const message = formState.errors[name]?.message;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted">
        {label}
      </label>
      <input
        id={id}
        inputMode="decimal"
        className={`${input} font-mono tabular-nums`}
        aria-invalid={message ? true : undefined}
        aria-describedby={message ? `${id}-msg` : undefined}
        {...register(name)}
      />
      {message && (
        <p id={`${id}-msg`} className="text-xs text-bad">
          {message}
        </p>
      )}
    </div>
  );
}

const STATE_STYLE: Record<Schemas["IntakeState"] | "UNCHECKED", [string, string]> = {
  RESOLVED: ["Resolved", "border-l-ok"],
  NEEDS_RESOLUTION: ["Needs resolution", "border-l-warn"],
  REJECTED: ["Rejected", "border-l-bad"],
  UNCHECKED: ["Not checked", "border-l-rule"],
};

type FieldName = Exclude<keyof LegValues, "uid" | "raw_text">;

function LegCard({
  index,
  draft,
  issues,
  stale,
  onRemove,
}: {
  index: number;
  stale: boolean;
  draft: Schemas["LegDraft"] | undefined;
  issues: IntakeIssue[];
  onRemove: () => void;
}) {
  const { getValues } = useFormContext<SlipValues>();
  const [stateLabel, rail] = STATE_STYLE[draft?.state ?? "UNCHECKED"];
  const rawText = getValues(`legs.${index}.raw_text`);
  const onField = (issue: IntakeIssue) => {
    const name = ISSUE_FIELD[issue.field ?? ""] ?? issue.field;
    return name !== null && name !== undefined && name in FIELD_LABELS;
  };
  const leg = index + 1;
  return (
    <fieldset className={`rounded-sm border border-rule border-l-4 bg-panel p-4 ${rail}`}>
      <legend className="sr-only">Leg {leg}</legend>
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-semibold" aria-hidden="true">
          Leg {leg}
        </span>
        <span className="font-mono text-xs uppercase tracking-wide text-muted">
          {stale && draft ? `${stateLabel} before edits` : stateLabel}
        </span>
        {rawText ? (
          <span className="truncate font-mono text-xs text-muted" title={rawText}>
            Pasted: {rawText}
          </span>
        ) : (
          <span className="font-mono text-xs text-muted">Entered by hand</span>
        )}
        <button
          type="button"
          onClick={onRemove}
          className={`${quiet} ml-auto`}
          aria-label={`Remove leg ${leg}`}
        >
          Remove
        </button>
      </div>
      {issues.some((i) => !onField(i)) && (
        <ul className="mb-3 flex flex-col gap-1" aria-label={`Leg ${leg} issues`}>
          {issues
            .filter((i) => !onField(i))
            .map((issue) => (
              <IssueLine key={`${issue.code}-${issue.field}`} issue={issue} />
            ))}
        </ul>
      )}
      {draft?.candidates && draft.candidates.length > 0 && (
        <Candidates index={index} candidates={draft.candidates} />
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(Object.keys(FIELD_LABELS) as FieldName[]).map((name) => (
          <LegField key={name} index={index} name={name} issues={issues} />
        ))}
      </div>
    </fieldset>
  );
}

const FIELD_LABELS: Record<FieldName, [string, Record<string, string>?]> = {
  sport: ["Sport", SPORTS],
  league: ["League"],
  event_start_local: ["Event start (local time)"],
  status: ["Market status", STATUSES],
  home_participant: ["Home"],
  away_participant: ["Away"],
  event_id: ["Event ID"],
  player_id: ["Player ID (props)"],
  market_type: ["Market type", MARKET_TYPES],
  side: ["Side", SIDES],
  line: ["Line"],
  market_price_usd: ["Price (USD)"],
  polymarket_market_id: ["Polymarket market ID"],
  settlement_rule_ref: ["Settlement rule reference"],
};

const NUMERIC = new Set<FieldName>(["line", "market_price_usd"]);

function LegField({
  index,
  name,
  issues,
}: {
  index: number;
  name: FieldName;
  issues: IntakeIssue[];
}) {
  const { register, formState } = useFormContext<SlipValues>();
  const id = useId();
  const [label, options] = FIELD_LABELS[name];
  const messages = [
    formState.errors.legs?.[index]?.[name]?.message,
    ...issues
      .filter((i) => (ISSUE_FIELD[i.field ?? ""] ?? i.field) === name)
      .map((i) => `${i.message} (${i.code})`),
  ].filter(Boolean);
  const props = {
    id,
    className: `${input} ${NUMERIC.has(name) ? "font-mono tabular-nums" : ""}`,
    "aria-invalid": messages.length > 0 ? true : undefined,
    "aria-describedby": messages.length > 0 ? `${id}-msg` : undefined,
    ...register(`legs.${index}.${name}`),
  };
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted">
        {label}
      </label>
      {options ? (
        <select {...props}>
          <option value="">Not set</option>
          {Object.entries(options).map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
      ) : (
        <input
          {...props}
          type={name === "event_start_local" ? "datetime-local" : "text"}
          inputMode={NUMERIC.has(name) ? "decimal" : undefined}
        />
      )}
      {messages.length > 0 && (
        <p id={`${id}-msg`} className="text-xs text-bad">
          {messages.join(" ")}
        </p>
      )}
    </div>
  );
}

function Candidates({
  index,
  candidates,
}: {
  index: number;
  candidates: Schemas["EventCandidate"][];
}) {
  const { setValue } = useFormContext<SlipValues>();
  const choose = (c: Schemas["EventCandidate"]) => {
    const set = (name: FieldName, value: string) =>
      setValue(`legs.${index}.${name}`, value, { shouldDirty: true });
    set("event_id", c.event_id);
    set("sport", c.sport);
    set("league", c.league);
    set("event_start_local", toLocalInput(c.event_start_utc));
    set("home_participant", c.home_participant);
    set("away_participant", c.away_participant);
  };
  return (
    <fieldset className="mb-3 rounded-sm border border-warn/40 bg-warn/5 p-3">
      <legend className="px-1 text-xs font-semibold text-warn">
        {candidates.length} events match. Choose one; nothing is picked for you.
      </legend>
      <div className="flex flex-col gap-1">
        {candidates.map((c) => (
          <label key={c.event_id} className="flex items-baseline gap-2 text-sm">
            <input type="radio" name={`candidate-${index}`} onChange={() => choose(c)} />
            <span>
              {c.away_participant} at {c.home_participant}
            </span>
            <span className="font-mono text-xs text-muted">
              {c.league} · {utc(c.event_start_utc)} · {c.event_id}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

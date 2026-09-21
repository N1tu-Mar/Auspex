import { z } from "zod";
import type { BetSlip, LegDraft, Schemas } from "./api";

// Records keyed by the generated enum types: the compiler fails if the contract adds a value.
export const SPORTS: Record<Schemas["Sport"], string> = {
  NFL: "NFL",
  NCAAF: "College football",
  MLB: "MLB",
  SOCCER: "Soccer",
};
export const MARKET_TYPES: Record<Schemas["MarketType"], string> = {
  MONEYLINE: "Moneyline",
  SPREAD: "Spread",
  TOTAL: "Total",
  PLAYER_PROP: "Player prop",
};
export const SIDES: Record<Schemas["Side"], string> = {
  HOME: "Home",
  AWAY: "Away",
  DRAW: "Draw",
  OVER: "Over",
  UNDER: "Under",
  YES: "Yes",
  NO: "No",
};
export const STATUSES: Record<Schemas["LegStatus"], string> = {
  PREGAME: "Pregame",
  LIVE: "Live",
  COMPLETED: "Completed",
  POSTPONED: "Postponed",
  CANCELED: "Canceled",
  UNSUPPORTED: "Unsupported",
};

const oneOf = <T extends string>(labels: Record<T, string>, message: string) =>
  z.string().pipe(z.enum(Object.keys(labels) as [T, ...T[]], { error: message }));

const text = z.string().trim();
const usd = (message: string, optional = false) =>
  text.refine(
    (v) => (optional && v === "") || (/^\d+(\.\d{1,2})?$/.test(v) && Number(v) > 0),
    message,
  );

// Only shape and bounds are checked here; pregame and resolution rules belong to the API.
const legSchema = z.object({
  uid: z.string(),
  raw_text: z.string(),
  sport: oneOf(SPORTS, "Choose a sport."),
  league: text.min(1, "League is required."),
  event_id: text,
  event_start_local: z
    .string()
    .refine((v) => !Number.isNaN(Date.parse(v)), "Enter the start time."),
  home_participant: text,
  away_participant: text,
  player_id: text,
  market_type: oneOf(MARKET_TYPES, "Choose a market type."),
  side: oneOf(SIDES, "Choose a side."),
  line: text.refine((v) => v === "" || /^[+-]?\d+(\.\d+)?$/.test(v), "Line must be a number."),
  market_price_usd: text.refine(
    (v) => /^0?\.\d{1,4}$/.test(v) && Number(v) > 0,
    "Price must be above 0 and below 1 USD, with up to 4 decimals.",
  ),
  polymarket_market_id: text,
  settlement_rule_ref: text,
  status: oneOf(STATUSES, "Choose a status."),
});

export const slipSchema = z.object({
  text: z.string().max(2000, "Pasted text is limited to 2,000 characters."),
  stake_usd: usd("Stake must be a positive USD amount, e.g. 25 or 25.50."),
  gross_payout_usd: usd("Payout must be a positive USD amount or left blank.", true),
  legs: z.array(legSchema).min(1, "Add at least one leg."),
});

export type SlipValues = z.input<typeof slipSchema>;
export type LegValues = SlipValues["legs"][number];
export type ParsedSlip = z.output<typeof slipSchema>;

/** Backend issue fields that map onto a form input. */
export const ISSUE_FIELD: Record<string, keyof LegValues> = {
  event_start_utc: "event_start_local",
};

const blank = (v: string) => v || null;

export function toBetSlip(values: ParsedSlip): BetSlip {
  return {
    original_input: blank(values.text.trim()),
    stake_usd: values.stake_usd,
    gross_payout_usd: blank(values.gross_payout_usd),
    legs: values.legs.map((leg) => ({
      sport: leg.sport,
      league: leg.league,
      event_id: blank(leg.event_id),
      event_start_utc: new Date(leg.event_start_local).toISOString(),
      home_participant: blank(leg.home_participant),
      away_participant: blank(leg.away_participant),
      player_id: blank(leg.player_id),
      market_type: leg.market_type,
      side: leg.side,
      line: blank(leg.line),
      polymarket_market_id: blank(leg.polymarket_market_id),
      market_price_usd: leg.market_price_usd,
      settlement_rule_ref: blank(leg.settlement_rule_ref),
      status: leg.status,
    })),
  };
}

/** UTC ISO timestamp to the browser-local value a datetime-local input expects. */
export function toLocalInput(iso: string): string {
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function emptyLeg(): LegValues {
  return {
    uid: crypto.randomUUID(),
    raw_text: "",
    sport: "",
    league: "",
    event_id: "",
    event_start_local: "",
    home_participant: "",
    away_participant: "",
    player_id: "",
    market_type: "",
    side: "",
    line: "",
    market_price_usd: "",
    polymarket_market_id: "",
    settlement_rule_ref: "",
    status: "PREGAME",
  };
}

/** Editable leg from an intake draft. Unknown values stay blank; nothing is filled in by guess. */
export function fromDraft(draft: LegDraft): LegValues {
  const s = (v: string | number | null | undefined) => (v == null ? "" : String(v));
  return {
    ...emptyLeg(),
    raw_text: s(draft.raw_text),
    sport: s(draft.sport),
    league: s(draft.league),
    event_id: s(draft.event_id),
    event_start_local: draft.event_start_utc ? toLocalInput(draft.event_start_utc) : "",
    home_participant: s(draft.home_participant),
    away_participant: s(draft.away_participant),
    player_id: s(draft.player_id),
    market_type: s(draft.market_type),
    side: s(draft.side),
    line: s(draft.line),
    market_price_usd: s(draft.market_price_usd),
    polymarket_market_id: s(draft.polymarket_market_id),
    settlement_rule_ref: s(draft.settlement_rule_ref),
    status: draft.status ?? "PREGAME",
  };
}

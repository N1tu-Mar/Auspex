import type { AnalysisRecord, IntakeResult } from "../src/api";

export const ANALYSIS_ID = "7d1c2b3a-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
export const SLIP_ID = "11111111-2222-4333-8444-555555555555";
export const AS_OF = "2026-09-21T14:05:00Z";

export const resolved: IntakeResult = {
  trace_id: "0b6f7c1e-9a55-4c1b-8f8e-2f5a6d7e8c90",
  received_at_utc: "2026-09-21T14:02:11Z",
  source: "paste",
  state: "RESOLVED",
  original_input: "Chiefs ML @ 0.56",
  legs: [],
  issues: [],
  bet_slip_id: SLIP_ID,
  slip: {
    original_input: "Chiefs ML @ 0.56",
    stake_usd: "25",
    gross_payout_usd: "44.64",
    legs: [
      {
        sport: "NFL",
        league: "NFL",
        event_id: "evt-kc-buf",
        event_start_utc: "2026-09-27T20:25:00Z",
        home_participant: "Kansas City Chiefs",
        away_participant: "Buffalo Bills",
        market_type: "MONEYLINE",
        side: "HOME",
        market_price_usd: "0.56",
        settlement_rule_ref: "pm-us:nfl-ml-v1",
        status: "PREGAME",
      },
    ],
  },
};

export const item = (
  id: string,
  fact: string,
  publisher: string,
  claim_kind: "CONFIRMED_FACT" | "RUMOR" = "CONFIRMED_FACT",
) => ({
  evidence_id: id.repeat(64),
  event_id: "evt-kc-buf",
  category: "INJURY" as const,
  claim_kind,
  extracted_fact: fact,
  excerpt: null,
  source: {
    provider: "news-feed",
    publisher,
    url: `https://example.com/${publisher.replace(" ", "-")}`,
    published_at: "2026-09-21T12:00:00Z",
    retrieved_at: "2026-09-21T13:55:00Z",
    content_sha256: "a".repeat(64),
  },
  derived_from: [] as string[],
});

const MARKET_SNAPSHOT_ID = "22222222-2222-4333-8444-555555555555";

// Cast: fixtures fill only the fields the UI reads; server-side defaults are omitted.
/** One-leg analysis with an estimate, EV, and one piece of evidence; no failures. */
export const success = {
  analysis: {
    id: ANALYSIS_ID,
    created_at: "2026-09-21T14:05:01Z",
    as_of_utc: AS_OF,
    bet_slip_id: SLIP_ID,
    intake_record_id: null,
    code_version: "abcdef1234567890",
    model_version: "baseline-v1",
    legs: [
      {
        leg_index: 0,
        market_implied_probability: "0.56",
        consensus_probability: "0.5432",
        estimate: {
          model_probability: "0.6125",
          interval: { low: "0.55", high: "0.67" },
          model_version: "baseline-v1",
          snapshot_captured_at_utc: "2026-09-21T14:00:00Z",
        },
        insufficient_data: null,
        edge_probability_points: "5.25",
        market_snapshot_id: MARKET_SNAPSHOT_ID,
      },
    ],
    combo: null,
    expected_value: {
      costs: {
        stake_usd: "25",
        gross_payout_usd: "44.64",
        estimated_fees_usd: "0.50",
        estimated_slippage_usd: "0",
      },
      model_probability: "0.6125",
      break_even_probability: "0.5711",
      edge_probability_points: "4.14",
      expected_profit_usd: "1.8400",
      expected_return_pct: "7.36",
    },
    recommendation: { recommendation: "CONSIDER", reason: "Edge exceeds the interval width." },
  },
  events: [],
  markets: [],
  market_snapshots: [
    {
      id: MARKET_SNAPSHOT_ID,
      provider: "polymarket-us",
      market_id: "m1",
      captured_at: "2026-09-21T14:03:00Z",
      title: "Chiefs to beat Bills",
      is_open: true,
      sides: [],
      warnings: [],
    },
  ],
  evidence_snapshots: [
    {
      snapshot_id: "s".repeat(64),
      event_id: "evt-kc-buf",
      created_at: "2026-09-21T14:00:00Z",
      items: [item("1", "Starting QB is active.", "ESPN")],
      failures: [],
    },
  ],
  feature_snapshots: [],
  provider_failures: [],
} as unknown as AnalysisRecord;

/** No estimate, no EV, no evidence, no quote: INSUFFICIENT_DATA. */
export const noData = {
  ...success,
  analysis: {
    ...success.analysis,
    legs: [
      {
        leg_index: 0,
        market_implied_probability: "0.56",
        estimate: null,
        insufficient_data: { reasons: ["no features were available for this event"] },
        edge_probability_points: null,
        market_snapshot_id: null,
      },
    ],
    expected_value: null,
    recommendation: {
      recommendation: "INSUFFICIENT_DATA",
      reason: "no features were available for this event",
      insufficient_data: { reasons: ["no features were available for this event"] },
    },
  },
  evidence_snapshots: [],
  market_snapshots: [],
} as unknown as AnalysisRecord;

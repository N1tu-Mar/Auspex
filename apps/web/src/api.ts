import type { components, paths } from "@auspex/contracts";

export type Schemas = components["schemas"];
export type IntakeResult = Schemas["IntakeResult"];
export type IntakeError = Schemas["IntakeError"];
export type IntakeIssue = Schemas["IntakeIssue"];
export type LegDraft = Schemas["LegDraft"];
export type BetSlip = Schemas["BetSlip"];

/** "invalid": the service read the request and refused it. "unavailable": no usable answer. */
export class IntakeRequestError extends Error {
  constructor(
    readonly kind: "invalid" | "unavailable",
    message: string,
    readonly detail?: IntakeError,
  ) {
    super(message);
  }
}

async function post(path: keyof paths, body: unknown): Promise<IntakeResult> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new IntakeRequestError("unavailable", "Could not reach the intake service.");
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.ok && payload) return payload as IntakeResult;
  if (response.status === 422) {
    const detail =
      payload && typeof payload === "object" && "code" in payload
        ? (payload as IntakeError)
        : undefined;
    throw new IntakeRequestError(
      "invalid",
      detail?.message ?? "The intake service could not read this slip.",
      detail,
    );
  }
  throw new IntakeRequestError(
    "unavailable",
    `The intake service answered HTTP ${response.status} without a result.`,
  );
}

export const intakePaste = (body: Schemas["PasteIntakeRequest"]) =>
  post("/api/v1/bet-slips/intake/paste", body);

export const intakeManual = (body: BetSlip) => post("/api/v1/bet-slips/intake/manual", body);

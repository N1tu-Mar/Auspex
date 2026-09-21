// Money and probabilities arrive as decimal strings. Format them with integer (BigInt) maths only;
// never Number/parseFloat/toFixed, which would round through binary floats.
const DECIMAL = /^([+-]?)(\d*)\.?(\d*)$/;

/** Round to `places` after moving the point `shift` places right. Unparseable input is shown as is. */
export function fixed(value: number | string, places: number, shift = 0): string {
  const text = String(value);
  const match = DECIMAL.exec(text);
  if (!match || !(match[2] || match[3])) return text;
  const [, sign, whole = "", frac = ""] = match;
  const scale = frac.length - shift;
  let n = BigInt(whole + frac);
  if (scale > places) {
    const divisor = 10n ** BigInt(scale - places);
    n = (n + divisor / 2n) / divisor;
  } else n *= 10n ** BigInt(places - scale);
  const digits = n.toString().padStart(places + 1, "0");
  const out = places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits;
  return sign === "-" && n !== 0n ? `-${out}` : out;
}

/** A 0–1 probability as a percent, e.g. "0.5432" → "54.3%". */
export const pct = (value: number | string) => `${fixed(value, 1, 2)}%`;

/** A value already in percent or probability points, with an explicit sign. */
export function signed(value: number | string, unit: string) {
  const out = fixed(value, 1);
  return `${out.startsWith("-") || /^0(\.0+)?$/.test(out) ? "" : "+"}${out}${unit}`;
}

export function usd(value: number | string) {
  const out = fixed(value, 2);
  return out.startsWith("-") ? `-$${out.slice(1)}` : `$${out}`;
}

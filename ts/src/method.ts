/**
 * The method behind `oura_compare`, as plain functions over plain numbers.
 *
 * THE TWIN OF `src/oura_mcp/method.py`, and it must agree to the last printed
 * digit: every loop is a plain float loop in the same order as the Python one,
 * rounding is `toFixed` (ties away from zero, which the Python side copies),
 * and the parity test feeds both the same series. The reasoning behind each
 * piece of the method — measured, not assumed — is written once, there.
 */

export const MIN_DAYS = 7;
export const MIN_HISTORY = 60;
export const MIN_PAIRS = 20;       // see method.py
export const HISTORY_DAYS = 120;
const RHO_CEILING = 0.95;

export const DAILY = ["daily_sleep", "daily_readiness", "daily_activity", "daily_stress",
  "daily_spo2", "daily_resilience", "daily_cardiovascular_age", "vO2_max", "sleep"] as const;

export const MAIN_SLEEP_RULE =
  "`sleep` has one record per sleep, naps included. Each day's value is its " +
  "longest `long_sleep`; a day with only naps or rests has no value.";

export const MULTIPLE_COMPARISONS =
  "This is one comparison. Asking many — other metrics, other periods — and " +
  "keeping whichever crosses the band will find a crossing by chance about " +
  "one time in twenty.";

const T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
  2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
  2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042];

export function tCritical(df: number): number {
  const d = Math.max(1, Math.trunc(df));
  if (d <= 30) return T95[d - 1]!;
  if (d <= 40) return 2.021;
  if (d <= 60) return 2.000;
  if (d <= 120) return 1.980;
  return 1.960;
}

export function checkMetric(metric: string): string | undefined {
  if (!metric.includes(".")) {
    return `\`metric\` is \`collection.field\`, like \`daily_readiness.score\` or ` +
           `\`sleep.average_hrv\`; got «${metric}»`;
  }
  const collection = metric.split(".", 1)[0]!;
  if (!(DAILY as readonly string[]).includes(collection)) {
    return `\`${collection}\` does not have one record per day, and a period's ` +
           `mean there is a different question. Comparable: ${DAILY.join(", ")}`;
  }
  return undefined;
}

type Rec = Record<string, unknown>;
export type Day = [string, number];

function get(record: Rec, path: string): unknown {
  let v: unknown = record;
  for (const part of path.split(".")) {
    if (typeof v !== "object" || v === null || Array.isArray(v)) return undefined;
    v = (v as Rec)[part];
  }
  return v;
}

export interface Series {
  values: Day[];
  missing_values: number;
  non_numeric: number;
  without_main_sleep?: number;
}

export function series(records: Rec[], collection: string, field: string): Series {
  let missing = 0, nonNumeric = 0;
  const picked = new Map<string, Rec>();
  const withoutMain = new Set<string>();
  if (collection === "sleep") {
    for (const r of records) {
      const day = r["day"];
      if (typeof day !== "string" || !day) continue;
      if (r["type"] !== "long_sleep") { withoutMain.add(day); continue; }
      const best = picked.get(day);
      if (best === undefined ||
          (Number(r["total_sleep_duration"]) || 0) > (Number(best["total_sleep_duration"]) || 0)) {
        picked.set(day, r);
      }
    }
    for (const d of picked.keys()) withoutMain.delete(d);
  } else {
    for (const r of records) {
      const day = r["day"];
      if (typeof day === "string" && day) picked.set(day, r);
    }
  }

  const values: Day[] = [];
  for (const day of [...picked.keys()].sort()) {
    const v = get(picked.get(day)!, field);
    if (v === undefined || v === null) missing++;
    else if (typeof v !== "number") nonNumeric++;
    else values.push([day, v]);
  }
  const found: Series = { values, missing_values: missing, non_numeric: nonNumeric };
  if (collection === "sleep") found.without_main_sleep = withoutMain.size;
  return found;
}

const ordinal = (day: string) => Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10)) / 86_400_000;

export function consecutivePairs(days: Day[]): [number, number][] {
  const pairs: [number, number][] = [];
  for (let i = 0; i + 1 < days.length; i++) {
    const [d0, v0] = days[i]!, [d1, v1] = days[i + 1]!;
    if (ordinal(d1) - ordinal(d0) === 1) pairs.push([v0, v1]);
  }
  return pairs;
}

function mean(xs: number[]): number {
  let s = 0.0;
  for (const x of xs) s += x;
  return s / xs.length;
}

function variance(xs: number[], m: number): number {
  let s = 0.0;
  for (const x of xs) s += (x - m) * (x - m);
  return s / (xs.length - 1);
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const k = Math.floor(s.length / 2);
  return s.length % 2 ? s[k]! : (s[k - 1]! + s[k]!) / 2;
}

export function lag1(days: Day[]): number {
  const vals = days.map(([, v]) => v);
  if (vals.length < 3) return 0.0;
  const m = mean(vals);
  let den = 0.0;
  for (const v of vals) den += (v - m) * (v - m);
  const pairs = consecutivePairs(days);
  let num = 0.0;
  for (const [a, b] of pairs) num += (a - m) * (b - m);
  if (den === 0.0 || !pairs.length) return 0.0;
  // Each sum over its own count: see method.py.
  return Math.min(Math.max((num / pairs.length) / (den / vals.length), 0.0), RHO_CEILING);
}

const r = (x: number, places = 3) => Number(x.toFixed(places));

function num(x: number): string {
  let s = x.toFixed(3);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s === "-0" || s === "" ? "0" : s;
}

function signed(x: number): string {
  const s = num(x);
  return s.startsWith("-") || s === "0" ? s : "+" + s;
}

export function compareSeries(a: Day[], b: Day[], history: Day[]): Record<string, unknown> {
  const pa: Record<string, unknown> = { n: a.length };
  const pb: Record<string, unknown> = { n: b.length };
  const out: Record<string, unknown> = {};
  out["period_a"] = pa;
  out["period_b"] = pb;
  if (a.length < MIN_DAYS || b.length < MIN_DAYS) {
    out["verdict"] = "cannot_tell";
    out["reading"] =
      `Each period needs at least ${MIN_DAYS} days with a value; these have ` +
      `${a.length} and ${b.length}. Fewer days than that cannot be told apart from ` +
      `an ordinary week.`;
    return out;
  }
  if (history.length < MIN_HISTORY) {
    out["verdict"] = "cannot_tell";
    out["reading"] =
      `How much this metric moves on its own is measured from the ` +
      `${HISTORY_DAYS} days before the first period, and needs at least ` +
      `${MIN_HISTORY} with a value; there are ${history.length}. Without it any ` +
      `band would be a guess, and a guessed band is exactly the signal ` +
      `this tool exists not to invent.`;
    return out;
  }

  const nPairs = consecutivePairs(history).length;
  if (nPairs < MIN_PAIRS) {
    out["verdict"] = "cannot_tell";
    out["reading"] =
      `The history has too few consecutive days with a value — ${nPairs}, ` +
      `and at least ${MIN_PAIRS} are needed — to measure how much one day ` +
      `depends on the day before. Treating that as «no dependence» would ` +
      `narrow the band and call noise a change.`;
    return out;
  }

  const rho = lag1(history);
  const va = a.map(([, v]) => v), vb = b.map(([, v]) => v);
  const ma = mean(va), mb = mean(vb);
  const shrink = (1 - rho) / (1 + rho);
  const na = va.length * shrink, nb = vb.length * shrink;
  const sa = variance(va, ma) / na, sb = variance(vb, mb) / nb;
  const se = Math.sqrt(sa + sb);
  const hv = history.map(([, v]) => v);
  if (se === 0.0 || variance(hv, mean(hv)) === 0.0) {
    // Found on Oura's sandbox, whose score is 80 every day: see method.py.
    out["verdict"] = "cannot_tell";
    out["reading"] =
      "This metric did not vary at all in these days or in the history, so " +
      "there is no noise to measure a difference against. Constant values " +
      "are what sample data and a disconnected ring produce.";
    return out;
  }
  const df = (sa + sb) * (sa + sb) / (sa * sa / Math.max(na - 1, 1e-9) + sb * sb / Math.max(nb - 1, 1e-9));
  const t = tCritical(df);
  const band = t * se;
  const diff = mb - ma;

  const swings = consecutivePairs(history).map(([x, y]) => Math.abs(y - x));
  pa["mean"] = r(ma);
  pb["mean"] = r(mb);
  out["difference"] = r(diff);
  out["noise_band"] = r(band);
  if (Math.abs(diff) > band) {
    out["verdict"] = "outside_noise";
    out["reading"] =
      `The difference (${signed(diff)}) is larger than what this metric does ` +
      `on its own over periods this long (±${num(band)}), at 95% confidence. ` +
      `It says the level differs between the two periods — not why, and not ` +
      `that it will last.`;
  } else {
    out["verdict"] = "within_noise";
    out["reading"] =
      `The difference (${signed(diff)}) is inside what this metric does on ` +
      `its own over periods this long (±${num(band)}). It is not evidence of ` +
      `a change — and with these days, a real change smaller than ` +
      `${num(band)} would be missed more often than seen.`;
  }
  out["typical_daily_change"] = swings.length ? r(median(swings)) : null;
  out["method"] = {
    autocorrelation: r(rho),
    estimated_from_days: history.length,
    effective_days: { a: r(na, 1), b: r(nb, 1) },
    t_critical: t,
    confidence: 0.95,
  };
  out["multiple_comparisons"] = MULTIPLE_COMPARISONS;
  return out;
}

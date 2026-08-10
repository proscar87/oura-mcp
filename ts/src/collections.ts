/**
 * The 19 collections of the Oura v2 API, and nothing else.
 *
 * All the complexity of talking to Oura lives in these tables. The rest — the
 * client, the MCP server — is presentation. That's why this is its own file: if
 * Oura adds a collection, you touch this and nothing else.
 *
 * FOUR PARAMETER SHAPES, not nineteen:
 *
 *     dateRange       start_date / end_date          (most of them)
 *     datetimeRange   start_datetime / end_datetime  (heartrate, battery)
 *     single          no parameters                  (personal_info)
 *     tokenOnly       no parameters, no date         (ring_configuration)
 */

export const BASE = "https://api.ouraring.com/v2/usercollection";

export type Shape = "dateRange" | "datetimeRange" | "single" | "tokenOnly";

export const COLLECTIONS: Record<string, { shape: Shape; carries: string }> = {
  // Daily summaries: what gets queried day to day.
  daily_sleep: { shape: "dateRange", carries: "sleep score and its contributors" },
  daily_readiness: { shape: "dateRange", carries: "readiness score and its contributors" },
  daily_activity: { shape: "dateRange", carries: "steps, calories, time by intensity" },
  daily_stress: { shape: "dateRange", carries: "minutes of stress and recovery" },
  daily_spo2: { shape: "dateRange", carries: "average overnight oxygen saturation" },
  daily_resilience: { shape: "dateRange", carries: "resilience (limited…exceptional)" },
  daily_cardiovascular_age: { shape: "dateRange", carries: "estimated cardiovascular age" },
  vO2_max: { shape: "dateRange", carries: "estimated VO2 max" },

  // The detail the scores hide.
  sleep: { shape: "dateRange", carries: "sleep sessions: stages, HRV, temperature, latency" },
  sleep_time: { shape: "dateRange", carries: "recommended sleep window" },
  workout: { shape: "dateRange", carries: "workouts with type, duration and intensity" },
  session: { shape: "dateRange", carries: "breathing, meditation and nap sessions" },
  rest_mode_period: { shape: "dateRange", carries: "rest mode periods" },
  tag: { shape: "dateRange", carries: "tags (deprecated: Oura recommends enhanced_tag)" },
  enhanced_tag: { shape: "dateRange", carries: "tags with start and end times" },

  // High resolution. The only ones that FORCE pagination.
  heartrate: { shape: "datetimeRange", carries: "heart rate every 5 min" },
  ring_battery_level: { shape: "datetimeRange", carries: "ring battery" },

  // No range.
  personal_info: { shape: "single", carries: "age, weight, height, biological sex" },
  ring_configuration: { shape: "tokenOnly", carries: "ring model, size and color" },
};

export const WITH_DATE: ReadonlySet<Shape> = new Set<Shape>(["dateRange", "datetimeRange"]);

/**
 * The only two that honor `latest=true`. Measured against the API on
 * 2026-08-09: on the others Oura does NOT return an error, it returns the
 * entire collection. Asking for the latest record and getting ten, with no
 * warning, is the same family of failure as not paginating — which is why it's
 * rejected here before going anywhere near the network.
 */
export const WITH_LATEST: ReadonlySet<string> = new Set(["heartrate", "ring_battery_level"]);

/**
 * The ones Oura's sandbox does NOT serve. It's exactly one, and that makes
 * sense: it's the only collection returning email, age, weight and height.
 * Without this, asking for the profile in sandbox mode returned a bare
 * `404: Not Found`, and anyone who had just installed would conclude the server
 * was broken.
 */
export const WITHOUT_SANDBOX: ReadonlySet<string> = new Set(["personal_info"]);

/**
 * Which OAuth scope each collection needs. It serves exactly one purpose, and it
 * matters: when a query comes back EMPTY, telling "there is no data" apart from
 * "you didn't grant that permission". The two look identical — n=0 — and lead to
 * opposite conclusions.
 */
export const SCOPE_OF: Record<string, string> = {
  daily_sleep: "daily", daily_readiness: "daily", daily_activity: "daily",
  daily_stress: "daily", daily_resilience: "daily",
  daily_cardiovascular_age: "daily", vO2_max: "daily",
  sleep: "daily", sleep_time: "daily", rest_mode_period: "daily",
  ring_battery_level: "daily", ring_configuration: "daily",
  daily_spo2: "spo2",
  heartrate: "heartrate",
  workout: "workout",
  session: "session",
  tag: "tag", enhanced_tag: "tag",
  personal_info: "personal",
};

/**
 * The collection's parameter shape. Throws if it doesn't exist — deliberately.
 *
 * A made-up name has to blow up HERE and not turn into a request to a URL that
 * doesn't exist, whose 404 then has to be interpreted.
 */
export function shape(collection: string): Shape {
  const c = COLLECTIONS[collection];
  if (!c) throw new Error(`«${collection}» is not an Oura collection`);
  return c.shape;
}

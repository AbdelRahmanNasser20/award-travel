const BASE_URL = "https://seats.aero/partnerapi/search";

const CABIN_FIELD: Record<string, string> = {
  economy: "YMileageCost",
  premium: "WMileageCost",
  business: "JMileageCost",
  first: "FMileageCost",
};

export interface AwardResult {
  date: string;
  program: string;
  origin: string;
  destination: string;
  miles: number;
  taxes: number | null;
  direct: boolean;
  id: string;
  deal: "great" | "ok" | "over" | "none";
  bookingLink: string;
}

export interface SearchParams {
  origin: string;
  destination: string;
  startDate: string;
  endDate: string;
  cabin: string;
  sources: string;
  maxMiles: number;
  onlyDirect: boolean;
  weekdays?: number[];
}

interface SeatsAeroRaw {
  Source?: string;
  source?: string;
  Date?: string;
  date?: string;
  YMileageCost?: number;
  WMileageCost?: number;
  JMileageCost?: number;
  FMileageCost?: number;
  TotalTaxes?: number;
  Direct?: boolean;
  YDirect?: boolean;
  WDirect?: boolean;
  JDirect?: boolean;
  FDirect?: boolean;
  ID?: string;
  id?: string;
  OriginAirport?: string;
  DestinationAirport?: string;
  Route?: string;
}

async function fetchAll(
  params: Record<string, string>,
  apiKey: string,
): Promise<SeatsAeroRaw[]> {
  const results: SeatsAeroRaw[] = [];
  let cursor: string | null = null;

  while (true) {
    const q = new URLSearchParams(params);
    if (cursor) q.set("cursor", cursor);
    const url = `${BASE_URL}?${q.toString()}`;

    const res = await fetch(url, {
      headers: {
        "Partner-Authorization": apiKey,
        Accept: "application/json",
      },
      signal: AbortSignal.timeout(40_000),
    });

    if (!res.ok) {
      throw new Error(`Seats.aero API error: ${res.status} ${res.statusText}`);
    }

    const payload = await res.json();
    const data: SeatsAeroRaw[] = payload.data ?? (Array.isArray(payload) ? payload : []);
    results.push(...data);
    cursor = typeof payload === "object" && !Array.isArray(payload) ? payload.cursor ?? null : null;
    if (!cursor || data.length === 0) break;
  }

  return results;
}

function weekdayOk(dateStr: string, allowed?: number[]): boolean {
  if (!allowed || allowed.length === 0) return true;
  const d = new Date(dateStr + "T00:00:00");
  return allowed.includes(d.getDay());
}

function bookingLink(id: string, origin: string, dest: string, date: string): string {
  if (id) return `https://seats.aero/search?id=${id}`;
  return `https://www.google.com/travel/flights?q=${encodeURIComponent(`Flights ${origin} to ${dest} on ${date}`)}`;
}

export async function searchAward(params: SearchParams): Promise<AwardResult[]> {
  const apiKey = process.env.SEATS_AERO_API_KEY;
  if (!apiKey) {
    throw new Error("SEATS_AERO_API_KEY environment variable is not set");
  }

  const field = CABIN_FIELD[params.cabin] ?? "YMileageCost";
  const queryParams: Record<string, string> = {
    origin_airport: params.origin,
    destination_airport: params.destination,
    start_date: params.startDate,
    end_date: params.endDate,
    cabin: params.cabin,
    sources: params.sources,
    order_by: "lowest_mileage",
    take: "1000",
  };
  if (params.onlyDirect) {
    queryParams.only_direct_flights = "true";
  }

  const raw = await fetchAll(queryParams, apiKey);

  const rows: AwardResult[] = [];
  for (const r of raw) {
    const miles = Number(r[field as keyof SeatsAeroRaw]) || 0;
    if (miles <= 0) continue;

    const date = ((r.Date ?? r.date) || "").slice(0, 10);
    if (!weekdayOk(date, params.weekdays)) continue;

    const taxes = r.TotalTaxes != null ? Number(r.TotalTaxes) : null;
    const id = r.ID ?? r.id ?? "";
    const origin = r.OriginAirport ?? params.origin.split(",")[0];
    const dest = r.DestinationAirport ?? params.destination.split(",")[0];

    let deal: AwardResult["deal"] = "none";
    if (params.maxMiles > 0) {
      if (miles <= params.maxMiles) deal = "great";
      else if (miles <= params.maxMiles * 1.15) deal = "ok";
      else deal = "over";
    }

    const directField = field.replace("MileageCost", "Direct") as keyof SeatsAeroRaw;
    rows.push({
      date,
      program: r.Source ?? r.source ?? "Unknown",
      origin,
      destination: dest,
      miles,
      taxes,
      direct: !!(r.Direct ?? r[directField]),
      id,
      deal,
      bookingLink: bookingLink(id, origin, dest, date),
    });
  }

  rows.sort((a, b) => a.miles - b.miles || (a.taxes ?? 0) - (b.taxes ?? 0));
  return rows;
}

import { NextRequest, NextResponse } from "next/server";
import { searchAward, type SearchParams } from "@/lib/seats-aero";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;

  const origin = sp.get("origin");
  const destination = sp.get("destination");
  const startDate = sp.get("startDate");
  const endDate = sp.get("endDate");

  if (!origin || !destination || !startDate || !endDate) {
    return NextResponse.json(
      { error: "Missing required parameters: origin, destination, startDate, endDate" },
      { status: 400 },
    );
  }

  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  if (!datePattern.test(startDate) || !datePattern.test(endDate)) {
    return NextResponse.json(
      { error: "Dates must be in YYYY-MM-DD format" },
      { status: 400 },
    );
  }

  const cabin = sp.get("cabin") ?? "economy";
  if (!["economy", "premium", "business", "first"].includes(cabin)) {
    return NextResponse.json({ error: "Invalid cabin class" }, { status: 400 });
  }

  const weekdaysParam = sp.get("weekdays");
  const weekdays = weekdaysParam
    ? weekdaysParam.split(",").map(Number).filter((n) => n >= 0 && n <= 6)
    : undefined;

  const params: SearchParams = {
    origin,
    destination,
    startDate,
    endDate,
    cabin,
    sources: sp.get("sources") ?? "united,delta,american,jetblue,southwest",
    maxMiles: Number(sp.get("maxMiles")) || 0,
    onlyDirect: sp.get("onlyDirect") === "true",
    weekdays,
  };

  try {
    const results = await searchAward(params);
    return NextResponse.json({ results, count: results.length });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Search failed";
    const status = message.includes("not set") ? 503 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}

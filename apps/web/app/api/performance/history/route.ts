import { NextResponse } from "next/server";

const apiBaseUrl = process.env.INVESTMENT_WEB_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  try {
    const response = await fetch(`${apiBaseUrl}/api/performance/history`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return NextResponse.json({ points: [], notes: ["Investment API unavailable."] }, { status: 200 });
    }

    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({ points: [], notes: ["Investment API unavailable."] }, { status: 200 });
  }
}

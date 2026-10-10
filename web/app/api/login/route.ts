// POST /api/login {passcode} → sets the DEMO_PASSCODE cookie. GET → {authed}. DELETE → logs out.
import type { NextRequest } from "next/server";
import { checkDemoToken, demoToken, DEMO_COOKIE } from "@/app/approvals/approvals";
import { reply } from "@/app/approvals/server";

const MAX_AGE_S = 12 * 60 * 60;

export async function GET(req: NextRequest) {
  const authed = await checkDemoToken(req.cookies.get(DEMO_COOKIE)?.value, process.env.DEMO_PASSCODE);
  return reply(200, { authed });
}

export async function POST(req: NextRequest) {
  const passcode = process.env.DEMO_PASSCODE;
  if (!passcode) return reply(503, { error: "DEMO_PASSCODE is not set on this server" });
  let given: unknown;
  try {
    given = ((await req.json()) as { passcode?: unknown })?.passcode;
  } catch {
    return reply(400, { error: "body is not valid JSON" });
  }
  // Compare HMACs, not raw strings, so the check takes the same time whatever was typed.
  if (typeof given !== "string" || !given || !(await checkDemoToken(await demoToken(given), passcode)))
    return reply(401, { error: "wrong passcode" });

  const res = reply(200, { authed: true });
  res.headers.append(
    "set-cookie",
    `${DEMO_COOKIE}=${await demoToken(passcode)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${MAX_AGE_S}` +
      (process.env.NODE_ENV === "production" ? "; Secure" : ""),
  );
  return res;
}

export async function DELETE() {
  const res = reply(200, { authed: false });
  res.headers.append("set-cookie", `${DEMO_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`);
  return res;
}

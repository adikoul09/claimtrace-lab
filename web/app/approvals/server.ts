// Shared guard for the write routes: JSON body, DEMO_PASSCODE cookie, service key configured.
import type { NextRequest } from "next/server";
import type { SupabaseClient } from "@supabase/supabase-js";
import { serviceSupabase } from "@/lib/supabase";
import { checkDemoToken, DEMO_COOKIE } from "./approvals";

export const reply = (status: number, body: Record<string, unknown>) =>
  Response.json(body, { status, headers: { "cache-control": "no-store" } });

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (s: string) => UUID.test(s);

/**
 * Returns the service client and the parsed JSON body, or a Response to send back.
 * Requiring application/json also blocks cross-site HTML form posts (they cannot set it without CORS).
 */
export async function guardWrite(
  req: NextRequest,
): Promise<{ db: SupabaseClient; body: Record<string, unknown> } | Response> {
  if (!req.headers.get("content-type")?.startsWith("application/json"))
    return reply(415, { error: "send JSON (content-type: application/json)" });
  if (!(await checkDemoToken(req.cookies.get(DEMO_COOKIE)?.value, process.env.DEMO_PASSCODE)))
    return reply(401, { error: "log in with the demo passcode first" });
  const db = serviceSupabase();
  if (!db) return reply(503, { error: "writes are not configured on this server (SUPABASE_SERVICE_ROLE_KEY)" });
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return reply(400, { error: "body is not valid JSON" });
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) return reply(400, { error: "body must be an object" });
  return { db, body: body as Record<string, unknown> };
}

export const TASK_FIELDS = "id,project_id,agent_id,capability,status";

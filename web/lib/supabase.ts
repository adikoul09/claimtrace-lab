// Browser Supabase client. Uses only the public anon key: RLS makes it read-only.
// Writes go through server routes with the service key (SPEC §12), never from here.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (client) return client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set");
  }
  client = createClient(url, key, { auth: { persistSession: false } });
  return client;
}

/**
 * Server-only client with the service key, for the write routes (SPEC §12). The key is not NEXT_PUBLIC, so it is
 * never inlined into a browser bundle; calling this in the browser throws. Returns null when it is not configured.
 */
export function serviceSupabase(): SupabaseClient | null {
  if (typeof window !== "undefined") throw new Error("serviceSupabase() is server-only");
  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return createClient(url, key, { auth: { persistSession: false } });
}

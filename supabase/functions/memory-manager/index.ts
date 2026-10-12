// Produktiver Einstiegspunkt. Der Handler kann in Offline-Regressionstests importiert werden.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.117.3";
import { createMemoryHandler, type MemoryDatabase } from "./handler.ts";

const url = Deno.env.get("SUPABASE_URL");
const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
if (!url || !serviceKey) {
  throw new Error("Supabase server configuration missing");
}

Deno.serve(createMemoryHandler({
  database: createClient(url, serviceKey) as unknown as MemoryDatabase,
  env: (name) => Deno.env.get(name),
}));

// Supabase Edge Function: memory-manager
// CRUD operations for persistent memory across Claude sessions
//
// ENDPOINTS:
// GET  /functions/v1/memory-manager?tier=core&project=fabrikiq
// GET  /functions/v1/memory-manager?action=search&q=flutter&project=fabrikiq
// GET  /functions/v1/memory-manager?action=search&q=flutter&semantic=true  (Vector Search)
// GET  /functions/v1/memory-manager?action=backup
// GET  /functions/v1/memory-manager?action=load_session&project=fabrikiq  (Session-Start: loads core + active)
// POST /functions/v1/memory-manager  (create or update entry, auto-generates embedding if OPENAI_API_KEY set)
// POST /functions/v1/memory-manager  { "action": "backfill_embeddings", "tier": "core" }  (Backfill)
// DELETE /functions/v1/memory-manager?tier=active&id=<uuid>
//
// SECURITY: Requires Bearer token.
// Supports client-specific secrets via X-Memory-Client / ?client=
// with legacy fallback to API_SECRET.
//
// VECTOR SEARCH: Optional. Requires OPENAI_API_KEY env var + pgvector extension.
// Without OPENAI_API_KEY, everything works as before (ILIKE search).

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const API_SECRET = Deno.env.get("API_SECRET")?.trim();
const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY")?.trim();

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

const corsHeaders = {
  "Content-Type": "application/json",
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, x-memory-client, x-client-info, apikey, content-type",
};

const CLIENT_SECRET_ENV = {
  cowork: "API_SECRET_COWORK",
  claude_code: "API_SECRET_CLAUDE_CODE",
  openclaw: "API_SECRET_OPENCLAW",
  api: "API_SECRET_API",
  backup: "API_SECRET_BACKUP",
} as const;

type ClientName = keyof typeof CLIENT_SECRET_ENV;
const VALID_CLIENTS = Object.keys(CLIENT_SECRET_ENV) as ClientName[];

// =============================================================================
// Embedding Helper (inline, no separate import needed for Edge Functions)
// =============================================================================

async function generateEmbedding(text: string): Promise<number[] | null> {
  if (!OPENAI_API_KEY) return null;
  if (!text || text.trim().length === 0) return null;

  const truncated = text.slice(0, 32000);

  try {
    const response = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${OPENAI_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "text-embedding-3-small",
        input: truncated,
        dimensions: 1536,
      }),
    });

    if (!response.ok) {
      console.error(`Embedding API error: ${response.status} ${response.statusText}`);
      return null;
    }

    const result = await response.json();
    return result.data?.[0]?.embedding || null;
  } catch (error) {
    console.error("Embedding generation failed:", error);
    return null;
  }
}

// =============================================================================
// Auth (unchanged)
// =============================================================================

function getBearerToken(req: Request): string | null {
  const authHeader = req.headers.get("Authorization");
  if (!authHeader) return null;
  const [scheme, token] = authHeader.split(" ");
  if (scheme?.toLowerCase() !== "bearer" || !token) return null;
  return token.trim();
}

function getConfiguredClientSecrets(): Partial<Record<ClientName, string>> {
  const secrets: Partial<Record<ClientName, string>> = {};
  for (const client of VALID_CLIENTS) {
    const envName = CLIENT_SECRET_ENV[client];
    const value = Deno.env.get(envName)?.trim();
    if (value) secrets[client] = value;
  }
  return secrets;
}

function getRequestedClient(req: Request): { client: ClientName | null; invalid: string | null } {
  const url = new URL(req.url);
  const rawClient = (req.headers.get("X-Memory-Client") || url.searchParams.get("client") || "").trim().toLowerCase();
  if (!rawClient) return { client: null, invalid: null };
  if (!VALID_CLIENTS.includes(rawClient as ClientName)) {
    return { client: null, invalid: rawClient };
  }
  return { client: rawClient as ClientName, invalid: null };
}

function validateApiKey(req: Request): Response | null {
  const token = getBearerToken(req);
  if (!token) {
    return new Response(
      JSON.stringify({ error: "Unauthorized" }),
      { status: 401, headers: corsHeaders }
    );
  }

  const { client, invalid } = getRequestedClient(req);
  if (invalid) {
    return new Response(
      JSON.stringify({
        error: "Invalid client",
        valid_clients: VALID_CLIENTS,
      }),
      { status: 400, headers: corsHeaders }
    );
  }

  const clientSecrets = getConfiguredClientSecrets();
  const allowedTokens = new Set<string>();
  for (const secret of Object.values(clientSecrets)) {
    if (secret) allowedTokens.add(secret);
  }
  if (API_SECRET) allowedTokens.add(API_SECRET);

  if (allowedTokens.size === 0) {
    return new Response(
      JSON.stringify({ error: "Server auth config missing" }),
      { status: 500, headers: corsHeaders }
    );
  }

  if (client) {
    const clientSecret = clientSecrets[client];
    const isAuthorized = clientSecret ? token === clientSecret : !!API_SECRET && token === API_SECRET;
    if (!isAuthorized) {
      return new Response(
        JSON.stringify({ error: "Unauthorized" }),
        { status: 401, headers: corsHeaders }
      );
    }
    return null;
  }

  if (!allowedTokens.has(token)) {
    return new Response(
      JSON.stringify({ error: "Unauthorized" }),
      { status: 401, headers: corsHeaders }
    );
  }
  return null;
}

const VALID_TIERS = ["core", "active", "sessions"] as const;
type Tier = typeof VALID_TIERS[number];

function getTableName(tier: Tier): string {
  return `memory_${tier}`;
}

// =============================================================================
// GET handlers
// =============================================================================

async function handleLoadSession(project?: string) {
  const coreQuery = supabase.from("memory_core").select("*");
  const activeQuery = supabase.from("memory_active").select("*").eq("resolved", false);
  const sessionsQuery = supabase.from("memory_sessions").select("*")
    .order("created_at", { ascending: false }).limit(5);

  if (project) {
    coreQuery.or(`project.eq.${project},project.is.null`);
    activeQuery.or(`project.eq.${project},project.is.null`);
    sessionsQuery.or(`project.eq.${project},project.is.null`);
  }

  const [coreResult, activeResult, sessionsResult] = await Promise.all([
    coreQuery, activeQuery, sessionsQuery
  ]);

  return {
    success: true,
    action: "load_session",
    project: project || "all",
    vector_search_enabled: !!OPENAI_API_KEY,
    core: { count: coreResult.data?.length || 0, data: coreResult.data || [] },
    active: { count: activeResult.data?.length || 0, data: activeResult.data || [] },
    recent_sessions: { count: sessionsResult.data?.length || 0, data: sessionsResult.data || [] },
  };
}

async function handleSearch(query: string, project?: string, semantic?: boolean) {
  // Semantic search: generate embedding for query, then use RPC
  if (semantic && OPENAI_API_KEY) {
    const queryEmbedding = await generateEmbedding(query);
    if (queryEmbedding) {
      const { data, error } = await supabase.rpc("search_memory_semantic", {
        query_embedding: JSON.stringify(queryEmbedding),
        match_threshold: 0.5,
        match_count: 10,
        filter_project: project || null,
      });

      if (error) {
        console.error("Semantic search failed, falling back to ILIKE:", error);
        // Fall through to ILIKE search below
      } else {
        return {
          success: true,
          action: "search",
          search_type: "semantic",
          query,
          project: project || "all",
          count: data?.length || 0,
          results: data || [],
        };
      }
    }
  }

  // ILIKE search (default, or fallback if semantic fails)
  const { data, error } = await supabase.rpc("search_memory", {
    search_term: query,
    filter_project: project || null,
  });

  if (error) throw error;

  return {
    success: true,
    action: "search",
    search_type: "text",
    query,
    project: project || "all",
    count: data?.length || 0,
    results: data || [],
  };
}

async function handleBackup() {
  const [core, active, sessions] = await Promise.all([
    supabase.from("memory_core").select("*"),
    supabase.from("memory_active").select("*"),
    supabase.from("memory_sessions").select("*").order("created_at", { ascending: false }).limit(100),
  ]);

  return {
    success: true,
    action: "backup",
    exported_at: new Date().toISOString(),
    core: { count: core.data?.length || 0, data: core.data || [] },
    active: { count: active.data?.length || 0, data: active.data || [] },
    sessions: { count: sessions.data?.length || 0, data: sessions.data || [] },
  };
}

async function handleGet(tier: Tier, params: URLSearchParams) {
  const table = getTableName(tier);
  let query = supabase.from(table).select("*");

  const project = params.get("project");
  const category = params.get("category");
  const tag = params.get("tag");
  const limit = Math.min(parseInt(params.get("limit") || "50", 10) || 50, 500);

  if (project) query = query.eq("project", project);
  if (category) query = query.eq("category", category);
  if (tag) query = query.contains("tags", [tag]);
  if (tier === "active") {
    const showResolved = params.get("resolved") === "true";
    if (!showResolved) query = query.eq("resolved", false);
  }

  query = query.order("created_at", { ascending: false }).limit(limit);

  const { data, error } = await query;
  if (error) throw error;

  return { success: true, tier, count: data?.length || 0, data: data || [] };
}

// =============================================================================
// POST handler (with optional embedding generation)
// =============================================================================

async function handlePost(body: any) {
  const { tier, action: bodyAction, ...entry } = body;

  // Backfill embeddings action
  if (bodyAction === "backfill_embeddings") {
    if (!OPENAI_API_KEY) {
      return { success: false, error: "OPENAI_API_KEY not configured" };
    }
    if (!tier || !["core", "active"].includes(tier)) {
      return { success: false, error: "Backfill requires tier: core or active" };
    }
    const table = getTableName(tier as Tier);
    const { data: entries, error } = await supabase
      .from(table)
      .select("id, title, content")
      .is("embedding", null)
      .limit(50);

    if (error) throw error;
    if (!entries || entries.length === 0) {
      return { success: true, action: "backfill_embeddings", processed: 0, message: "No entries without embeddings" };
    }

    let processed = 0;
    let errors = 0;
    for (const e of entries) {
      const embedding = await generateEmbedding(`${e.title} ${e.content}`);
      if (embedding) {
        const { error: updateError } = await supabase
          .from(table)
          .update({ embedding })
          .eq("id", e.id);
        if (updateError) errors++;
        else processed++;
      } else {
        errors++;
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    return {
      success: true,
      action: "backfill_embeddings",
      tier,
      processed,
      errors,
      remaining: entries.length - processed,
    };
  }

  if (!tier || !VALID_TIERS.includes(tier)) {
    return { success: false, error: `Invalid tier. Valid: ${VALID_TIERS.join(", ")}` };
  }

  const table = getTableName(tier);

  // Generate embedding for core and active entries (not sessions)
  if (OPENAI_API_KEY && (tier === "core" || tier === "active") && entry.title && entry.content) {
    const embedding = await generateEmbedding(`${entry.title} ${entry.content}`);
    if (embedding) {
      entry.embedding = embedding;
    }
  }

  // Upsert: if id is provided, update; otherwise insert
  if (entry.id) {
    const { data, error } = await supabase
      .from(table)
      .update(entry)
      .eq("id", entry.id)
      .select()
      .single();

    if (error) throw error;
    return {
      success: true,
      action: "updated",
      tier,
      embedding_generated: !!entry.embedding,
      data,
    };
  } else {
    const { data, error } = await supabase
      .from(table)
      .insert(entry)
      .select()
      .single();

    if (error) throw error;
    return {
      success: true,
      action: "created",
      tier,
      embedding_generated: !!entry.embedding,
      data,
    };
  }
}

// =============================================================================
// DELETE handler (unchanged)
// =============================================================================

async function handleDelete(tier: Tier, id: string) {
  const table = getTableName(tier);

  if (tier === "active") {
    const { data, error } = await supabase
      .from(table)
      .update({ resolved: true, resolved_at: new Date().toISOString() })
      .eq("id", id)
      .select()
      .single();

    if (error) throw error;
    return { success: true, action: "resolved", tier, data };
  }

  const { error } = await supabase.from(table).delete().eq("id", id);
  if (error) throw error;
  return { success: true, action: "deleted", tier, id };
}

// =============================================================================
// Main handler
// =============================================================================

serve(async (req) => {
  const requestId = crypto.randomUUID().slice(0, 8);
  const headers = { ...corsHeaders, "X-Request-Id": requestId };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers });
  }

  const authError = validateApiKey(req);
  if (authError) return authError;

  try {
    const url = new URL(req.url);
    let result: any;

    if (req.method === "GET") {
      const action = url.searchParams.get("action");
      const project = url.searchParams.get("project") || undefined;

      if (action === "load_session") {
        result = await handleLoadSession(project);
      } else if (action === "search") {
        const q = url.searchParams.get("q");
        if (!q) return new Response(
          JSON.stringify({ error: "Missing 'q' parameter for search" }),
          { status: 400, headers }
        );
        const semantic = url.searchParams.get("semantic") === "true";
        result = await handleSearch(q, project, semantic);
      } else if (action === "backup") {
        result = await handleBackup();
      } else {
        const tier = url.searchParams.get("tier") as Tier;
        if (!tier || !VALID_TIERS.includes(tier)) {
          return new Response(
            JSON.stringify({
              error: `Missing or invalid 'tier'. Valid: ${VALID_TIERS.join(", ")}`,
              usage: {
                load_session: "GET ?action=load_session&project=fabrikiq",
                search: "GET ?action=search&q=flutter",
                search_semantic: "GET ?action=search&q=wie+loese+ich+OEE+Problem&semantic=true",
                backup: "GET ?action=backup",
                list: "GET ?tier=core&project=fabrikiq&category=pattern",
                backfill: "POST { action: 'backfill_embeddings', tier: 'core' }",
              },
            }),
            { status: 400, headers }
          );
        }
        result = await handleGet(tier, url.searchParams);
      }
    } else if (req.method === "POST") {
      const body = await req.json();
      result = await handlePost(body);
    } else if (req.method === "DELETE") {
      const tier = url.searchParams.get("tier") as Tier;
      const id = url.searchParams.get("id");
      if (!tier || !id) {
        return new Response(
          JSON.stringify({ error: "Missing 'tier' and 'id' for DELETE" }),
          { status: 400, headers }
        );
      }
      result = await handleDelete(tier, id);
    } else {
      return new Response(
        JSON.stringify({ error: "Method not allowed" }),
        { status: 405, headers }
      );
    }

    const statusCode = result.success ? 200 : 400;
    console.log(`[memory-manager] ${requestId} ${req.method} success=${result.success}`);
    return new Response(JSON.stringify(result), { status: statusCode, headers });

  } catch (e) {
    console.error(`[memory-manager] ${requestId} error:`, e);
    return new Response(
      JSON.stringify({ success: false, error: "Internal server error" }),
      { status: 500, headers }
    );
  }
});

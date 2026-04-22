// Supabase Edge Function: memory-manager
// CRUD operations for persistent memory across Claude sessions
//
// TIERS: core, active, sessions, improvements
//
// ENDPOINTS:
// GET  /functions/v1/memory-manager?tier=core&project=fabrikiq
// GET  /functions/v1/memory-manager?tier=improvements&status=experimenting
// GET  /functions/v1/memory-manager?action=search&q=flutter&project=fabrikiq
// GET  /functions/v1/memory-manager?action=search&q=flutter&semantic=true  (Vector Search)
// GET  /functions/v1/memory-manager?action=backup
// GET  /functions/v1/memory-manager?action=load_session&project=fabrikiq  (Session-Start: loads core + active + improvements)
// POST /functions/v1/memory-manager  (create or update entry, auto-generates embedding if OPENAI_API_KEY set)
// POST /functions/v1/memory-manager  { "action": "backfill_embeddings", "tier": "core" }  (Backfill)
// DELETE /functions/v1/memory-manager?tier=active&id=<uuid>         (soft: resolved=true)
// DELETE /functions/v1/memory-manager?tier=improvements&id=<uuid>   (soft: status=retired)
// DELETE /functions/v1/memory-manager?tier=core&id=<uuid>           (hard delete)
//
// ERROR HANDLING:
// - 400: Validation failure (missing fields, invalid enum, type error, invalid JSON) — body includes `field` and/or `pg_code`.
// - 401: Missing/invalid bearer token.
// - 404: N/A (no 404 from this function currently).
// - 409: Unique constraint violation.
// - 500: Actual server error only (unexpected exceptions). Never for bad payloads.
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

const VALID_TIERS = ["core", "active", "sessions", "improvements"] as const;
type Tier = typeof VALID_TIERS[number];

function getTableName(tier: Tier): string {
  return `memory_${tier}`;
}

// =============================================================================
// Validation constants (mirror Postgres CHECK constraints)
// =============================================================================

const CORE_CATEGORIES = [
  "preference", "architecture", "pattern", "context", "tool_config", "decision",
  "user_profile", "user_values", "work_style", "communication",
  "pain_points", "workflow_preference",
] as const;

const ACTIVE_CATEGORIES = [
  "work_state", "open_question", "next_step", "blocker", "decision_pending", "learning",
] as const;

const IMPROVEMENT_CATEGORIES = [
  "skill", "hook", "workflow", "process", "command", "agent",
] as const;

const IMPROVEMENT_STATUSES = [
  "experimenting", "proven", "retired",
] as const;

const IMPORTANCE_VALUES = ["low", "normal", "high", "critical"] as const;
const PRIORITY_VALUES = ["low", "normal", "high", "urgent"] as const;
const SESSION_TOOLS = ["cowork", "claude_code", "api", "other", "openclaw"] as const;

type ValidationError = { field: string; message: string };

function validateCreatePayload(tier: Tier, entry: Record<string, unknown>): ValidationError | null {
  // tags must be array (if present)
  if ("tags" in entry && entry.tags !== null && entry.tags !== undefined && !Array.isArray(entry.tags)) {
    return { field: "tags", message: "must be an array of strings" };
  }

  if (tier === "core") {
    if (!entry.title || typeof entry.title !== "string") {
      return { field: "title", message: "required string" };
    }
    if (!entry.content || typeof entry.content !== "string") {
      return { field: "content", message: "required string" };
    }
    if (!entry.category || !CORE_CATEGORIES.includes(entry.category as typeof CORE_CATEGORIES[number])) {
      return {
        field: "category",
        message: `must be one of: ${CORE_CATEGORIES.join(", ")}`,
      };
    }
    if (entry.importance && !IMPORTANCE_VALUES.includes(entry.importance as typeof IMPORTANCE_VALUES[number])) {
      return {
        field: "importance",
        message: `must be one of: ${IMPORTANCE_VALUES.join(", ")}`,
      };
    }
  } else if (tier === "active") {
    if (!entry.title || typeof entry.title !== "string") {
      return { field: "title", message: "required string" };
    }
    if (!entry.content || typeof entry.content !== "string") {
      return { field: "content", message: "required string" };
    }
    if (!entry.category || !ACTIVE_CATEGORIES.includes(entry.category as typeof ACTIVE_CATEGORIES[number])) {
      return {
        field: "category",
        message: `must be one of: ${ACTIVE_CATEGORIES.join(", ")}`,
      };
    }
    if (entry.priority && !PRIORITY_VALUES.includes(entry.priority as typeof PRIORITY_VALUES[number])) {
      return {
        field: "priority",
        message: `must be one of: ${PRIORITY_VALUES.join(", ")}`,
      };
    }
  } else if (tier === "sessions") {
    if (!entry.session_id || typeof entry.session_id !== "string") {
      return { field: "session_id", message: "required string" };
    }
    if (!entry.summary || typeof entry.summary !== "string") {
      return { field: "summary", message: "required string" };
    }
    if (entry.tool && !SESSION_TOOLS.includes(entry.tool as typeof SESSION_TOOLS[number])) {
      return {
        field: "tool",
        message: `must be one of: ${SESSION_TOOLS.join(", ")}`,
      };
    }
  } else if (tier === "improvements") {
    if (!entry.title || typeof entry.title !== "string") {
      return { field: "title", message: "required string" };
    }
    if (!entry.category || !IMPROVEMENT_CATEGORIES.includes(entry.category as typeof IMPROVEMENT_CATEGORIES[number])) {
      return {
        field: "category",
        message: `must be one of: ${IMPROVEMENT_CATEGORIES.join(", ")}`,
      };
    }
    if (entry.status && !IMPROVEMENT_STATUSES.includes(entry.status as typeof IMPROVEMENT_STATUSES[number])) {
      return {
        field: "status",
        message: `must be one of: ${IMPROVEMENT_STATUSES.join(", ")}`,
      };
    }
    if ("related_files" in entry && entry.related_files !== null && entry.related_files !== undefined && !Array.isArray(entry.related_files)) {
      return { field: "related_files", message: "must be an array of strings" };
    }
  }

  return null;
}

function mapPgErrorToResponse(error: { code?: string; message?: string; details?: string } | null | undefined) {
  if (!error?.code) return null;
  const base = { pg_code: error.code, details: error.details || error.message };
  switch (error.code) {
    case "23502":
      return { status: 400, body: { success: false, error: "Missing required field", ...base } };
    case "23514":
      return { status: 400, body: { success: false, error: "Invalid enum value (CHECK constraint)", ...base } };
    case "22P02":
      return { status: 400, body: { success: false, error: "Invalid data type", ...base } };
    case "23505":
      return { status: 409, body: { success: false, error: "Duplicate entry (unique constraint)", ...base } };
    case "23503":
      return { status: 400, body: { success: false, error: "Foreign key violation", ...base } };
    default:
      return null;
  }
}

// =============================================================================
// GET handlers
// =============================================================================

async function handleLoadSession(project?: string) {
  const coreQuery = supabase.from("memory_core").select("*");
  const activeQuery = supabase.from("memory_active").select("*").eq("resolved", false);
  const sessionsQuery = supabase.from("memory_sessions").select("*")
    .order("created_at", { ascending: false }).limit(5);
  // improvements: only experimenting entries are "active"; proven/retired shown on demand
  const improvementsQuery = supabase.from("memory_improvements").select("*")
    .eq("status", "experimenting");

  if (project) {
    coreQuery.or(`project.eq.${project},project.is.null`);
    activeQuery.or(`project.eq.${project},project.is.null`);
    sessionsQuery.or(`project.eq.${project},project.is.null`);
    improvementsQuery.or(`project.eq.${project},project.is.null`);
  }

  const [coreResult, activeResult, sessionsResult, improvementsResult] = await Promise.all([
    coreQuery, activeQuery, sessionsQuery, improvementsQuery,
  ]);

  // memory_improvements table may not exist yet (pre-migration). Tolerate that.
  const improvementsAvailable = !improvementsResult.error;

  return {
    success: true,
    action: "load_session",
    project: project || "all",
    vector_search_enabled: !!OPENAI_API_KEY,
    core: { count: coreResult.data?.length || 0, data: coreResult.data || [] },
    active: { count: activeResult.data?.length || 0, data: activeResult.data || [] },
    recent_sessions: { count: sessionsResult.data?.length || 0, data: sessionsResult.data || [] },
    improvements: improvementsAvailable
      ? { count: improvementsResult.data?.length || 0, data: improvementsResult.data || [] }
      : { count: 0, data: [], unavailable: true },
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
        match_count: 20,
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
  const status = params.get("status");
  const limit = Math.min(parseInt(params.get("limit") || "50", 10) || 50, 500);

  if (project) query = query.eq("project", project);
  if (category) query = query.eq("category", category);
  if (tag) query = query.contains("tags", [tag]);
  if (tier === "active") {
    const showResolved = params.get("resolved") === "true";
    if (!showResolved) query = query.eq("resolved", false);
  }
  if (tier === "improvements" && status) {
    query = query.eq("status", status);
  }

  query = query.order("created_at", { ascending: false }).limit(limit);

  const { data, error } = await query;
  if (error) throw error;

  return { success: true, tier, count: data?.length || 0, data: data || [] };
}

// =============================================================================
// POST handler (with optional embedding generation)
// =============================================================================

type PostResult =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; status: number; body: Record<string, unknown> };

async function handlePost(body: any): Promise<PostResult> {
  const { tier, action: bodyAction, ...entry } = body || {};

  // Allowlist: only forward known fields to the DB. Fields per tier.
  const ALLOWED_FIELDS = [
    // Shared
    'id', 'project', 'category', 'title', 'content', 'tags',
    // core
    'importance',
    // active
    'priority', 'resolved', 'resolved_at',
    // sessions
    'session_id', 'tool', 'summary',
    'decisions_made', 'issues_encountered', 'files_changed',
    // improvements
    'status', 'introduced_at', 'evidence', 'next_step',
    'related_files', 'model_version_notes',
    'last_used_at', 'use_count',
  ];
  const sanitizedEntry: Record<string, unknown> = {};
  for (const key of ALLOWED_FIELDS) {
    if (entry && key in entry) {
      sanitizedEntry[key] = entry[key];
    }
  }

  // Backfill embeddings action
  if (bodyAction === "backfill_embeddings") {
    if (!OPENAI_API_KEY) {
      return { ok: false, status: 400, body: { success: false, error: "OPENAI_API_KEY not configured" } };
    }
    if (!tier || !["core", "active"].includes(tier)) {
      return { ok: false, status: 400, body: { success: false, error: "Backfill requires tier: core or active" } };
    }
    const table = getTableName(tier as Tier);
    const { data: entries, error } = await supabase
      .from(table)
      .select("id, title, content")
      .is("embedding", null)
      .limit(50);

    if (error) throw error;
    if (!entries || entries.length === 0) {
      return { ok: true, value: { success: true, action: "backfill_embeddings", tier, processed: 0, errors: 0 } };
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
      ok: true,
      value: { success: true, action: "backfill_embeddings", tier, processed, errors },
    };
  }

  if (!tier || !VALID_TIERS.includes(tier)) {
    return {
      ok: false,
      status: 400,
      body: { success: false, error: `Invalid tier. Valid: ${VALID_TIERS.join(", ")}` },
    };
  }

  // For updates (id present), skip strict validation — partial updates allowed.
  // For inserts, enforce required fields + enum constraints upfront.
  if (!sanitizedEntry.id) {
    const validationError = validateCreatePayload(tier as Tier, sanitizedEntry);
    if (validationError) {
      return {
        ok: false,
        status: 400,
        body: {
          success: false,
          error: `Validation failed: ${validationError.field} ${validationError.message}`,
          field: validationError.field,
        },
      };
    }
  }

  const table = getTableName(tier as Tier);

  // Generate embedding for core, active, improvements (not sessions).
  // Improvements use title + (next_step || evidence || '') since there is no content field.
  if (OPENAI_API_KEY) {
    if ((tier === "core" || tier === "active") && sanitizedEntry.title && sanitizedEntry.content) {
      const embedding = await generateEmbedding(`${sanitizedEntry.title} ${sanitizedEntry.content}`);
      if (embedding) sanitizedEntry.embedding = embedding;
    } else if (tier === "improvements" && sanitizedEntry.title) {
      const extra = (sanitizedEntry.next_step as string) || (sanitizedEntry.evidence as string) || "";
      const embedding = await generateEmbedding(`${sanitizedEntry.title} ${extra}`.trim());
      if (embedding) sanitizedEntry.embedding = embedding;
    }
  }

  // Upsert: if id is provided, update; otherwise insert
  if (sanitizedEntry.id) {
    const { data, error } = await supabase
      .from(table)
      .update(sanitizedEntry)
      .eq("id", sanitizedEntry.id)
      .select()
      .single();

    if (error) {
      const mapped = mapPgErrorToResponse(error);
      if (mapped) return { ok: false, ...mapped };
      throw error;
    }
    return {
      ok: true,
      value: {
        success: true,
        action: "updated",
        tier,
        embedding_generated: !!sanitizedEntry.embedding,
        data,
      },
    };
  } else {
    const { data, error } = await supabase
      .from(table)
      .insert(sanitizedEntry)
      .select()
      .single();

    if (error) {
      const mapped = mapPgErrorToResponse(error);
      if (mapped) return { ok: false, ...mapped };
      throw error;
    }
    return {
      ok: true,
      value: {
        success: true,
        action: "created",
        tier,
        embedding_generated: !!sanitizedEntry.embedding,
        data,
      },
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

  if (tier === "improvements") {
    // Soft-retire instead of hard-delete to preserve history
    const { data, error } = await supabase
      .from(table)
      .update({ status: "retired" })
      .eq("id", id)
      .select()
      .single();

    if (error) throw error;
    return { success: true, action: "retired", tier, data };
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
      let body: unknown;
      try {
        body = await req.json();
      } catch (_e) {
        return new Response(
          JSON.stringify({ success: false, error: "Invalid JSON body" }),
          { status: 400, headers }
        );
      }
      const postResult = await handlePost(body);
      if (!postResult.ok) {
        console.log(`[memory-manager] ${requestId} POST validation_error status=${postResult.status}`);
        return new Response(JSON.stringify(postResult.body), { status: postResult.status, headers });
      }
      result = postResult.value;
    } else if (req.method === "DELETE") {
      const tier = url.searchParams.get("tier") as Tier;
      const id = url.searchParams.get("id");
      if (!tier || !VALID_TIERS.includes(tier) || !id) {
        return new Response(
          JSON.stringify({
            error: `Missing or invalid 'tier' and/or 'id' for DELETE. Valid tiers: ${VALID_TIERS.join(", ")}`,
          }),
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
    const err = e as { code?: string; message?: string; details?: string };
    const mapped = mapPgErrorToResponse(err);
    if (mapped) {
      console.log(`[memory-manager] ${requestId} pg_error code=${err.code}`);
      return new Response(JSON.stringify(mapped.body), { status: mapped.status, headers });
    }
    console.error(`[memory-manager] ${requestId} error:`, e);
    return new Response(
      JSON.stringify({ success: false, error: "Internal server error", message: err.message }),
      { status: 500, headers }
    );
  }
});

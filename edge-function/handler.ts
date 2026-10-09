// Memory API implementation. Dependencies are injected for offline regression tests.
type Row = Record<string, unknown>;
export type DatabaseError = {
  code?: string;
  message?: string;
  details?: string;
};
export type QueryResult<Single extends boolean = false> = {
  data: (Single extends true ? Row : Row[]) | null;
  error: DatabaseError | null;
  count?: number | null;
};
export interface MemoryQuery<Single extends boolean = false>
  extends PromiseLike<QueryResult<Single>> {
  select(columns?: string, options?: { count: "exact" }): MemoryQuery<Single>;
  eq(column: string, value: unknown): MemoryQuery<Single>;
  is(column: string, value: null): MemoryQuery<Single>;
  or(filter: string): MemoryQuery<Single>;
  contains(column: string, values: string[]): MemoryQuery<Single>;
  order(column: string, options: { ascending: boolean }): MemoryQuery<Single>;
  limit(count: number): MemoryQuery<Single>;
  update(value: Row): MemoryQuery<Single>;
  insert(value: Row): MemoryQuery<Single>;
  delete(): MemoryQuery<Single>;
  single(): MemoryQuery<true>;
}
export interface MemoryDatabase {
  from(table: string): MemoryQuery;
  rpc(
    name: string,
    args?: Row,
  ): PromiseLike<{ data: unknown; error: DatabaseError | null }>;
}
export interface HandlerDependencies {
  database: MemoryDatabase;
  env: (name: string) => string | undefined;
  fetch?: typeof fetch;
  now?: () => Date;
}

const TIERS = ["core", "active", "sessions", "improvements"] as const;
type Tier = typeof TIERS[number];
const CLIENT_SECRET_ENV = {
  cowork: "API_SECRET_COWORK",
  claude_code: "API_SECRET_CLAUDE_CODE",
  openclaw: "API_SECRET_OPENCLAW",
  api: "API_SECRET_API",
  backup: "API_SECRET_BACKUP",
  restore: "API_SECRET_RESTORE",
} as const;
type Client = keyof typeof CLIENT_SECRET_ENV;
type Role = "ordinary" | "backup" | "restore";
const CLIENTS = Object.keys(CLIENT_SECRET_ENV) as Client[];
const FIELDS: Record<Tier, readonly string[]> = {
  core: ["id", "project", "category", "title", "content", "tags", "importance"],
  active: [
    "id",
    "project",
    "category",
    "title",
    "content",
    "tags",
    "priority",
    "resolved",
  ],
  sessions: [
    "id",
    "project",
    "session_id",
    "tool",
    "summary",
    "decisions_made",
    "issues_encountered",
    "files_changed",
    "tags",
  ],
  improvements: [
    "id",
    "project",
    "title",
    "category",
    "status",
    "introduced_at",
    "evidence",
    "next_step",
    "related_files",
    "model_version_notes",
    "tags",
    "last_used_at",
    "use_count",
  ],
};
const CATEGORIES = {
  core: [
    "preference",
    "architecture",
    "pattern",
    "context",
    "tool_config",
    "decision",
    "user_profile",
    "user_values",
    "work_style",
    "communication",
    "pain_points",
    "workflow_preference",
  ],
  active: [
    "work_state",
    "open_question",
    "next_step",
    "blocker",
    "decision_pending",
    "learning",
  ],
  improvements: ["skill", "hook", "workflow", "process", "command", "agent"],
};
const ENUMS: Record<string, readonly string[]> = {
  importance: ["low", "normal", "high", "critical"],
  priority: ["low", "normal", "high", "urgent"],
  status: ["experimenting", "proven", "retired"],
  tool: ["cowork", "claude_code", "api", "other", "openclaw"],
};
const ARRAY_FIELDS = [
  "tags",
  "decisions_made",
  "issues_encountered",
  "files_changed",
  "related_files",
];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const corsHeaders = {
  "Content-Type": "application/json",
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers":
    "authorization, x-memory-client, x-client-info, apikey, content-type",
};

function isRow(value: unknown): value is Row {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isTier(value: unknown): value is Tier {
  return typeof value === "string" && TIERS.includes(value as Tier);
}
class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly field?: string,
  ) {
    super(message);
  }
}
function invalid(field: string, message: string): never {
  throw new HttpError(400, `Validation failed: ${field} ${message}`, field);
}

function validateEntry(
  tier: Tier,
  entry: Row,
  partial: boolean,
  restore = false,
) {
  const allowed = [...FIELDS[tier]];
  if (restore) {
    allowed.push("created_at");
    if (tier !== "sessions") allowed.push("updated_at");
    if (tier === "active") allowed.push("resolved_at");
  }
  for (const key of Object.keys(entry)) {
    if (!allowed.includes(key)) invalid(key, `is not allowed for ${tier}`);
  }
  const required = tier === "sessions"
    ? ["session_id", "summary"]
    : tier === "improvements"
    ? ["title", "category"]
    : ["title", "content", "category"];
  if (!partial) {
    for (const field of required) {
      if (!(field in entry)) invalid(field, "is required");
    }
  }
  if (restore) {
    for (
      const field of [
        "id",
        "created_at",
        ...(tier === "sessions" ? [] : ["updated_at"]),
      ]
    ) {
      if (!(field in entry)) invalid(field, "is required for restore");
    }
  }
  for (const [field, value] of Object.entries(entry)) {
    if (field === "id") {
      if (typeof value !== "string" || !UUID.test(value)) {
        invalid(field, "must be a UUID");
      }
      continue;
    }
    const notNull = required.includes(field) ||
      (tier === "improvements" && ["status", "use_count"].includes(field));
    if (value === null && !notNull && (field !== "resolved" || restore)) {
      continue;
    }
    if (ARRAY_FIELDS.includes(field)) {
      if (
        !Array.isArray(value) ||
        !value.every((item) =>
          typeof item === "string" || (restore && item === null)
        )
      ) invalid(field, "must be an array of strings");
    } else if (field === "resolved") {
      if (typeof value !== "boolean") invalid(field, "must be a boolean");
    } else if (field === "use_count") {
      if (
        typeof value !== "number" || !Number.isInteger(value) || value < 0 ||
        value > 2147483647
      ) invalid(field, "must be a nonnegative integer");
    } else {
      if (typeof value !== "string") invalid(field, "must be a string");
      if (!restore && required.includes(field) && !value.trim()) {
        invalid(field, "must not be empty");
      }
      const enumeration = field === "category" && tier !== "sessions"
        ? CATEGORIES[tier]
        : ENUMS[field];
      if (enumeration && !enumeration.includes(value)) {
        invalid(field, `must be one of: ${enumeration.join(", ")}`);
      }
      if (
        ["created_at", "updated_at", "resolved_at", "last_used_at"].includes(
          field,
        ) && (!TIMESTAMP.test(value) || !Number.isFinite(Date.parse(value)))
      ) invalid(field, "must be an ISO timestamp with timezone");
      if (
        field === "introduced_at" &&
        (!/^\d{4}-\d{2}-\d{2}$/.test(value) ||
          !Number.isFinite(Date.parse(value)) ||
          new Date(value).toISOString().slice(0, 10) !== value)
      ) invalid(field, "must be a valid ISO date");
    }
  }
}

function pgStatus(error: DatabaseError): number {
  if (error.code === "23505") return 409;
  if (error.code === "PGRST116") return 404;
  if (
    ["23502", "23514", "22P02", "23503", "22023", "22007", "22008"].includes(
      error.code || "",
    )
  ) return 400;
  return 500;
}

export function createMemoryHandler(dependencies: HandlerDependencies) {
  const supabase = dependencies.database;
  const env = (key: string) => dependencies.env(key)?.trim();
  const fetchRequest = dependencies.fetch || fetch;
  const now = dependencies.now || (() => new Date());

  function authorize(req: Request): Role {
    const token = /^Bearer\s+(\S+)\s*$/i.exec(
      req.headers.get("Authorization") || "",
    )?.[1];
    if (!token) throw new HttpError(401, "Unauthorized");
    const rawClient = (req.headers.get("X-Memory-Client") ||
      new URL(req.url).searchParams.get("client") || "").trim().toLowerCase();
    if (rawClient && !CLIENTS.includes(rawClient as Client)) {
      throw new HttpError(400, "Invalid client");
    }
    const client = rawClient as Client | "";
    const secrets = Object.fromEntries(
      CLIENTS.map((name) => [name, env(CLIENT_SECRET_ENV[name])]),
    ) as Partial<Record<Client, string>>;
    const legacy = env("API_SECRET");
    if (!legacy && !Object.values(secrets).some(Boolean)) {
      throw new HttpError(500, "Server auth config missing");
    }
    const matches = CLIENTS.filter((name) =>
      !!secrets[name] && secrets[name] === token
    );
    const privilegedMatches = matches.filter((name) =>
      name === "restore" || name === "backup"
    );
    // Reserved credentials cannot be reused for another role; a header must never escalate rights.
    if (privilegedMatches.length && (matches.length > 1 || token === legacy)) {
      throw new HttpError(500, "Server auth role configuration invalid");
    }
    if (client) {
      const secret = secrets[client];
      const reserved = client === "restore" || client === "backup";
      if (
        !(secret ? secret === token : !reserved && !!legacy && legacy === token)
      ) throw new HttpError(401, "Unauthorized");
    } else if (!matches.length && token !== legacy) {
      throw new HttpError(401, "Unauthorized");
    }
    const role = privilegedMatches[0] || "ordinary";
    if (
      role === "restore" &&
      req.headers.get("X-Memory-Client")?.trim().toLowerCase() !== "restore"
    ) {
      throw new HttpError(
        403,
        "Restore credential requires X-Memory-Client: restore",
      );
    }
    if (role === "backup" && req.method !== "GET") {
      throw new HttpError(403, "Backup credential is read-only");
    }
    if (
      role === "restore" &&
      !(req.method === "POST" ||
        (req.method === "GET" &&
          new URL(req.url).searchParams.get("action") === "backup"))
    ) {
      throw new HttpError(
        403,
        "Restore credential only permits backup inspection and restore",
      );
    }
    return role;
  }

  async function generateEmbedding(text: string): Promise<number[] | null> {
    const key = env("OPENAI_API_KEY");
    if (!key || !text.trim()) return null;
    try {
      const response = await fetchRequest(
        "https://api.openai.com/v1/embeddings",
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${key}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: "text-embedding-3-small",
            input: text.slice(0, 32000),
            dimensions: 1536,
          }),
        },
      );
      if (!response.ok) return null;
      const payload: unknown = await response.json();
      const first = isRow(payload) && Array.isArray(payload.data)
        ? payload.data[0]
        : null;
      const embedding = isRow(first) ? first.embedding : null;
      return Array.isArray(embedding) && embedding.length === 1536 &&
          embedding.every((value) =>
            typeof value === "number" && Number.isFinite(value)
          )
        ? embedding
        : null;
    } catch {
      return null;
    }
  }

  async function handleLoadSession(project?: string) {
    const blocks = await Promise.all(TIERS.map(async (tier) => {
      const limit = tier === "sessions" ? 5 : 500;
      let query = supabase.from(`memory_${tier}`).select("*", {
        count: "exact",
      });
      if (tier === "active") query = query.eq("resolved", false);
      if (tier === "improvements") query = query.eq("status", "experimenting");
      if (project) {
        // Quoting prevents punctuation in project names from becoming PostgREST filter syntax.
        const quoted = `"${
          project.replaceAll("\\", "\\\\").replaceAll('"', '\\"')
        }"`;
        query = query.or(
          `project.eq.${quoted},project.in.(global,shared),project.is.null`,
        );
      }
      const { data, error, count } = await query.order("created_at", {
        ascending: false,
      }).order("id", { ascending: true }).limit(limit);
      if (error) throw error;
      if (
        !data || !Number.isInteger(count) || count === null ||
        count === undefined || count < data.length
      ) throw new Error("Incomplete session query");
      return {
        count: data.length,
        total_count: count,
        limit,
        truncated: count > data.length,
        data,
      };
    }));
    return {
      success: true,
      action: "load_session",
      project: project || "all",
      vector_search_enabled: !!env("OPENAI_API_KEY"),
      truncated: blocks.some((block) => block.truncated),
      core: blocks[0],
      active: blocks[1],
      recent_sessions: blocks[2],
      improvements: blocks[3],
    };
  }

  async function handleBackup() {
    const { data, error } = await supabase.rpc("export_memory_backup");
    if (error) throw error;
    if (
      !isRow(data) || data.schema_version !== 1 || data.complete !== true ||
      typeof data.exported_at !== "string" ||
      !TIMESTAMP.test(data.exported_at) ||
      !Number.isFinite(Date.parse(data.exported_at))
    ) throw new Error("Invalid backup snapshot");
    for (const tier of TIERS) {
      const block = data[tier];
      if (
        !isRow(block) || !Array.isArray(block.data) ||
        !Number.isInteger(block.count) || block.count !== block.data.length ||
        !block.data.every(isRow)
      ) throw new Error(`Incomplete backup tier ${tier}`);
    }
    return { ...data, success: true, action: "backup" };
  }

  async function handleSearch(
    query: string,
    project?: string,
    semantic = false,
  ) {
    if (semantic) {
      const embedding = await generateEmbedding(query);
      if (embedding) {
        const { data, error } = await supabase.rpc("search_memory_semantic", {
          query_embedding: JSON.stringify(embedding),
          match_threshold: 0.5,
          match_count: 20,
          filter_project: project || null,
        });
        if (!error && Array.isArray(data)) {
          return {
            success: true,
            action: "search",
            search_type: "semantic",
            query,
            project: project || "all",
            count: data.length,
            results: data,
          };
        }
      }
    }
    const { data, error } = await supabase.rpc("search_memory", {
      search_term: query,
      filter_project: project || null,
    });
    if (error) throw error;
    if (!Array.isArray(data)) throw new Error("Invalid search result");
    return {
      success: true,
      action: "search",
      search_type: "text",
      query,
      project: project || "all",
      count: data.length,
      results: data,
    };
  }

  async function handleGet(tier: Tier, params: URLSearchParams) {
    let query = supabase.from(`memory_${tier}`).select("*");
    for (const key of ["project", "category"]) {
      if (params.get(key)) query = query.eq(key, params.get(key));
    }
    if (params.get("tag")) query = query.contains("tags", [params.get("tag")!]);
    if (tier === "active" && params.get("resolved") !== "true") {
      query = query.eq("resolved", false);
    }
    if (tier === "improvements" && params.get("status")) {
      query = query.eq("status", params.get("status"));
    }
    const limit = Math.max(
      1,
      Math.min(Number.parseInt(params.get("limit") || "50", 10) || 50, 500),
    );
    const { data, error } = await query.order("created_at", {
      ascending: false,
    }).limit(limit);
    if (error) throw error;
    return { success: true, tier, count: data?.length || 0, data: data || [] };
  }

  async function handlePost(body: unknown, role: Role) {
    if (!isRow(body)) throw new HttpError(400, "JSON body must be an object");
    const { tier, action, ...entry } = body;
    if (!isTier(tier)) invalid("tier", `must be one of: ${TIERS.join(", ")}`);
    if (action === "restore") {
      if (role !== "restore") {
        throw new HttpError(
          403,
          "Restore requires a dedicated restore credential",
        );
      }
      if (
        Object.keys(entry).some((key) => key !== "record") ||
        !isRow(entry.record)
      ) invalid("record", "must be a restore record");
      validateEntry(tier, entry.record, false, true);
      const { data, error } = await supabase.rpc("restore_memory_record", {
        p_tier: tier,
        p_record: entry.record,
      });
      if (error) throw error;
      if (
        !isRow(data) || typeof data.inserted !== "boolean" ||
        typeof data.id !== "string" ||
        data.id.toLowerCase() !== String(entry.record.id).toLowerCase()
      ) throw new Error("Invalid restore result");
      return {
        success: true,
        action: "restore",
        tier,
        inserted: data.inserted,
        id: data.id,
      };
    }
    if (role === "restore") {
      throw new HttpError(
        403,
        "Restore credential only permits restore writes",
      );
    }
    if (action === "backfill_embeddings") {
      if (!env("OPENAI_API_KEY")) {
        throw new HttpError(400, "OPENAI_API_KEY not configured");
      }
      if (tier !== "core" && tier !== "active") {
        invalid("tier", "backfill requires core or active");
      }
      const { data: entries, error } = await supabase.from(`memory_${tier}`)
        .select("id, title, content").is("embedding", null).limit(50);
      if (error) throw error;
      let processed = 0;
      let errors = 0;
      for (const item of entries || []) {
        const embedding = await generateEmbedding(
          `${item.title} ${item.content}`,
        );
        if (!embedding) {
          errors++;
        } else {
          const { error: updateError } = await supabase.from(`memory_${tier}`)
            .update({ embedding }).eq("id", item.id);
          if (updateError) errors++;
          else processed++;
        }
        // Preserve the existing backfill pacing for optional provider requests.
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      return {
        success: true,
        action: "backfill_embeddings",
        tier,
        processed,
        errors,
      };
    }
    if (action !== undefined) invalid("action", "is unsupported");
    const updating = "id" in entry;
    validateEntry(tier, entry, updating);
    if (updating && Object.keys(entry).length === 1) {
      throw new HttpError(400, "Update requires at least one field");
    }
    const table = `memory_${tier}`;
    const embeddingFields = tier === "improvements"
      ? ["title", "evidence", "next_step", "model_version_notes"]
      : ["title", "content"];
    const textChanged = tier !== "sessions" &&
      embeddingFields.some((field) => field in entry);
    // Read complete text for partial updates and active state to preserve a previous resolution time.
    let previous: Row = {};
    if (
      updating && (textChanged || (tier === "active" && "resolved" in entry))
    ) {
      const { data, error } = await supabase.from(table).select("*").eq(
        "id",
        entry.id,
      ).single();
      if (error) throw error;
      if (!data) throw new HttpError(404, "Entry not found");
      previous = data;
    }
    if (textChanged) {
      const combined = { ...previous, ...entry };
      const text = embeddingFields.map((field) => combined[field] || "").join(
        " ",
      ).trim();
      entry.embedding = await generateEmbedding(text); // null invalidates stale vectors when AI is disabled or fails.
    }
    if (tier === "active" && "resolved" in entry) {
      entry.resolved_at = entry.resolved
        ? (previous.resolved === true && previous.resolved_at
          ? previous.resolved_at
          : now().toISOString())
        : null;
    }
    const query = updating
      ? supabase.from(table).update(entry).eq("id", entry.id)
      : supabase.from(table).insert(entry);
    const { data, error } = await query.select().single();
    if (error) throw error;
    return {
      success: true,
      action: updating ? "updated" : "created",
      tier,
      embedding_generated: Array.isArray(entry.embedding),
      data,
    };
  }

  async function handleDelete(tier: Tier, id: string) {
    if (!UUID.test(id)) invalid("id", "must be a UUID");
    if (tier === "active") {
      const updated = await handlePost(
        { tier, id, resolved: true },
        "ordinary",
      );
      return { ...updated, action: "resolved" };
    }
    if (tier === "improvements") {
      const { data, error } = await supabase.from(`memory_${tier}`).update({
        status: "retired",
      }).eq("id", id).select().single();
      if (error) throw error;
      return { success: true, action: "retired", tier, data };
    }
    const { error } = await supabase.from(`memory_${tier}`).delete().eq(
      "id",
      id,
    );
    if (error) throw error;
    return { success: true, action: "deleted", tier, id };
  }

  return async (req: Request): Promise<Response> => {
    const requestId = crypto.randomUUID().slice(0, 8);
    const headers = { ...corsHeaders, "X-Request-Id": requestId };
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 200, headers });
    }
    try {
      const role = authorize(req);
      const url = new URL(req.url);
      let result: Row;
      if (req.method === "GET") {
        const action = url.searchParams.get("action");
        const project = url.searchParams.get("project") || undefined;
        if (action === "load_session") {
          result = await handleLoadSession(project);
        } else if (action === "backup") result = await handleBackup();
        else if (action === "search") {
          const q = url.searchParams.get("q");
          if (!q) invalid("q", "is required for search");
          result = await handleSearch(
            q,
            project,
            url.searchParams.get("semantic") === "true",
          );
        } else {
          const tier = url.searchParams.get("tier");
          if (!isTier(tier)) {
            invalid("tier", `must be one of: ${TIERS.join(", ")}`);
          }
          result = await handleGet(tier, url.searchParams);
        }
      } else if (req.method === "POST") {
        let body: unknown;
        try {
          body = await req.json();
        } catch {
          throw new HttpError(400, "Invalid JSON body");
        }
        result = await handlePost(body, role);
      } else if (req.method === "DELETE") {
        const tier = url.searchParams.get("tier");
        const id = url.searchParams.get("id");
        if (!isTier(tier)) {
          invalid("tier", `must be one of: ${TIERS.join(", ")}`);
        }
        if (!id) invalid("id", "is required for DELETE");
        result = await handleDelete(tier, id);
      } else throw new HttpError(405, "Method not allowed");
      return new Response(JSON.stringify(result), { status: 200, headers });
    } catch (error) {
      if (error instanceof HttpError) {
        return new Response(
          JSON.stringify({
            success: false,
            error: error.message,
            ...(error.field ? { field: error.field } : {}),
          }),
          { status: error.status, headers },
        );
      }
      const status = isRow(error) ? pgStatus(error) : 500;
      // Only log a code and correlation ID; database/provider details can contain memory text.
      console.error(
        `[memory-manager] ${requestId} error status=${status} code=${
          isRow(error) ? error.code || "unknown" : "unknown"
        }`,
      );
      return new Response(
        JSON.stringify({
          success: false,
          error: status === 500
            ? "Internal server error"
            : status === 404
            ? "Entry not found"
            : status === 409
            ? "Duplicate entry"
            : "Invalid database value",
          request_id: requestId,
          ...(isRow(error) && typeof error.code === "string"
            ? { pg_code: error.code }
            : {}),
        }),
        { status, headers },
      );
    }
  };
}

import {
  createMemoryHandler,
  type DatabaseError,
  type HandlerDependencies,
  type MemoryDatabase,
  type MemoryQuery,
  type QueryResult,
} from "./handler.ts";

type Row = Record<string, unknown>;
const ID = "11111111-1111-4111-8111-111111111111";
const DATE = "2026-01-02T03:04:05.000Z";
const NOW = "2026-10-10T01:00:00.000Z";
const ordinary = "unit-test-owner-credential";
const backup = "unit-test-backup-credential";
const restore = "unit-test-restore-credential";
function equal(actual: unknown, expected: unknown) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Expected ${JSON.stringify(expected)}, received ${
        JSON.stringify(actual)
      }`,
    );
  }
}
function assert(value: unknown, message = "Assertion failed"): asserts value {
  if (!value) throw new Error(message);
}

// Executes the small query surface used by the handler, including limits and exact counts.
class FakeQuery<Single extends boolean = false> implements MemoryQuery<Single> {
  private operation = "select";
  private value: Row = {};
  private filters: [string, unknown][] = [];
  private maximum = Infinity;
  private singular = false;
  private exactCount = false;
  constructor(private database: FakeDatabase, private table: string) {}
  select(_columns?: string, options?: { count: "exact" }): this {
    this.exactCount = options?.count === "exact";
    return this;
  }
  eq(column: string, value: unknown): this {
    this.filters.push([column, value]);
    return this;
  }
  is(column: string, value: null): this {
    return this.eq(column, value);
  }
  or(filter: string): this {
    this.database.scopes.push(filter);
    return this;
  }
  contains(_column: string, _values: string[]): this {
    return this;
  }
  order(_column: string, _options: { ascending: boolean }): this {
    return this;
  }
  limit(count: number): this {
    this.maximum = count;
    return this;
  }
  update(value: Row): this {
    this.operation = "update";
    this.value = { ...value };
    return this;
  }
  insert(value: Row): this {
    this.operation = "insert";
    this.value = { ...value };
    return this;
  }
  delete(): this {
    this.operation = "delete";
    return this;
  }
  single(): MemoryQuery<true> {
    this.singular = true;
    return this as unknown as MemoryQuery<true>;
  }
  private run(): QueryResult<Single> {
    this.database.queries.push({
      table: this.table,
      operation: this.operation,
      value: this.value,
      maximum: this.maximum,
    });
    const error = this.database.failures[this.table];
    if (error) return { data: null, error };
    const rows = this.database.rows[this.table] ||
      (this.database.rows[this.table] = []);
    let selected = rows.filter((row) =>
      this.filters.every(([field, value]) => row[field] === value)
    );
    if (this.operation === "update") {
      selected.forEach((row) => Object.assign(row, this.value));
    }
    if (this.operation === "insert") {
      const created = { id: ID, ...this.value };
      rows.push(created);
      selected = [created];
    }
    if (this.operation === "delete") {
      this.database.rows[this.table] = rows.filter((row) =>
        !selected.includes(row)
      );
    }
    const count = this.exactCount ? selected.length : null;
    selected = selected.slice(0, this.maximum);
    if (this.singular && !selected.length) {
      return { data: null, error: { code: "PGRST116" } };
    }
    return {
      data: (this.singular ? selected[0] : selected) as QueryResult<
        Single
      >["data"],
      error: null,
      count: this.database.omitCount ? null : count,
    };
  }
  then<TResult1 = QueryResult<Single>, TResult2 = never>(
    onfulfilled?:
      | ((value: QueryResult<Single>) => TResult1 | PromiseLike<TResult1>)
      | null,
    onrejected?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ): PromiseLike<TResult1 | TResult2> {
    return Promise.resolve(this.run()).then(onfulfilled, onrejected);
  }
}
class FakeDatabase implements MemoryDatabase {
  rows: Record<string, Row[]> = {};
  failures: Record<string, DatabaseError> = {};
  queries: { table: string; operation: string; value: Row; maximum: number }[] =
    [];
  scopes: string[] = [];
  rpcCalls: { name: string; args?: Row }[] = [];
  rpcResult: { data: unknown; error: DatabaseError | null } = {
    data: null,
    error: null,
  };
  omitCount = false;
  from(table: string): MemoryQuery {
    return new FakeQuery(this, table);
  }
  rpc(name: string, args?: Row) {
    this.rpcCalls.push({ name, args });
    return Promise.resolve(this.rpcResult);
  }
}

function setup(
  config: Record<string, string | undefined> = { API_SECRET: ordinary },
  options: Partial<HandlerDependencies> = {},
) {
  const database = new FakeDatabase();
  const handler = createMemoryHandler({
    database,
    env: (name) => config[name],
    now: () => new Date(NOW),
    fetch: () => {
      throw new Error("Tests must never use the network");
    },
    ...options,
  });
  const call = async (
    method = "GET",
    query = "?action=backup",
    body?: unknown,
    token = ordinary,
    client?: string,
  ) => {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    };
    if (client) headers["X-Memory-Client"] = client;
    const response = await handler(
      new Request(`https://memory.test/${query}`, {
        method,
        headers,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      }),
    );
    const payload = await response.json() as Row;
    return { response, payload };
  };
  return { database, handler, call };
}
function snapshot(coreCount = 0, sessionsCount = 0) {
  const block = (count: number) => ({
    count,
    data: Array.from({ length: count }, (_, i) => ({ id: `record-${i}` })),
  });
  return {
    schema_version: 1,
    complete: true,
    exported_at: DATE,
    core: block(coreCount),
    active: block(0),
    sessions: block(sessionsCount),
    improvements: block(0),
  };
}
function coreRecord(): Row {
  return {
    id: ID,
    project: null,
    category: "context",
    title: "Original title",
    content: "Original body",
    tags: [],
    importance: "normal",
    created_at: DATE,
    updated_at: DATE,
  };
}

Deno.test("R3 backup propagates RPC errors instead of returning an empty success", async () => {
  const { database, call } = setup();
  database.rpcResult = {
    data: null,
    error: { code: "XX000", message: "private contents must not leak" },
  };
  const { response, payload } = await call();
  equal(response.status, 500);
  equal(payload.success, false);
  assert(!JSON.stringify(payload).includes("private contents"));
  equal(database.rpcCalls[0].name, "export_memory_backup");
});

Deno.test("R3 backup rejects missing tiers, partial snapshots and mismatched counts", async () => {
  for (
    const data of [{ success: true }, { ...snapshot(), complete: false }, {
      ...snapshot(),
      sessions: { count: 5, data: [] },
    }, { ...snapshot(), improvements: undefined }]
  ) {
    const { database, call } = setup();
    database.rpcResult = { data, error: null };
    equal((await call()).response.status, 500);
  }
});

Deno.test("R3 empty complete snapshot remains a valid backup", async () => {
  const { database, call } = setup();
  database.rpcResult = { data: snapshot(), error: null };
  const { response, payload } = await call();
  equal(response.status, 200);
  equal(payload.success, true);
  equal(payload.complete, true);
});

Deno.test("R4 export retains more than 1000 records and more than 100 sessions", async () => {
  const { database, call } = setup();
  database.rpcResult = { data: snapshot(1205, 237), error: null };
  const { response, payload } = await call();
  equal(response.status, 200);
  equal((payload.core as { data: unknown[] }).data.length, 1205);
  equal((payload.sessions as { data: unknown[] }).data.length, 237);
  equal(database.queries.length, 0);
  equal(database.rpcCalls.length, 1);
});

for (const tier of ["core", "active", "sessions", "improvements"]) {
  Deno.test(`R3 load_session fails when mandatory ${tier} query fails`, async () => {
    const { database, call } = setup();
    database.failures[`memory_${tier}`] = { code: "42P01" };
    const { response, payload } = await call("GET", "?action=load_session");
    equal(response.status, 500);
    equal(payload.success, false);
  });
}

Deno.test("R4 load_session reports total counts, limits and truncation explicitly", async () => {
  const { database, call } = setup();
  database.rows.memory_core = Array.from({ length: 1205 }, () => coreRecord());
  database.rows.memory_sessions = Array.from({ length: 9 }, () => ({ id: ID }));
  const { response, payload } = await call("GET", "?action=load_session");
  equal(response.status, 200);
  equal(payload.truncated, true);
  const core = payload.core as Row;
  equal(core.count, 500);
  equal(core.total_count, 1205);
  equal(core.limit, 500);
  equal(core.truncated, true);
  const sessions = payload.recent_sessions as Row;
  equal(sessions.count, 5);
  equal(sessions.total_count, 9);
  equal(sessions.truncated, true);
});

Deno.test("R4 session load without an exact database count fails closed", async () => {
  const { database, call } = setup();
  database.omitCount = true;
  equal((await call("GET", "?action=load_session")).response.status, 500);
});

Deno.test("R14 per-tier payload validation rejects unrelated fields and invalid partial updates before database writes", async () => {
  const { database, call } = setup();
  for (
    const entry of [
      {
        tier: "core",
        title: "A",
        content: "B",
        category: "context",
        priority: "urgent",
      },
      { tier: "active", id: ID, importance: "high" },
      { tier: "sessions", id: ID, content: "bad field" },
      { tier: "improvements", id: ID, content: "bad field" },
      { tier: "core", id: ID, importance: "urgent" },
      { tier: "core", id: ID, tags: [42] },
      { tier: "active", id: ID, resolved: "true" },
      { tier: "core", id: ID, created_at: DATE },
      { tier: "active", id: ID, resolved_at: DATE },
      { tier: "improvements", id: ID, use_count: -1 },
    ]
  ) {
    const { response, payload } = await call("POST", "", entry);
    equal(response.status, 400);
    equal(payload.success, false);
  }
  equal(database.queries.length, 0);
});

Deno.test("R14 required fields and JSON object shape are validated", async () => {
  const { database, call } = setup();
  for (
    const entry of [
      null,
      [],
      "text",
      { tier: "core", title: "A" },
      { tier: "active", title: "A", category: "work_state" },
      { tier: "sessions", session_id: "S" },
      { tier: "improvements", title: "A" },
    ]
  ) {
    equal((await call("POST", "", entry)).response.status, 400);
  }
  equal(database.queries.length, 0);
});

Deno.test("R10 partial text update regenerates an embedding from complete merged text", async () => {
  const requests: Row[] = [];
  const vector = Array(1536).fill(0.1);
  const { database, call } = setup({
    API_SECRET: ordinary,
    OPENAI_API_KEY: "unit-test-provider-credential",
  }, {
    fetch: (_input, init) => {
      requests.push(JSON.parse(String(init?.body)));
      return Promise.resolve(Response.json({ data: [{ embedding: vector }] }));
    },
  });
  database.rows.memory_core = [{ ...coreRecord(), embedding: [0.9] }];
  const { response, payload } = await call("POST", "", {
    tier: "core",
    id: ID,
    title: "New title",
  });
  equal(response.status, 200);
  equal(payload.embedding_generated, true);
  equal(requests[0].input, "New title Original body");
  equal(database.rows.memory_core[0].embedding, vector);
});

for (const provider of ["disabled", "failed", "malformed"]) {
  Deno.test(`R10 text updates invalidate stale embedding when provider is ${provider}`, async () => {
    const { database, call } = setup({
      API_SECRET: ordinary,
      ...(provider === "disabled"
        ? {}
        : { OPENAI_API_KEY: "unit-test-provider-credential" }),
    }, {
      fetch: () =>
        Promise.resolve(
          provider === "failed"
            ? new Response("", { status: 503 })
            : Response.json({ data: [{ embedding: [0.1] }] }),
        ),
    });
    database.rows.memory_active = [{
      id: ID,
      title: "Before",
      content: "Old body",
      embedding: [0.9],
    }];
    equal(
      (await call("POST", "", { tier: "active", id: ID, content: "New body" }))
        .response.status,
      200,
    );
    equal(database.rows.memory_active[0].embedding, null);
  });
}

Deno.test("R10 improvement evidence-only update uses title, next step and model notes", async () => {
  let text = "";
  const { database, call } = setup({
    API_SECRET: ordinary,
    OPENAI_API_KEY: "unit-test-provider-credential",
  }, {
    fetch: (_input, init) => {
      text = JSON.parse(String(init?.body)).input;
      return Promise.resolve(
        Response.json({ data: [{ embedding: Array(1536).fill(0.1) }] }),
      );
    },
  });
  database.rows.memory_improvements = [{
    id: ID,
    title: "Workflow",
    evidence: "Old",
    next_step: "Next",
    model_version_notes: "Version",
  }];
  equal(
    (await call("POST", "", { tier: "improvements", id: ID, evidence: "New" }))
      .response.status,
    200,
  );
  equal(text, "Workflow New Next Version");
});

Deno.test("R10 metadata-only updates preserve embeddings without provider work", async () => {
  const { database, call } = setup();
  database.rows.memory_core = [{ ...coreRecord(), embedding: [0.9] }];
  equal(
    (await call("POST", "", { tier: "core", id: ID, tags: ["new"] })).response
      .status,
    200,
  );
  equal(database.rows.memory_core[0].embedding, [0.9]);
});

Deno.test("R13 resolve, repeated resolve, reopen and re-resolve maintain lifecycle timestamps", async () => {
  let time = NOW;
  const { database, call } = setup({ API_SECRET: ordinary }, {
    now: () => new Date(time),
  });
  database.rows.memory_active = [{
    id: ID,
    resolved: false,
    resolved_at: DATE,
  }];
  equal(
    (await call("POST", "", { tier: "active", id: ID, resolved: true }))
      .response.status,
    200,
  );
  equal(database.rows.memory_active[0].resolved_at, NOW);
  time = "2026-10-11T01:00:00.000Z";
  await call("DELETE", `?tier=active&id=${ID}`);
  equal(database.rows.memory_active[0].resolved_at, NOW);
  await call("POST", "", { tier: "active", id: ID, resolved: false });
  equal(database.rows.memory_active[0].resolved_at, null);
  await call("POST", "", { tier: "active", id: ID, resolved: true });
  equal(database.rows.memory_active[0].resolved_at, time);
});

Deno.test("R13 creating an already resolved active entry sets its timestamp", async () => {
  const { database, call } = setup();
  const { response } = await call("POST", "", {
    tier: "active",
    title: "Done",
    content: "Complete",
    category: "work_state",
    resolved: true,
  });
  equal(response.status, 200);
  equal(database.rows.memory_active[0].resolved_at, NOW);
});

Deno.test("R6/R7 restore preserves UUID, timestamps, null values and reports inserted status", async () => {
  const { database, call } = setup({ API_SECRET_RESTORE: restore });
  const record = {
    ...coreRecord(),
    project: null,
    tags: null,
    updated_at: null,
  };
  for (const inserted of [true, false]) {
    database.rpcResult = { data: { inserted, id: ID }, error: null };
    const { response, payload } = await call(
      "POST",
      "",
      { action: "restore", tier: "core", record },
      restore,
      "restore",
    );
    equal(response.status, 200);
    equal(payload.action, "restore");
    equal(payload.inserted, inserted);
    equal(payload.id, ID);
    equal(database.rpcCalls.at(-1), {
      name: "restore_memory_record",
      args: { p_tier: "core", p_record: record },
    });
  }
  equal(database.queries.length, 0);
});

Deno.test("restore accepts session and active historical lifecycle fields without ordinary POST normalization", async () => {
  const { database, call } = setup({ API_SECRET_RESTORE: restore });
  database.rpcResult = { data: { inserted: true, id: ID }, error: null };
  const activeRecord = {
    id: ID,
    title: "Done",
    content: "Historical",
    category: "work_state",
    resolved: true,
    resolved_at: DATE,
    tags: [null, "historical"],
    created_at: DATE,
    updated_at: DATE,
  };
  equal(
    (await call(
      "POST",
      "",
      { action: "restore", tier: "active", record: activeRecord },
      restore,
      "restore",
    )).response.status,
    200,
  );
  equal((database.rpcCalls.at(-1)?.args?.p_record as Row).resolved_at, DATE);
  const sessionRecord = {
    id: ID,
    session_id: "Original",
    summary: "Original",
    created_at: DATE,
  };
  equal(
    (await call(
      "POST",
      "",
      { action: "restore", tier: "sessions", record: sessionRecord },
      restore,
      "restore",
    )).response.status,
    200,
  );
});

Deno.test("restore validates field whitelist, timestamps, identity and RPC failure", async () => {
  const { database, call } = setup({ API_SECRET_RESTORE: restore });
  for (
    const record of [
      { ...coreRecord(), id: "not-uuid" },
      { ...coreRecord(), created_at: "yesterday" },
      { ...coreRecord(), embedding: [] },
      { ...coreRecord(), priority: "high" },
      { title: "A", content: "B", category: "context", id: ID },
    ]
  ) {
    equal(
      (await call(
        "POST",
        "",
        { action: "restore", tier: "core", record },
        restore,
        "restore",
      )).response.status,
      400,
    );
  }
  equal(database.rpcCalls.length, 0);
  database.rpcResult = { data: null, error: { code: "XX000" } };
  equal(
    (await call(
      "POST",
      "",
      { action: "restore", tier: "core", record: coreRecord() },
      restore,
      "restore",
    )).response.status,
    500,
  );
});

Deno.test("authentication denies missing config, missing bearer and incorrect credentials", async () => {
  equal((await setup({}).call()).response.status, 500);
  equal(
    (await setup().call("GET", "?action=backup", undefined, "wrong")).response
      .status,
    401,
  );
  const { handler, database } = setup();
  equal(
    (await handler(new Request("https://memory.test/?action=backup"))).status,
    401,
  );
  equal(database.rpcCalls.length, 0);
});

Deno.test("ordinary clients cannot invoke restore or impersonate the restore role with legacy fallback", async () => {
  const { database, call } = setup();
  const payload = { action: "restore", tier: "core", record: coreRecord() };
  equal((await call("POST", "", payload)).response.status, 403);
  equal(
    (await call("POST", "", payload, ordinary, "restore")).response.status,
    401,
  );
  equal(database.rpcCalls.length, 0);
});

Deno.test("backup key is read-only with or without its client header", async () => {
  const { database, call } = setup({ API_SECRET_BACKUP: backup });
  database.rpcResult = { data: snapshot(), error: null };
  for (const client of [undefined, "backup"]) {
    equal(
      (await call("GET", "?action=backup", undefined, backup, client)).response
        .status,
      200,
    );
    equal(
      (await call("DELETE", `?tier=core&id=${ID}`, undefined, backup, client))
        .response.status,
      403,
    );
    equal(
      (await call(
        "POST",
        "",
        { tier: "core", title: "A", content: "B", category: "context" },
        backup,
        client,
      )).response.status,
      403,
    );
  }
  equal(database.queries.length, 0);
});

Deno.test("restore key requires explicit header and permits only backup inspection and restore writes", async () => {
  const { database, call } = setup({ API_SECRET_RESTORE: restore });
  database.rpcResult = { data: snapshot(), error: null };
  equal(
    (await call("GET", "?action=backup", undefined, restore)).response.status,
    403,
  );
  equal(
    (await call("GET", "?action=backup&client=restore", undefined, restore))
      .response.status,
    403,
  );
  equal(
    (await call("GET", "?action=backup", undefined, restore, "restore"))
      .response.status,
    200,
  );
  equal(
    (await call("GET", "?tier=core", undefined, restore, "restore")).response
      .status,
    403,
  );
  equal(
    (await call("DELETE", `?tier=core&id=${ID}`, undefined, restore, "restore"))
      .response.status,
    403,
  );
  equal(
    (await call(
      "POST",
      "",
      { tier: "core", id: ID, title: "Changed" },
      restore,
      "restore",
    )).response.status,
    403,
  );
});

Deno.test("reusing a reserved credential for an ordinary role fails closed", async () => {
  for (
    const config of [{ API_SECRET_BACKUP: backup, API_SECRET: backup }, {
      API_SECRET_RESTORE: restore,
      API_SECRET_API: restore,
    }]
  ) {
    const { call, database } = setup(config);
    const token = config.API_SECRET_BACKUP || restore;
    equal(
      (await call("POST", "", { tier: "core", id: ID, title: "X" }, token))
        .response.status,
      500,
    );
    equal(database.queries.length, 0);
  }
});

Deno.test("ordinary named clients retain explicit-key precedence and documented legacy fallback", async () => {
  const { database, call } = setup({
    API_SECRET: ordinary,
    API_SECRET_API: "unit-test-specific-api",
  });
  database.rpcResult = { data: snapshot(), error: null };
  equal(
    (await call("GET", "?action=backup", undefined, ordinary, "cowork"))
      .response.status,
    200,
  );
  equal(
    (await call("GET", "?action=backup", undefined, ordinary, "api")).response
      .status,
    401,
  );
  equal(
    (await call(
      "GET",
      "?action=backup",
      undefined,
      "unit-test-specific-api",
      "api",
    )).response.status,
    200,
  );
});

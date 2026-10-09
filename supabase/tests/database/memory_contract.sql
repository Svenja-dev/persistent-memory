-- Ausfuehren nach allen Migrationen: psql -v ON_ERROR_STOP=1 -f memory_contract.sql
-- Nur synthetische Daten; alle Aenderungen werden zurueckgerollt.
BEGIN;

DO $$
DECLARE rpc regprocedure;
BEGIN
  FOREACH rpc IN ARRAY ARRAY[
    'public.search_memory(text,text)'::regprocedure,
    'public.search_memory_semantic(extensions.vector,double precision,integer,text)'::regprocedure,
    'public.search_memory_hybrid(text,extensions.vector,double precision,integer,text)'::regprocedure,
    'public.export_memory_backup()'::regprocedure,
    'public.restore_memory_record(text,jsonb)'::regprocedure
  ] LOOP
    IF has_function_privilege('anon', rpc, 'EXECUTE')
      OR has_function_privilege('authenticated', rpc, 'EXECUTE')
      OR NOT has_function_privilege('service_role', rpc, 'EXECUTE') THEN
      RAISE EXCEPTION 'Incorrect RPC privileges: %', rpc;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = rpc AND prosecdef
      AND proconfig @> ARRAY['search_path=""']) THEN
      RAISE EXCEPTION 'Unsafe search_path: %', rpc;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc p,
      LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
      WHERE p.oid = rpc AND a.grantee = 0 AND a.privilege_type = 'EXECUTE') THEN
      RAISE EXCEPTION 'PUBLIC still has EXECUTE: %', rpc;
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    RAISE EXCEPTION 'Fresh installation did not activate pg_cron';
  END IF;
  IF (SELECT count(*) FROM cron.job WHERE jobname IN ('cleanup-memory-sessions', 'cleanup-memory-active-resolved')) <> 2
    OR EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'log-memory-stats') THEN
    RAISE EXCEPTION 'Unexpected cleanup jobs';
  END IF;
END;
$$;

-- Nicht nur ACL-Metadaten: echte Aufrufe unter beiden unberechtigten Rollen.
SET LOCAL ROLE anon;
DO $$
DECLARE command text;
BEGIN
  FOREACH command IN ARRAY ARRAY[
    'SELECT * FROM public.search_memory(''test'')',
    'SELECT * FROM public.search_memory_semantic(NULL)',
    'SELECT * FROM public.search_memory_hybrid(''test'')',
    'SELECT public.export_memory_backup()',
    'SELECT public.restore_memory_record(''core'', ''{}''::jsonb)'
  ] LOOP
    BEGIN
      EXECUTE command;
      RAISE EXCEPTION 'Anonymous RPC call unexpectedly succeeded: %', command;
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
  END LOOP;
END;
$$;
RESET ROLE;
SET LOCAL ROLE authenticated;
DO $$
DECLARE command text;
BEGIN
  FOREACH command IN ARRAY ARRAY[
    'SELECT * FROM public.search_memory(''test'')',
    'SELECT * FROM public.search_memory_semantic(NULL)',
    'SELECT * FROM public.search_memory_hybrid(''test'')',
    'SELECT public.export_memory_backup()',
    'SELECT public.restore_memory_record(''core'', ''{}''::jsonb)'
  ] LOOP
    BEGIN
      EXECUTE command;
      RAISE EXCEPTION 'Authenticated RPC call unexpectedly succeeded: %', command;
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
  END LOOP;
END;
$$;
RESET ROLE;

-- Alle zusaetzlichen API-Kategorien muessen auf einer frischen DB funktionieren.
INSERT INTO public.memory_core (project, category, title, content)
SELECT '__memory_contract__', category, category, 'synthetic category fixture'
FROM unnest(ARRAY['user_profile','user_values','work_style','communication','pain_points','workflow_preference']) category;

INSERT INTO public.memory_core (project, category, title, content)
SELECT '__memory_contract__', 'context', 'core ' || n, 'synthetic' FROM generate_series(1, 1101) n;
INSERT INTO public.memory_active (project, category, title, content)
SELECT '__memory_contract__', 'work_state', 'active ' || n, 'synthetic' FROM generate_series(1, 1101) n;
INSERT INTO public.memory_improvements (project, category, title)
SELECT '__memory_contract__', 'workflow', 'improvement ' || n FROM generate_series(1, 1101) n;
INSERT INTO public.memory_sessions (project, session_id, summary)
SELECT '__memory_contract__', 'session ' || n, 'synthetic' FROM generate_series(1, 151) n;

INSERT INTO public.memory_improvements (id, project, category, title, evidence, next_step,
  model_version_notes, status, introduced_at, last_used_at, use_count, created_at, updated_at, embedding)
VALUES ('aaaaaaaa-0000-4000-8000-000000000001', 'global', 'workflow', 'search fixture',
  '__memory_contract_search__', 'synthetic next step', 'synthetic model note', 'proven', '2026-01-01',
  '2026-01-04T12:00:00Z', 4, '2026-01-01T12:00:00Z', '2026-01-03T12:00:00Z',
  array_fill(1::real, ARRAY[1536])::extensions.vector),
  ('aaaaaaaa-0000-4000-8000-000000000002', 'global', 'workflow', 'retired search fixture',
  '__memory_contract_search__', NULL, NULL, 'retired', NULL, NULL, 0, now(), now(),
  array_fill(1::real, ARRAY[1536])::extensions.vector);
INSERT INTO public.memory_core (id, project, category, title, content, created_at, updated_at, embedding)
VALUES ('aaaaaaaa-0000-4000-8000-000000000003', '__memory_contract__', 'context', 'restore fixture',
  'unchanged core content', '2026-01-01T12:00:00Z', '2026-01-03T12:00:00Z',
  array_fill(1::real, ARRAY[1536])::extensions.vector);
INSERT INTO public.memory_active (id, project, category, title, content, resolved, resolved_at, created_at, updated_at)
VALUES ('aaaaaaaa-0000-4000-8000-000000000004', '__memory_contract__', 'work_state', 'restore fixture',
  'resolved active content', true, '2026-01-02T12:00:00Z', '2026-01-01T12:00:00Z', '2026-01-03T12:00:00Z');
INSERT INTO public.memory_sessions (id, project, session_id, summary, decisions_made, created_at)
VALUES ('aaaaaaaa-0000-4000-8000-000000000005', '__memory_contract__', 'restore fixture',
  'session summary', ARRAY['synthetic decision'], '2026-01-01T12:00:00Z');

SET LOCAL ROLE service_role;
DO $$
DECLARE snapshot jsonb; tier text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.search_memory('__memory_contract_search__', 'another_project')
    WHERE source = 'improvements' AND id = 'aaaaaaaa-0000-4000-8000-000000000001'
      AND content LIKE '%synthetic next step%' AND content LIKE '%synthetic model note%') THEN
    RAISE EXCEPTION 'Text search omitted global improvement or content fields';
  END IF;
  IF EXISTS (SELECT 1 FROM public.search_memory('__memory_contract_search__')
    WHERE id = 'aaaaaaaa-0000-4000-8000-000000000002') THEN
    RAISE EXCEPTION 'Text search included retired improvement';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.search_memory_semantic(array_fill(1::real, ARRAY[1536])::extensions.vector,
    0.99, 10, 'another_project') WHERE source = 'improvements' AND id = 'aaaaaaaa-0000-4000-8000-000000000001') THEN
    RAISE EXCEPTION 'Semantic search omitted global improvement';
  END IF;
  IF (SELECT count(*) FROM public.search_memory_hybrid('__memory_contract_search__',
    array_fill(1::real, ARRAY[1536])::extensions.vector, 0.99, 20, 'another_project')
    WHERE id = 'aaaaaaaa-0000-4000-8000-000000000001') <> 1 THEN
    RAISE EXCEPTION 'Hybrid search duplicated or omitted improvement';
  END IF;
  snapshot := public.export_memory_backup();
  IF snapshot ->> 'schema_version' <> '1' OR snapshot ->> 'complete' <> 'true'
    OR snapshot ->> 'exported_at' IS NULL THEN
    RAISE EXCEPTION 'Invalid snapshot envelope';
  END IF;
  FOREACH tier IN ARRAY ARRAY['core', 'active', 'sessions', 'improvements'] LOOP
    IF jsonb_array_length(snapshot -> tier -> 'data') <> (snapshot -> tier ->> 'count')::int
      OR (snapshot -> tier ->> 'count')::int < CASE WHEN tier = 'sessions' THEN 152 ELSE 1101 END THEN
      RAISE EXCEPTION 'Truncated snapshot for %', tier;
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(snapshot -> tier -> 'data') item WHERE item ? 'embedding') THEN
      RAISE EXCEPTION 'Snapshot contains derived embeddings for %', tier;
    END IF;
  END LOOP;
END;
$$;
RESET ROLE;

DO $$
DECLARE snapshot jsonb; tier text; actual_count bigint;
BEGIN
  snapshot := public.export_memory_backup();
  FOREACH tier IN ARRAY ARRAY['core', 'active', 'sessions', 'improvements'] LOOP
    EXECUTE format('SELECT count(*) FROM public.%I', 'memory_' || tier) INTO actual_count;
    IF (snapshot -> tier ->> 'count')::bigint <> actual_count THEN
      RAISE EXCEPTION 'Snapshot did not include every row for %', tier;
    END IF;
  END LOOP;
END;
$$;

CREATE TEMP TABLE contract_restore_originals (tier text, original jsonb);
INSERT INTO contract_restore_originals
SELECT 'core', to_jsonb(m) - 'embedding' FROM public.memory_core m WHERE id = 'aaaaaaaa-0000-4000-8000-000000000003'
UNION ALL SELECT 'active', to_jsonb(m) - 'embedding' FROM public.memory_active m WHERE id = 'aaaaaaaa-0000-4000-8000-000000000004'
UNION ALL SELECT 'sessions', to_jsonb(m) FROM public.memory_sessions m WHERE id = 'aaaaaaaa-0000-4000-8000-000000000005'
UNION ALL SELECT 'improvements', to_jsonb(m) - 'embedding' FROM public.memory_improvements m WHERE id = 'aaaaaaaa-0000-4000-8000-000000000001';
GRANT SELECT ON contract_restore_originals TO service_role;
DELETE FROM public.memory_core WHERE id = 'aaaaaaaa-0000-4000-8000-000000000003';
DELETE FROM public.memory_active WHERE id = 'aaaaaaaa-0000-4000-8000-000000000004';
DELETE FROM public.memory_sessions WHERE id = 'aaaaaaaa-0000-4000-8000-000000000005';
DELETE FROM public.memory_improvements WHERE id = 'aaaaaaaa-0000-4000-8000-000000000001';

SET LOCAL ROLE service_role;
DO $$
DECLARE fixture record; result jsonb; snapshot jsonb; saved jsonb;
BEGIN
  FOR fixture IN SELECT * FROM contract_restore_originals LOOP
    result := public.restore_memory_record(fixture.tier, fixture.original);
    IF result ->> 'inserted' <> 'true' OR result ->> 'id' <> fixture.original ->> 'id' THEN
      RAISE EXCEPTION 'Initial restore failed for %', fixture.tier;
    END IF;
    result := public.restore_memory_record(fixture.tier, fixture.original);
    IF result ->> 'inserted' <> 'false' THEN
      RAISE EXCEPTION 'Repeated restore duplicated %', fixture.tier;
    END IF;
    -- Selbst ein abweichender Inhalt darf dieselbe UUID nicht ueberschreiben.
    result := public.restore_memory_record(fixture.tier, fixture.original ||
      CASE WHEN fixture.tier = 'sessions' THEN '{"summary":"overwrite attempt"}'::jsonb
        ELSE '{"title":"overwrite attempt"}'::jsonb END);
    snapshot := public.export_memory_backup();
    SELECT item INTO saved FROM jsonb_array_elements(snapshot -> fixture.tier -> 'data') item
      WHERE item ->> 'id' = fixture.original ->> 'id';
    IF saved IS DISTINCT FROM fixture.original THEN
      RAISE EXCEPTION 'Restore changed fields, timestamps or lifecycle for %', fixture.tier;
    END IF;
    BEGIN
      PERFORM public.restore_memory_record(fixture.tier, fixture.original || '{"embedding":null}'::jsonb);
      RAISE EXCEPTION 'Restore accepted unexpected field';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
      PERFORM public.restore_memory_record(fixture.tier, fixture.original - 'created_at');
      RAISE EXCEPTION 'Restore accepted missing creation time';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
      PERFORM public.restore_memory_record(fixture.tier, fixture.original || '{"tags":[123]}'::jsonb);
      RAISE EXCEPTION 'Restore accepted incorrect array item type';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
  END LOOP;
END;
$$;
RESET ROLE;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.memory_core WHERE id = 'aaaaaaaa-0000-4000-8000-000000000003' AND embedding IS NOT NULL)
    OR EXISTS (SELECT 1 FROM public.memory_improvements WHERE id = 'aaaaaaaa-0000-4000-8000-000000000001' AND embedding IS NOT NULL) THEN
    RAISE EXCEPTION 'Restore retained stale embeddings';
  END IF;
END;
$$;

ROLLBACK;

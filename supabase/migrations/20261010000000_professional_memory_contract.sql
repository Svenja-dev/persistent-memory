-- Zugriffsschutz, vollstaendige Sicherungen und konsistenter Suchvertrag.
-- Migration: 20261010000000_professional_memory_contract.sql
-- Upgrade: zuerst diese Migration, danach die dazugehoerige Edge Function.
-- Frische Installationen durchlaufen alle Migrationen in Zeitreihenfolge.

ALTER TABLE public.memory_core DROP CONSTRAINT memory_core_category_check;
ALTER TABLE public.memory_core ADD CONSTRAINT memory_core_category_check CHECK (
  category IN ('preference', 'architecture', 'pattern', 'context', 'tool_config',
    'decision', 'user_profile', 'user_values', 'work_style', 'communication',
    'pain_points', 'workflow_preference')
);

-- Alte Installationen koennen noch den Job mit der fremden cron_logs-Tabelle haben.
DO $$
DECLARE stale_job bigint;
BEGIN
  FOR stale_job IN SELECT jobid FROM cron.job WHERE jobname = 'log-memory-stats'
  LOOP
    PERFORM cron.unschedule(stale_job);
  END LOOP;
END;
$$;

-- Die Jobnamen ersetzen vorhandene Definitionen, ohne doppelte Jobs anzulegen.
SELECT cron.schedule('cleanup-memory-sessions', '0 3 * * *',
  $$DELETE FROM public.memory_sessions WHERE created_at < NOW() - INTERVAL '90 days'$$);
SELECT cron.schedule('cleanup-memory-active-resolved', '5 3 * * *',
  $$DELETE FROM public.memory_active WHERE resolved = TRUE AND resolved_at < NOW() - INTERVAL '30 days'$$);

CREATE OR REPLACE FUNCTION public.search_memory(search_term text, filter_project text DEFAULT NULL)
RETURNS TABLE (
  source text, id uuid, project text, category text, title text,
  content text, tags text[], created_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT 'core'::text AS source, m.id, m.project, m.category, m.title, m.content, m.tags, m.created_at
  FROM public.memory_core m
  WHERE (m.title ILIKE '%' || search_term || '%' OR m.content ILIKE '%' || search_term || '%')
    AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
  UNION ALL
  SELECT 'active'::text, m.id, m.project, m.category, m.title, m.content, m.tags, m.created_at
  FROM public.memory_active m
  WHERE (m.title ILIKE '%' || search_term || '%' OR m.content ILIKE '%' || search_term || '%')
    AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
    AND m.resolved = FALSE
  UNION ALL
  SELECT 'session'::text, m.id, m.project, 'session'::text, m.session_id, m.summary, m.tags, m.created_at
  FROM public.memory_sessions m
  WHERE m.summary ILIKE '%' || search_term || '%'
    AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
  UNION ALL
  SELECT 'improvements'::text, m.id, m.project, m.category, m.title,
    concat_ws(E'\n', m.evidence, m.next_step, m.model_version_notes), m.tags, m.created_at
  FROM public.memory_improvements m
  WHERE concat_ws(E'\n', m.title, m.category, m.status, m.evidence, m.next_step, m.model_version_notes)
    ILIKE '%' || search_term || '%'
    AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
    AND m.status <> 'retired'
  ORDER BY created_at DESC, source, id
  LIMIT 50;
$$;

CREATE OR REPLACE FUNCTION public.search_memory_semantic(
  query_embedding extensions.vector(1536), match_threshold float DEFAULT 0.5,
  match_count int DEFAULT 10, filter_project text DEFAULT NULL
)
RETURNS TABLE (
  source text, id uuid, project text, category text, title text, content text,
  tags text[], similarity float, created_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT * FROM (
    SELECT 'core'::text AS source, m.id, m.project, m.category, m.title, m.content, m.tags,
      1 - (m.embedding OPERATOR(extensions.<=>) query_embedding) AS similarity, m.created_at
    FROM public.memory_core m
    WHERE m.embedding IS NOT NULL
      AND 1 - (m.embedding OPERATOR(extensions.<=>) query_embedding) > match_threshold
      AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
    UNION ALL
    SELECT 'active'::text, m.id, m.project, m.category, m.title, m.content, m.tags,
      1 - (m.embedding OPERATOR(extensions.<=>) query_embedding), m.created_at
    FROM public.memory_active m
    WHERE m.embedding IS NOT NULL AND m.resolved = FALSE
      AND 1 - (m.embedding OPERATOR(extensions.<=>) query_embedding) > match_threshold
      AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
    UNION ALL
    SELECT 'improvements'::text, m.id, m.project, m.category, m.title,
      concat_ws(E'\n', m.evidence, m.next_step, m.model_version_notes), m.tags,
      1 - (m.embedding OPERATOR(extensions.<=>) query_embedding), m.created_at
    FROM public.memory_improvements m
    WHERE m.embedding IS NOT NULL AND m.status <> 'retired'
      AND 1 - (m.embedding OPERATOR(extensions.<=>) query_embedding) > match_threshold
      AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
  ) combined
  ORDER BY similarity DESC, source, id
  LIMIT greatest(0, least(coalesce(match_count, 10), 100));
$$;

CREATE OR REPLACE FUNCTION public.search_memory_hybrid(
  search_term text, query_embedding extensions.vector(1536) DEFAULT NULL,
  match_threshold float DEFAULT 0.5, match_count int DEFAULT 20, filter_project text DEFAULT NULL
)
RETURNS TABLE (
  source text, id uuid, project text, category text, title text, content text,
  tags text[], similarity float, search_type text, created_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH semantic AS MATERIALIZED (
    SELECT * FROM public.search_memory_semantic(query_embedding, match_threshold, match_count, filter_project)
    WHERE query_embedding IS NOT NULL
  )
  SELECT * FROM (
    SELECT s.source, s.id, s.project, s.category, s.title, s.content, s.tags,
      s.similarity, 'semantic'::text AS search_type, s.created_at
    FROM semantic s
    UNION ALL
    SELECT t.source, t.id, t.project, t.category, t.title, t.content, t.tags,
      0.0::float, 'text'::text, t.created_at
    FROM public.search_memory(search_term, filter_project) t
    WHERE search_term IS NOT NULL AND search_term <> ''
      AND NOT EXISTS (SELECT 1 FROM semantic s WHERE s.id = t.id AND s.source = t.source)
  ) combined
  ORDER BY similarity DESC, created_at DESC, source, id
  LIMIT greatest(0, least(coalesce(match_count, 20), 100));
$$;

-- Ein einzelner skalarer JSON-Wert umgeht PostgREST-Zeilenlimits. Alle vier
-- Aggregate sehen denselben SQL-Snapshot; leere Tabellen bleiben explizit leer.
-- Embeddings sind abgeleitete Daten und werden bewusst nicht gesichert.
CREATE OR REPLACE FUNCTION public.export_memory_backup()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT jsonb_build_object(
    'schema_version', 1, 'complete', true, 'exported_at', statement_timestamp(),
    'core', (SELECT jsonb_build_object('count', count(*),
      'data', coalesce(jsonb_agg(to_jsonb(m) - 'embedding' ORDER BY m.id), '[]'::jsonb))
      FROM public.memory_core m),
    'active', (SELECT jsonb_build_object('count', count(*),
      'data', coalesce(jsonb_agg(to_jsonb(m) - 'embedding' ORDER BY m.id), '[]'::jsonb))
      FROM public.memory_active m),
    'sessions', (SELECT jsonb_build_object('count', count(*),
      'data', coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.id), '[]'::jsonb))
      FROM public.memory_sessions m),
    'improvements', (SELECT jsonb_build_object('count', count(*),
      'data', coalesce(jsonb_agg(to_jsonb(m) - 'embedding' ORDER BY m.id), '[]'::jsonb))
      FROM public.memory_improvements m)
  );
$$;

-- Restore ist nur fuer den Server verfuegbar. Bestehende IDs werden niemals
-- ueberschrieben, auch nicht nach Teilfehlern oder bei parallelen Wiederholungen.
CREATE OR REPLACE FUNCTION public.restore_memory_record(p_tier text, p_record jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  allowed_fields text[];
  item record;
  inserted_id uuid;
  record_id uuid;
  core_row public.memory_core%ROWTYPE;
  active_row public.memory_active%ROWTYPE;
  session_row public.memory_sessions%ROWTYPE;
  improvement_row public.memory_improvements%ROWTYPE;
BEGIN
  IF p_tier IS NULL OR p_tier NOT IN ('core', 'active', 'sessions', 'improvements')
    OR p_record IS NULL OR jsonb_typeof(p_record) <> 'object' THEN
    RAISE EXCEPTION 'Invalid restore tier or record' USING ERRCODE = '22023';
  END IF;
  allowed_fields := ARRAY['id', 'project', 'tags', 'created_at'];
  CASE p_tier
    WHEN 'core' THEN
      allowed_fields := allowed_fields || ARRAY['category', 'title', 'content', 'importance', 'updated_at'];
    WHEN 'active' THEN
      allowed_fields := allowed_fields || ARRAY['category', 'title', 'content', 'priority', 'resolved', 'resolved_at', 'updated_at'];
    WHEN 'sessions' THEN
      allowed_fields := allowed_fields || ARRAY['session_id', 'tool', 'summary', 'decisions_made', 'issues_encountered', 'files_changed'];
    WHEN 'improvements' THEN
      allowed_fields := allowed_fields || ARRAY['title', 'category', 'status', 'introduced_at', 'evidence', 'next_step',
        'related_files', 'model_version_notes', 'last_used_at', 'use_count', 'updated_at'];
  END CASE;
  IF NOT (p_record ?& ARRAY['id', 'created_at'])
    OR (p_tier <> 'sessions' AND NOT (p_record ? 'updated_at'))
    OR jsonb_typeof(p_record -> 'id') <> 'string' THEN
    RAISE EXCEPTION 'Restore requires original id and timestamp fields' USING ERRCODE = '22023';
  END IF;
  FOR item IN SELECT key, value FROM jsonb_each(p_record)
  LOOP
    IF NOT (item.key = ANY(allowed_fields)) THEN
      RAISE EXCEPTION 'Unexpected restore field: %', item.key USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(item.value) = 'null' THEN CONTINUE; END IF;
    IF item.key IN ('tags', 'decisions_made', 'issues_encountered', 'files_changed', 'related_files') THEN
      IF jsonb_typeof(item.value) <> 'array' THEN
        RAISE EXCEPTION 'Restore field % must be an array', item.key USING ERRCODE = '22023';
      END IF;
      IF EXISTS (SELECT 1 FROM jsonb_array_elements(item.value) v WHERE jsonb_typeof(v) NOT IN ('string', 'null')) THEN
        RAISE EXCEPTION 'Restore array % must contain strings', item.key USING ERRCODE = '22023';
      END IF;
    ELSIF item.key = 'resolved' THEN
      IF jsonb_typeof(item.value) <> 'boolean' THEN
        RAISE EXCEPTION 'Restore resolved must be boolean' USING ERRCODE = '22023';
      END IF;
    ELSIF item.key = 'use_count' THEN
      IF jsonb_typeof(item.value) <> 'number' OR item.value::text !~ '^[0-9]+$' THEN
        RAISE EXCEPTION 'Restore use_count must be a nonnegative integer' USING ERRCODE = '22023';
      END IF;
    ELSIF jsonb_typeof(item.value) <> 'string' THEN
      RAISE EXCEPTION 'Restore field % must be a string', item.key USING ERRCODE = '22023';
    END IF;
  END LOOP;

  record_id := (p_record ->> 'id')::uuid;
  CASE p_tier
    WHEN 'core' THEN
      core_row := jsonb_populate_record(NULL::public.memory_core, p_record);
      INSERT INTO public.memory_core (id, project, category, title, content, tags, importance, created_at, updated_at)
      VALUES (core_row.id, core_row.project, core_row.category, core_row.title, core_row.content,
        core_row.tags, core_row.importance, core_row.created_at, core_row.updated_at)
      ON CONFLICT (id) DO NOTHING RETURNING id INTO inserted_id;
    WHEN 'active' THEN
      active_row := jsonb_populate_record(NULL::public.memory_active, p_record);
      INSERT INTO public.memory_active (id, project, category, title, content, tags, priority, resolved, resolved_at, created_at, updated_at)
      VALUES (active_row.id, active_row.project, active_row.category, active_row.title, active_row.content,
        active_row.tags, active_row.priority, active_row.resolved, active_row.resolved_at, active_row.created_at, active_row.updated_at)
      ON CONFLICT (id) DO NOTHING RETURNING id INTO inserted_id;
    WHEN 'sessions' THEN
      session_row := jsonb_populate_record(NULL::public.memory_sessions, p_record);
      INSERT INTO public.memory_sessions (id, session_id, project, tool, summary, decisions_made, issues_encountered, files_changed, tags, created_at)
      VALUES (session_row.id, session_row.session_id, session_row.project, session_row.tool, session_row.summary,
        session_row.decisions_made, session_row.issues_encountered, session_row.files_changed, session_row.tags, session_row.created_at)
      ON CONFLICT (id) DO NOTHING RETURNING id INTO inserted_id;
    WHEN 'improvements' THEN
      improvement_row := jsonb_populate_record(NULL::public.memory_improvements, p_record);
      INSERT INTO public.memory_improvements (id, project, title, category, status, introduced_at, evidence, next_step,
        related_files, model_version_notes, tags, last_used_at, use_count, created_at, updated_at)
      VALUES (improvement_row.id, improvement_row.project, improvement_row.title, improvement_row.category, improvement_row.status,
        improvement_row.introduced_at, improvement_row.evidence, improvement_row.next_step, improvement_row.related_files,
        improvement_row.model_version_notes, improvement_row.tags, improvement_row.last_used_at,
        improvement_row.use_count, improvement_row.created_at, improvement_row.updated_at)
      ON CONFLICT (id) DO NOTHING RETURNING id INTO inserted_id;
  END CASE;
  RETURN jsonb_build_object('inserted', inserted_id IS NOT NULL, 'id', record_id);
END;
$$;

-- RLS allein schuetzt keine SECURITY-DEFINER-RPCs. Supabase-Clients duerfen
-- ausschliesslich ueber die authentifizierende Edge Function zugreifen.
REVOKE ALL ON FUNCTION public.search_memory(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.search_memory_semantic(extensions.vector, float, int, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.search_memory_hybrid(text, extensions.vector, float, int, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.export_memory_backup() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restore_memory_record(text, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.search_memory(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_memory_semantic(extensions.vector, float, int, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_memory_hybrid(text, extensions.vector, float, int, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.export_memory_backup() TO service_role;
GRANT EXECUTE ON FUNCTION public.restore_memory_record(text, jsonb) TO service_role;

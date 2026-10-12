-- Suchfunktionen: projektuebergreifende Eintraege in gefilterten Suchen
-- Migration: 20260909000000_search_include_global.sql
-- Eintraege mit project NULL, 'global' oder 'shared' sind projektuebergreifend und
-- werden auch bei gesetztem filter_project gefunden (gleiches Verhalten wie load_session).
-- Typen und Tabellen sind vollqualifiziert, damit die Migration auch ohne
-- 'extensions' im search_path installierbar ist. Die Folgemigration
-- 20261010000000_professional_memory_contract.sql ersetzt beide Funktionen erneut.

CREATE OR REPLACE FUNCTION public.search_memory(search_term text, filter_project text DEFAULT NULL)
RETURNS TABLE (
  source text,
  id uuid,
  project text,
  category text,
  title text,
  content text,
  tags text[],
  created_at timestamptz
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
  ORDER BY created_at DESC
  LIMIT 50;
$$;

CREATE OR REPLACE FUNCTION public.search_memory_semantic(
  query_embedding extensions.vector(1536),
  match_threshold float DEFAULT 0.5,
  match_count int DEFAULT 10,
  filter_project text DEFAULT NULL
)
RETURNS TABLE (
  source text,
  id uuid,
  project text,
  category text,
  title text,
  content text,
  tags text[],
  similarity float,
  created_at timestamptz
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
    WHERE m.embedding IS NOT NULL
      AND m.resolved = FALSE
      AND 1 - (m.embedding OPERATOR(extensions.<=>) query_embedding) > match_threshold
      AND (filter_project IS NULL OR m.project = filter_project OR m.project IS NULL OR m.project IN ('global', 'shared'))
  ) combined
  ORDER BY similarity DESC
  LIMIT match_count;
$$;

-- SECURITY-DEFINER-RPCs duerfen nur ueber die authentifizierende Edge Function laufen.
-- Ohne diesen Entzug koennten anon/authenticated die Suche direkt per PostgREST aufrufen.
REVOKE ALL ON FUNCTION public.search_memory(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.search_memory_semantic(extensions.vector, float, int, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.search_memory_hybrid(text, extensions.vector, float, int, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.search_memory(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_memory_semantic(extensions.vector, float, int, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_memory_hybrid(text, extensions.vector, float, int, text) TO service_role;

-- Suchfunktionen: Eintraege mit project NULL, 'global' oder 'shared' sind projektuebergreifend
-- und werden auch bei gesetztem filter_project gefunden (gleiches Verhalten wie load_session).

CREATE OR REPLACE FUNCTION search_memory(search_term TEXT, filter_project TEXT DEFAULT NULL)
RETURNS TABLE (
  source TEXT,
  id UUID,
  project TEXT,
  category TEXT,
  title TEXT,
  content TEXT,
  tags TEXT[],
  created_at TIMESTAMPTZ
) AS $$
BEGIN
  RETURN QUERY
  SELECT 'core'::TEXT, mc.id, mc.project, mc.category, mc.title, mc.content, mc.tags, mc.created_at
  FROM memory_core mc
  WHERE (mc.title ILIKE '%' || search_term || '%' OR mc.content ILIKE '%' || search_term || '%')
    AND (filter_project IS NULL OR mc.project = filter_project OR mc.project IS NULL OR mc.project IN ('global', 'shared'))
  UNION ALL
  SELECT 'active'::TEXT, ma.id, ma.project, ma.category, ma.title, ma.content, ma.tags, ma.created_at
  FROM memory_active ma
  WHERE (ma.title ILIKE '%' || search_term || '%' OR ma.content ILIKE '%' || search_term || '%')
    AND (filter_project IS NULL OR ma.project = filter_project OR ma.project IS NULL OR ma.project IN ('global', 'shared'))
    AND ma.resolved = FALSE
  UNION ALL
  SELECT 'session'::TEXT, ms.id, ms.project, 'session'::TEXT, ms.session_id, ms.summary, ms.tags, ms.created_at
  FROM memory_sessions ms
  WHERE (ms.summary ILIKE '%' || search_term || '%')
    AND (filter_project IS NULL OR ms.project = filter_project OR ms.project IS NULL OR ms.project IN ('global', 'shared'))
  ORDER BY created_at DESC
  LIMIT 50;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION search_memory_semantic(
  query_embedding vector(1536),
  match_threshold FLOAT DEFAULT 0.5,
  match_count INT DEFAULT 10,
  filter_project TEXT DEFAULT NULL
)
RETURNS TABLE (
  source TEXT,
  id UUID,
  project TEXT,
  category TEXT,
  title TEXT,
  content TEXT,
  tags TEXT[],
  similarity FLOAT,
  created_at TIMESTAMPTZ
) AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM (
    SELECT
      'core'::TEXT AS source,
      mc.id,
      mc.project,
      mc.category,
      mc.title,
      mc.content,
      mc.tags,
      1 - (mc.embedding <=> query_embedding) AS similarity,
      mc.created_at
    FROM memory_core mc
    WHERE mc.embedding IS NOT NULL
      AND 1 - (mc.embedding <=> query_embedding) > match_threshold
      AND (filter_project IS NULL OR mc.project = filter_project OR mc.project IS NULL OR mc.project IN ('global', 'shared'))

    UNION ALL

    SELECT
      'active'::TEXT AS source,
      ma.id,
      ma.project,
      ma.category,
      ma.title,
      ma.content,
      ma.tags,
      1 - (ma.embedding <=> query_embedding) AS similarity,
      ma.created_at
    FROM memory_active ma
    WHERE ma.embedding IS NOT NULL
      AND ma.resolved = FALSE
      AND 1 - (ma.embedding <=> query_embedding) > match_threshold
      AND (filter_project IS NULL OR ma.project = filter_project OR ma.project IS NULL OR ma.project IN ('global', 'shared'))
  ) combined
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

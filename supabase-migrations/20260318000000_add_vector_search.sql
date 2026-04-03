-- Vector Search Erweiterung fuer Memory System
-- Migration: 20260318000000_add_vector_search.sql
-- Fuegt semantische Suche via pgvector hinzu (zusaetzlich zu bestehender ILIKE-Suche)
--
-- Voraussetzung: Supabase-Projekt mit pgvector-Support
-- (Extension wird automatisch per CREATE EXTENSION aktiviert)
--
-- Kosten: ~$0.0001 pro Embedding (text-embedding-3-small via OpenAI)
-- Bei 50 Eintraegen/Tag = ~$0.15/Monat

-- =============================================================================
-- 1. pgvector Extension aktivieren + search_path setzen
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- search_path muss extensions enthalten, damit der Typ "vector" gefunden wird
SET search_path = public, extensions;

-- =============================================================================
-- 2. Embedding-Spalte zu memory_core und memory_active hinzufuegen
-- memory_sessions bekommt kein Embedding (kurzlebig, nicht lohnend)
-- =============================================================================
ALTER TABLE memory_core
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

ALTER TABLE memory_active
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- =============================================================================
-- 3. Indexes fuer schnelle Vector-Suche (IVFFlat, guter Kompromiss)
-- Bei < 10.000 Eintraegen reicht auch sequentiell, aber Index schadet nicht
--
-- HINWEIS: IVFFlat-Index auf leerer Tabelle ist ineffektiv.
-- Nach dem Backfill: REINDEX INDEX idx_memory_core_embedding;
-- Nach dem Backfill: REINDEX INDEX idx_memory_active_embedding;
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_memory_core_embedding
  ON memory_core USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

CREATE INDEX IF NOT EXISTS idx_memory_active_embedding
  ON memory_active USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

-- =============================================================================
-- 4. Semantische Suchfunktion (ersetzt NICHT die bestehende search_memory)
-- =============================================================================
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
    -- Suche in memory_core
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
      AND (filter_project IS NULL OR mc.project = filter_project)

    UNION ALL

    -- Suche in memory_active (nur nicht-aufgeloeste)
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
      AND (filter_project IS NULL OR ma.project = filter_project)
  ) combined
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- 5. Hybride Suche: Erst semantisch, dann ILIKE als Fallback
-- Nutzt Vector Search wenn Embedding vorhanden, sonst bestehende Textsuche
-- Ergebnis ist auf match_count begrenzt (semantisch priorisiert, Text fuellt auf)
-- =============================================================================
CREATE OR REPLACE FUNCTION search_memory_hybrid(
  search_term TEXT,
  query_embedding vector(1536) DEFAULT NULL,
  match_threshold FLOAT DEFAULT 0.5,
  match_count INT DEFAULT 20,
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
  search_type TEXT,
  created_at TIMESTAMPTZ
) AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM (
    -- Semantische Ergebnisse zuerst (hoehere Prioritaet)
    SELECT
      s.source, s.id, s.project, s.category, s.title, s.content, s.tags,
      s.similarity, 'semantic'::TEXT AS search_type, s.created_at
    FROM search_memory_semantic(query_embedding, match_threshold, match_count, filter_project) s
    WHERE query_embedding IS NOT NULL

    UNION ALL

    -- Text-Ergebnisse, Duplikate aus semantischer Suche ausgeschlossen
    SELECT
      sm.source, sm.id, sm.project, sm.category, sm.title, sm.content, sm.tags,
      0.0::FLOAT AS similarity, 'text'::TEXT AS search_type, sm.created_at
    FROM search_memory(search_term, filter_project) sm
    WHERE search_term IS NOT NULL AND search_term != ''
      AND NOT EXISTS (
        SELECT 1 FROM search_memory_semantic(
          query_embedding, match_threshold, match_count, filter_project
        ) ss WHERE ss.id = sm.id AND query_embedding IS NOT NULL
      )
  ) combined
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- HINWEIS: Embeddings werden NICHT automatisch erzeugt.
-- Die Edge Function (memory-manager) muss beim Schreiben optional ein
-- Embedding generieren. Das passiert nur wenn OPENAI_API_KEY gesetzt ist.
-- Bestehende Eintraege ohne Embedding funktionieren weiterhin ueber ILIKE.
-- =============================================================================

-- Backfill-Query fuer spaeter (manuell ausfuehren wenn gewuenscht):
-- Eintraege ohne Embedding finden:
-- SELECT id, title, LEFT(content, 100) FROM memory_core WHERE embedding IS NULL;
-- SELECT id, title, LEFT(content, 100) FROM memory_active WHERE embedding IS NULL AND resolved = FALSE;

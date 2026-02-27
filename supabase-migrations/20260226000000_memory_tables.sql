-- Memory System for Cross-Session Persistence
-- Migration: 20260226000000_memory_tables.sql
-- Three-tier memory: core (long-term), active (medium-term), sessions (short-term)

-- =============================================================================
-- TIER 1: memory_core - Langlebig, selten geaendert
-- Praeferenzen, Architektur-Entscheidungen, gelernte Patterns, Projekt-Kontexte
-- =============================================================================
CREATE TABLE memory_core (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project TEXT,                          -- nullable: NULL = projektuebergreifend
  category TEXT NOT NULL CHECK (category IN (
    'preference',       -- Nutzer-Praeferenzen
    'architecture',     -- Architektur-Entscheidungen
    'pattern',          -- Gelernte Patterns und Best Practices
    'context',          -- Projekt-Kontexte und Hintergrund
    'tool_config',      -- Tool-Konfigurationen und Setups
    'decision'          -- Wichtige Entscheidungen mit Begruendung
  )),
  title TEXT NOT NULL,                   -- Kurztitel fuer schnelles Scannen
  content TEXT NOT NULL,                 -- Eigentlicher Inhalt
  tags TEXT[] DEFAULT '{}',              -- Frei waehlbare Tags fuer Suche
  importance TEXT DEFAULT 'normal' CHECK (importance IN ('low', 'normal', 'high', 'critical')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- TIER 2: memory_active - Mittelfristig, aktuelle Arbeitsstaende
-- Offene Fragen, naechste Schritte, aktuelle Entscheidungen pro Projekt
-- =============================================================================
CREATE TABLE memory_active (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project TEXT,                          -- nullable: NULL = projektuebergreifend
  category TEXT NOT NULL CHECK (category IN (
    'work_state',       -- Aktueller Arbeitsstand
    'open_question',    -- Offene Fragen die geklaert werden muessen
    'next_step',        -- Naechste geplante Schritte
    'blocker',          -- Blockierende Probleme
    'decision_pending', -- Ausstehende Entscheidungen
    'learning'          -- Frische Erkenntnisse (werden spaeter zu core/pattern)
  )),
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  tags TEXT[] DEFAULT '{}',
  priority TEXT DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
  resolved BOOLEAN DEFAULT FALSE,        -- Markiert als erledigt, bleibt aber sichtbar
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- TIER 3: memory_sessions - Kurzfristig, pro Session
-- Was wurde gemacht, Erkenntnisse, Fehler, Zusammenfassungen
-- =============================================================================
CREATE TABLE memory_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id TEXT NOT NULL,              -- Eindeutige Session-ID (z.B. Datum + Uhrzeit)
  project TEXT,
  tool TEXT DEFAULT 'cowork' CHECK (tool IN ('cowork', 'claude_code', 'api', 'other')),
  summary TEXT NOT NULL,                 -- Was wurde in der Session gemacht
  decisions_made TEXT[],                 -- Getroffene Entscheidungen
  issues_encountered TEXT[],             -- Aufgetretene Probleme
  files_changed TEXT[],                  -- Geaenderte Dateien
  tags TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- Indexes fuer schnelle Abfragen
-- =============================================================================
CREATE INDEX idx_memory_core_project ON memory_core(project);
CREATE INDEX idx_memory_core_category ON memory_core(category);
CREATE INDEX idx_memory_core_tags ON memory_core USING GIN(tags);
CREATE INDEX idx_memory_core_importance ON memory_core(importance);

CREATE INDEX idx_memory_active_project ON memory_active(project);
CREATE INDEX idx_memory_active_category ON memory_active(category);
CREATE INDEX idx_memory_active_resolved ON memory_active(resolved);
CREATE INDEX idx_memory_active_tags ON memory_active USING GIN(tags);

CREATE INDEX idx_memory_sessions_project ON memory_sessions(project);
CREATE INDEX idx_memory_sessions_session_id ON memory_sessions(session_id);
CREATE INDEX idx_memory_sessions_tool ON memory_sessions(tool);
CREATE INDEX idx_memory_sessions_created ON memory_sessions(created_at DESC);

-- =============================================================================
-- RLS Policies (gleich wie bei roadmap: service_role hat vollen Zugriff)
-- =============================================================================
ALTER TABLE memory_core ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_active ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_sessions ENABLE ROW LEVEL SECURITY;

-- Service Role: Vollzugriff (fuer Edge Functions)
CREATE POLICY "service_role_memory_core" ON memory_core
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_memory_active" ON memory_active
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_memory_sessions" ON memory_sessions
  FOR ALL USING (auth.role() = 'service_role');

-- Updated_at Trigger
CREATE OR REPLACE FUNCTION update_memory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_memory_core_timestamp
  BEFORE UPDATE ON memory_core
  FOR EACH ROW EXECUTE FUNCTION update_memory_timestamp();

CREATE TRIGGER update_memory_active_timestamp
  BEFORE UPDATE ON memory_active
  FOR EACH ROW EXECUTE FUNCTION update_memory_timestamp();

-- =============================================================================
-- Hilfsfunktion: Volltext-Suche ueber alle Memory-Tabellen
-- =============================================================================
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
    AND (filter_project IS NULL OR mc.project = filter_project)
  UNION ALL
  SELECT 'active'::TEXT, ma.id, ma.project, ma.category, ma.title, ma.content, ma.tags, ma.created_at
  FROM memory_active ma
  WHERE (ma.title ILIKE '%' || search_term || '%' OR ma.content ILIKE '%' || search_term || '%')
    AND (filter_project IS NULL OR ma.project = filter_project)
    AND ma.resolved = FALSE
  UNION ALL
  SELECT 'session'::TEXT, ms.id, ms.project, 'session'::TEXT, ms.session_id, ms.summary, ms.tags, ms.created_at
  FROM memory_sessions ms
  WHERE (ms.summary ILIKE '%' || search_term || '%')
    AND (filter_project IS NULL OR ms.project = filter_project)
  ORDER BY created_at DESC
  LIMIT 50;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

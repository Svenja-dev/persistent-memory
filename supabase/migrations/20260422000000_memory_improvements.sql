-- Memory System: Improvements Layer
-- Migration: 20260422000000_memory_improvements.sql
--
-- Purpose: Track skill/hook/workflow/process/command/agent improvements through
-- a lifecycle: experimenting -> proven | retired. Long-lived; cross-device.
--
-- Context: The persistent-memory skill documents an "improvements" tier, but the
-- edge function and schema previously only knew core/active/sessions. This
-- migration closes that gap. Safe to apply multiple times.

-- pgvector must be available (enabled by the earlier vector-search migration).
-- Include extensions schema on search_path so the "vector" type resolves.
SET search_path = public, extensions;

CREATE TABLE IF NOT EXISTS memory_improvements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project TEXT,                          -- nullable: NULL = cross-project (usually 'global')
  title TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN (
    'skill',
    'hook',
    'workflow',
    'process',
    'command',
    'agent'
  )),
  status TEXT NOT NULL DEFAULT 'experimenting' CHECK (status IN (
    'experimenting',
    'proven',
    'retired'
  )),
  introduced_at DATE,
  evidence TEXT,
  next_step TEXT,
  related_files TEXT[] DEFAULT '{}',
  model_version_notes TEXT,
  tags TEXT[] DEFAULT '{}',
  last_used_at TIMESTAMPTZ,
  use_count INTEGER NOT NULL DEFAULT 0,
  embedding vector(1536),                -- semantic search; optional, populated by edge function if OPENAI_API_KEY is set
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- For already-created tables (re-running migration), ensure the column exists.
ALTER TABLE memory_improvements
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Indexes for typical queries
CREATE INDEX IF NOT EXISTS idx_memory_improvements_status ON memory_improvements(status);
CREATE INDEX IF NOT EXISTS idx_memory_improvements_category ON memory_improvements(category);
CREATE INDEX IF NOT EXISTS idx_memory_improvements_project ON memory_improvements(project);
CREATE INDEX IF NOT EXISTS idx_memory_improvements_tags ON memory_improvements USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_memory_improvements_last_used ON memory_improvements(last_used_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_improvements_embedding
  ON memory_improvements USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

-- RLS (service_role has full access, matching core/active/sessions)
ALTER TABLE memory_improvements ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'memory_improvements'
      AND policyname = 'service_role_memory_improvements'
  ) THEN
    EXECUTE 'CREATE POLICY "service_role_memory_improvements" ON memory_improvements
      FOR ALL USING (auth.role() = ''service_role'')';
  END IF;
END $$;

-- Reuse update_memory_timestamp() trigger (created in the base migration)
DROP TRIGGER IF EXISTS update_memory_improvements_timestamp ON memory_improvements;
CREATE TRIGGER update_memory_improvements_timestamp
  BEFORE UPDATE ON memory_improvements
  FOR EACH ROW EXECUTE FUNCTION update_memory_timestamp();

-- Add OpenClaw as supported tool in memory_sessions
-- Migration: 20260226000002_add_openclaw_tool.sql

ALTER TABLE memory_sessions
  DROP CONSTRAINT IF EXISTS memory_sessions_tool_check;

ALTER TABLE memory_sessions
  ADD CONSTRAINT memory_sessions_tool_check
  CHECK (tool IN ('cowork', 'claude_code', 'openclaw', 'api', 'other'));

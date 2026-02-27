-- Automatische Memory-Bereinigung per pg_cron
-- Migration: 20260226000001_memory_cleanup_cron.sql
-- Laeuft taeglich um 03:00 UTC (04:00 CET / 05:00 CEST)

-- Sessions aelter als 90 Tage loeschen
SELECT cron.schedule(
  'cleanup-memory-sessions',
  '0 3 * * *',
  $$DELETE FROM memory_sessions WHERE created_at < NOW() - INTERVAL '90 days'$$
);

-- Erledigte Active-Eintraege aelter als 30 Tage loeschen
SELECT cron.schedule(
  'cleanup-memory-active-resolved',
  '5 3 * * *',
  $$DELETE FROM memory_active WHERE resolved = TRUE AND resolved_at < NOW() - INTERVAL '30 days'$$
);

-- Logging: Wie viele Eintraege existieren (wöchentlich, Sonntag 03:10)
SELECT cron.schedule(
  'log-memory-stats',
  '10 3 * * 0',
  $$INSERT INTO cron_logs (function_name, status, messages_processed, tasks_created)
    SELECT 'memory-stats', 'ok',
      (SELECT count(*) FROM memory_core) + (SELECT count(*) FROM memory_active),
      (SELECT count(*) FROM memory_sessions)$$
);

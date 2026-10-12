-- Automatische Memory-Bereinigung per pg_cron
-- Migration: 20260226000001_memory_cleanup_cron.sql
-- Laeuft taeglich um 03:00 UTC (04:00 CET / 05:00 CEST)

-- Frische Supabase-Installationen aktivieren pg_cron selbst. Der Server muss
-- pg_cron in shared_preload_libraries bereitstellen (bei Supabase vorkonfiguriert).
CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA pg_catalog;

-- Sessions aelter als 90 Tage loeschen
SELECT cron.schedule(
  'cleanup-memory-sessions',
  '0 3 * * *',
  $$DELETE FROM public.memory_sessions WHERE created_at < NOW() - INTERVAL '90 days'$$
);

-- Erledigte Active-Eintraege aelter als 30 Tage loeschen
SELECT cron.schedule(
  'cleanup-memory-active-resolved',
  '5 3 * * *',
  $$DELETE FROM public.memory_active WHERE resolved = TRUE AND resolved_at < NOW() - INTERVAL '30 days'$$
);

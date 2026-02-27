# Changelog

Alle relevanten Aenderungen am Persistent Memory System.

## [1.0.0] - 2026-02-27

Erstes produktives Deployment auf Supabase.

### Datenbank
- Drei-Tabellen-Schema: `memory_core`, `memory_active`, `memory_sessions`
- Row Level Security mit `service_role`-Zugriff
- GIN-Indexes fuer Tag-Suche, B-Tree-Indexes fuer Filter
- `search_memory()` Funktion fuer Volltextsuche ueber alle Schichten
- `update_memory_timestamp()` Trigger fuer automatische `updated_at`-Pflege
- pg_cron-Jobs: Session-Cleanup (90d), Active-Cleanup (30d), woechentliches Statistik-Logging

### Edge Function (memory-manager)
- CRUD-Operationen fuer alle drei Schichten
- Bearer Token Auth mit Client-spezifischen Secrets
- Unterstuetzte Clients: cowork, claude_code, openclaw, api, backup
- `load_session` Endpoint fuer Session-Start (Core + Active + letzte 5 Sessions)
- Volltextsuche ueber alle Schichten
- Backup-Export als JSON
- Soft-Delete fuer Active-Eintraege (resolved-Flag)
- CORS-Support fuer Cross-Origin-Zugriff

### Tooling
- `backup_memory.py`: Lokales JSON-Backup mit automatischer Bereinigung (30 Tage)
- `deploy.ps1`: PowerShell-Deployment-Script
- `SKILL.md`: Skill-Dokumentation fuer Claude-basierte Tools

### Migrations
- `20260226000000_memory_tables.sql` - Schema, RLS, Indexes, Suchfunktion
- `20260226000001_memory_cleanup_cron.sql` - pg_cron Retention-Jobs
- `20260226000002_add_openclaw_tool.sql` - OpenClaw als Client

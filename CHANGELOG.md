# Changelog

Alle relevanten Aenderungen am Persistent Memory System.

## Unreleased

### Sicherheit und Installation
- Such-, Export- und Restore-RPCs auf die Serverrolle beschraenkt und SQL-Suchpfade abgesichert.
- Private Standard-Endpunkte entfernt; Deployment, Backup und Restore verlangen ein ausdrueckliches Ziel.
- Backup-Zugriff auf Lesen beschraenkt; Restore mit eigenem Schluessel und expliziter Rolle.
- Reproduzierbares Cowork-/Codex-Skill-Paket ausschliesslich aus `SKILL.md` und `LICENSE`; private Arbeitsdateien bleiben ausgeschlossen.
- Gemeinsamen Skill, getrennte Instanz je Person, Konfiguration in Cowork und Codex, externe Embedding-Datenfluesse und Grenzen automatischer Skill-Aktivierung dokumentiert.
- MIT-Lizenzdatei ergaenzt; Mindestversion fuer Python-Werkzeuge und Tests auf 3.11 vereinheitlicht.

### Zuverlaessigkeit
- Vollstaendiger konsistenter Export aller vier Memory-Tabellen mit versioniertem Vertrag und validierten Counts.
- Backup-Dateien eindeutig und atomar schreiben; unvollstaendige Exporte verhindern Speicherung und Retention.
- Restore bewahrt UUIDs, Zeitstempel und Lebenszyklus; Wiederholung fuegt nur fehlende Datensaetze ein.
- Ungueltige Backups ablehnen und abweichende Restore-Ziele ausdruecklich bestaetigen lassen.
- Kontextbegrenzung sichtbar machen und Pflichtabfragefehler weiterreichen.
- Embeddings nach Text-Teilupdates aus dem gesamten Text erneuern oder invalidieren.
- Improvements in die Suche aufgenommen, Core-Kategorien mit dem Schema vereinheitlicht und POST-Felder pro Tier begrenzt.
- Active-Status und `resolved_at` konsistent halten; frische Cron-Installation repariert und ungueltigen Statistikjob entfernt.
- Fehlgeschlagene Deployment-Verbindungstests als Fehler beenden.
- Deterministische API-, SQL-, Backup-/Restore-, Deployment- und Pakettests ohne bezahlten Modellzugang ergaenzt.

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

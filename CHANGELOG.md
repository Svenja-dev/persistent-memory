# Changelog

Alle relevanten Aenderungen am Persistent Memory System.

## Unreleased

### Sicherheit und Installation
- Such-, Export- und Restore-RPCs auf die Serverrolle beschraenkt und SQL-Suchpfade abgesichert.
- Private Standard-Endpunkte entfernt; Deployment, Backup und Restore verlangen ein ausdrueckliches Ziel.
- Backup-Zugriff auf Lesen beschraenkt; Restore mit eigenem Schluessel und expliziter Rolle.
- Reproduzierbares Cowork-/Codex-Skill-Paket ausschliesslich aus `SKILL.md`, `LICENSE` und `scripts/load_memory.py`; private Arbeitsdateien bleiben ausgeschlossen.
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

### Review-Nacharbeit (PR #10)
- Migration `20260909000000_search_include_global.sql` mit Migrations-ID im Header, vollqualifizierten `extensions.vector`-Typen, festem `search_path` und eigenen RPC-Grants; damit ist jede Migration einzeln installierbar und zu keinem Zeitpunkt oeffentlich aufrufbar.
- Kommentare und Docstrings der neuen TypeScript-, Python- und PowerShell-Dateien auf Deutsch vereinheitlicht; Funktions-Docstrings ergaenzt.
- Nicht mehr verwendetes Modul `embedding-helper.ts` aus Edge Function und Referenzkopie entfernt.
- Regressionstests ergaenzt: Projektnamen mit PostgREST-Sonderzeichen bleiben im `load_session`-Filter gequotet; Restore-Bestaetigungen werden unabhaengig von der UUID-Schreibweise erkannt.
- `scripts/test-payloads.sh` ohne private Pfade und an den neuen API-Vertrag angepasst (unbekannte Felder liefern 400, Restore ohne Rolle 403).
- CI-Datenbankjob wartet auf den abgeschlossenen Init-Prozess des Supabase-Images statt nur auf `pg_isready`; vorher konnte die Cron-Migration gegen den temporaeren Init-Server laufen und zufaellig scheitern.

### Automatisches Laden
- Neues Ladeskript `scripts/load_memory.py` im Skill-Paket: laedt `load_session` fuer das aktuelle Projekt als kompakten Klartext, stumm ohne Konfiguration, sichtbar bei Fehlern, mit Laengenbegrenzung.
- Claude Code laedt ueber einen dokumentierten `SessionStart`-Hook, Codex ueber `~/.codex/AGENTS.md`, Cowork ueber Skill-Beschreibung und Arbeitsablauf; SKILL.md fordert das Laden als ersten Schritt.
- `load_session` und Listenabfragen waehlen Spalten ausdruecklich aus und uebertragen den Embedding-Vektor nicht mehr (bis zu 1536 Zahlen pro Eintrag).

### Zweite Review-Runde vor dem Merge
- Restore setzt fuer fehlende optionale Felder die Tabellen-Defaults (`resolved=false`, `tags='{}'`, `status='experimenting'`, `use_count=0`, `priority`/`importance`/`tool`), damit kein wiederhergestellter Datensatz unsichtbar und von der Bereinigung ausgenommen bleibt; SQL-Vertragstest ergaenzt.
- Migration `20261010` ersetzt den Kategorie-Check auf `memory_core` unabhaengig vom vorhandenen Constraint-Namen.
- `load_session` meldet `truncated` nur noch fuer Core, Active und Improvements; das gewollte Fenster von fuenf Sessions gilt nicht als Luecke (sonst haette das Ladeskript bei jedem Start eine Luecke gemeldet).
- Teilupdates lesen die Vorzeile ohne Embedding-Vektor; DELETE auf `core`/`sessions` liefert 404 statt eines scheinbaren Erfolgs fuer unbekannte IDs.
- Ladeskript und Restore schreiben UTF-8 auch in Windows-Pipes; `scripts/test-payloads.sh` laeuft auch mit bash 3.2; toter Wrapper `get_api_secret` entfernt.
- README: Hinweis fuer bestehende Installationen, deren Migrationshistorie nicht den Repo-Versionen entspricht (`supabase db push` wuerde dort scheitern).

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

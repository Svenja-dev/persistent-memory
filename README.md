# Persistent Memory System

Dreischichtiges Memory-System fuer Claude-basierte Tools. Speichert Praeferenzen, Arbeitsstaende und Session-Protokolle persistent in Supabase und macht sie projektuebergreifend verfuegbar.

## Ueberblick

| Schicht | Tabelle | Zweck | Retention |
|---------|---------|-------|-----------|
| **Core** | `memory_core` | Praeferenzen, Architektur-Entscheidungen, Patterns | Dauerhaft |
| **Active** | `memory_active` | Arbeitsstaende, Blocker, offene Fragen | Bis resolved + 30 Tage |
| **Sessions** | `memory_sessions` | Was wurde in einer Session gemacht | 90 Tage |

## Architektur

```
Clients (Cowork, Claude Code, OpenClaw, API)
        |
        v  Bearer Token Auth
  Supabase Edge Function (memory-manager)
        |
        v  Service Role Key
  PostgreSQL
  +-- memory_core      (langfristig)
  +-- memory_active    (mittelfristig, soft-delete)
  +-- memory_sessions  (kurzfristig, auto-cleanup)
        |
        v  pg_cron
  Automatische Bereinigung (taeglich 03:00 UTC)
        |
        v  backup_memory.py
  Lokales JSON-Backup (optional, Google Drive Sync)
```

## Projektstruktur

```
persistent-memory/
+-- supabase/
|   +-- config.toml                              # Supabase CLI Konfiguration
|   +-- migrations/
|   |   +-- 20260226000000_memory_tables.sql     # Schema: 3 Tabellen, RLS, Indexes, Suchfunktion
|   |   +-- 20260226000001_memory_cleanup_cron.sql  # pg_cron Jobs fuer Retention
|   |   +-- 20260226000002_add_openclaw_tool.sql    # OpenClaw als Client hinzugefuegt
|   +-- functions/
|       +-- memory-manager/
|           +-- index.ts                         # Edge Function (Deno): CRUD + Search + Backup
+-- backup/
|   +-- backup_memory.py                         # Python-Script fuer lokale JSON-Backups
|   +-- .env.example                             # Vorlage fuer Backup-Konfiguration
+-- edge-function/
|   +-- index.ts                                 # Quellkopie der Edge Function (Referenz)
+-- supabase-migrations/
|   +-- *.sql                                    # Quellkopien der Migrations (Referenz)
+-- SKILL.md                                     # Skill-Anweisungen fuer Claude-Tools
+-- ARCHITECTURE.md                              # Technische Architektur-Dokumentation
+-- AGENTS.md                                    # Entwicklungsrichtlinien fuer AI-Assistenten
+-- CHANGELOG.md                                 # Versionshistorie
+-- deploy.ps1                                   # Deployment-Script (PowerShell)
+-- .gitignore
+-- README.md                                    # Diese Datei
```

## Voraussetzungen

- [Supabase CLI](https://supabase.com/docs/guides/cli) (v2.x)
- Supabase-Projekt mit aktiviertem `pg_cron` und `pg_net`
- Python 3.8+ (nur fuer Backup-Script)

## Deployment

### 1. Projekt verlinken

```bash
cd persistent-memory
supabase link --project-ref naatzputlsusiiczltzp
```

### 2. Datenbank-Migrations ausfuehren

```bash
supabase db push
```

Erstellt die drei Tabellen (`memory_core`, `memory_active`, `memory_sessions`), Indexes, RLS-Policies, die `search_memory()`-Funktion und pg_cron-Jobs.

### 3. Edge Function deployen

```bash
supabase functions deploy memory-manager --no-verify-jwt
```

### 4. API Secret setzen

```bash
supabase secrets set API_SECRET=dein-secret-hier
```

Optional pro Client (empfohlen fuer Produktivbetrieb):

```bash
supabase secrets set API_SECRET_COWORK=... API_SECRET_CLAUDE_CODE=... API_SECRET_OPENCLAW=...
```

### 5. Testen

```bash
# Session laden (leeres Ergebnis bei frischer Installation)
curl -s -H "Authorization: Bearer $API_SECRET" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager?action=load_session"

# Erwartete Antwort: {"success":true,"action":"load_session","project":"all","core":{"count":0,...},...}
```

## API-Referenz

Base-URL: `https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager`

Alle Requests benoetigen den Header `Authorization: Bearer <SECRET>`.
Optional: `X-Memory-Client: cowork|claude_code|openclaw|api|backup`

### GET Endpoints

| Endpoint | Beschreibung |
|----------|-------------|
| `?action=load_session` | Core + offene Active + letzte 5 Sessions laden |
| `?action=load_session&project=fabrikiq` | Projektspezifisch laden |
| `?action=search&q=flutter` | Volltextsuche ueber alle Schichten |
| `?action=backup` | Kompletter Datenexport als JSON |
| `?tier=core&category=pattern` | Gefiltert lesen (tier, category, project, tag, limit) |

### POST Endpoint

Body als JSON. Pflichtfelder abhaengig vom Tier:

```json
{
  "tier": "core",
  "category": "pattern",
  "title": "Edge Function Auth Pattern",
  "content": "Alle Edge Functions nutzen Bearer Token Auth",
  "project": "fabrikiq",
  "tags": ["supabase", "auth"],
  "importance": "high"
}
```

Mit `"id": "UUID"` im Body wird ein bestehender Eintrag aktualisiert (Upsert).

### DELETE Endpoint

```
DELETE ?tier=active&id=<UUID>    # Soft-Delete: markiert als resolved
DELETE ?tier=core&id=<UUID>      # Hard-Delete
DELETE ?tier=sessions&id=<UUID>  # Hard-Delete
```

## Backup

```bash
cd backup
cp .env.example .env
# .env editieren: API_SECRET_BACKUP=dein-secret
python backup_memory.py
```

Erstellt `memory_backup_YYYYMMDD_HHMMSS.json` und loescht Backups aelter als 30 Tage.

## Skill-Installation

Die Datei `SKILL.md` enthaelt die vollstaendige Anleitung fuer Claude-Tools (Cowork, Claude Code, OpenClaw). Installation:

- **Cowork**: Skill ueber die Oberflaeche hinzufuegen
- **Claude Code**: Nach `~/.claude/skills/persistent-memory/` kopieren

## Lizenz

MIT

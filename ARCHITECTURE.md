# Architecture

## Systemueberblick

Das Persistent Memory System ist ein serverloser REST-Service auf Basis von Supabase. Es besteht aus drei Komponenten:

1. **Edge Function** (`memory-manager`) - Geschaeftslogik, Auth, CRUD-Operationen
2. **PostgreSQL-Datenbank** - Drei Tabellen mit RLS, Indexes und Volltextsuche
3. **pg_cron-Jobs** - Automatische Datenbereinigung nach Retention-Regeln

## Datenmodell

### Drei-Schichten-Architektur

```
                    Lebensdauer
                    <--------->
  memory_core       |=========================================|  dauerhaft
  memory_active     |==============|  bis resolved + 30 Tage
  memory_sessions   |========|  90 Tage
```

**Warum drei Schichten?**
- **Core**: Wissen das sich selten aendert (Praeferenzen, Patterns). Wird bei jedem Session-Start geladen.
- **Active**: Laufende Arbeit. Hat ein `resolved`-Flag fuer Soft-Delete. Nur unerledigte Eintraege werden bei Session-Start geladen.
- **Sessions**: Protokoll was wann gemacht wurde. Wird fuer Kontext der letzten 5 Sessions geladen, danach nur noch ueber Suche erreichbar.

### memory_core

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| id | UUID | Primaerschluessel (auto-generiert) |
| project | TEXT | Projektname oder NULL (projektuebergreifend) |
| category | TEXT | preference, architecture, pattern, context, tool_config, decision |
| title | TEXT | Kurztitel fuer schnelles Scannen (NOT NULL) |
| content | TEXT | Eigentlicher Inhalt (NOT NULL) |
| tags | TEXT[] | Frei waehlbare Tags (Array) |
| importance | TEXT | low, normal (default), high, critical |
| created_at | TIMESTAMPTZ | Erstellungszeitpunkt |
| updated_at | TIMESTAMPTZ | Letzte Aenderung (Trigger-gesteuert) |

### memory_active

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| id | UUID | Primaerschluessel |
| project | TEXT | Projektname oder NULL |
| category | TEXT | work_state, open_question, next_step, blocker, decision_pending, learning |
| title | TEXT | Kurztitel (NOT NULL) |
| content | TEXT | Inhalt (NOT NULL) |
| tags | TEXT[] | Tags (Array) |
| priority | TEXT | low, normal (default), high, urgent |
| resolved | BOOLEAN | Soft-Delete Flag (default: false) |
| resolved_at | TIMESTAMPTZ | Zeitpunkt der Erledigung |
| created_at | TIMESTAMPTZ | Erstellungszeitpunkt |
| updated_at | TIMESTAMPTZ | Letzte Aenderung (Trigger-gesteuert) |

### memory_sessions

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| id | UUID | Primaerschluessel |
| session_id | TEXT | Eindeutige Session-ID (z.B. `2026-02-27_claude_code_1`) |
| project | TEXT | Projektname oder NULL |
| tool | TEXT | cowork, claude_code, openclaw, api, other |
| summary | TEXT | Was wurde gemacht (NOT NULL) |
| decisions_made | TEXT[] | Getroffene Entscheidungen |
| issues_encountered | TEXT[] | Aufgetretene Probleme |
| files_changed | TEXT[] | Geaenderte Dateien |
| tags | TEXT[] | Tags (Array) |
| created_at | TIMESTAMPTZ | Erstellungszeitpunkt |

## Sicherheitsmodell

### Authentifizierung

```
Client Request
    |
    v
Bearer Token aus Authorization-Header extrahieren
    |
    v
Client identifizieren (X-Memory-Client Header oder ?client= Query)
    |
    +--[Client angegeben]--> Token gegen CLIENT_SECRET_ENV[client] pruefen
    |                        Fallback: Token gegen API_SECRET pruefen
    |
    +--[Kein Client]-------> Token gegen ALLE konfigurierten Secrets pruefen
    |
    v
Zugriff erlaubt oder 401 Unauthorized
```

### Secret-Hierarchie

| Environment Variable | Client | Zweck |
|---------------------|--------|-------|
| `API_SECRET` | Alle (Legacy-Fallback) | Gemeinsamer Schluessel |
| `API_SECRET_COWORK` | cowork | Cowork-spezifisch |
| `API_SECRET_CLAUDE_CODE` | claude_code | Claude Code CLI |
| `API_SECRET_OPENCLAW` | openclaw | OpenClaw |
| `API_SECRET_API` | api | Externe API-Aufrufe |
| `API_SECRET_BACKUP` | backup | Backup-Script |

Empfehlung: Pro Client eigene Secrets vergeben. So kann ein kompromittierter Client isoliert werden, ohne alle anderen zu invalidieren.

### Row Level Security (RLS)

Alle drei Tabellen haben RLS aktiviert. Nur die `service_role` hat Zugriff. Die Edge Function nutzt den `SUPABASE_SERVICE_ROLE_KEY` und umgeht damit RLS-Einschraenkungen fuer Endnutzer.

Direkte Datenbankzugriffe mit dem `anon`-Key sind blockiert.

### JWT-Verification

Die Edge Function ist mit `verify_jwt = false` deployt. Die Authentifizierung laeuft ausschliesslich ueber die eigene Bearer-Token-Validierung, nicht ueber Supabase Auth JWT.

## Retention und Cleanup

Drei pg_cron-Jobs laufen taeglich um 03:00 UTC:

| Job | Zeitplan | Aktion |
|-----|----------|--------|
| `cleanup-memory-sessions` | Taeglich 03:00 | Sessions aelter als 90 Tage loeschen |
| `cleanup-memory-active-resolved` | Taeglich 03:05 | Erledigte Active-Eintraege aelter als 30 Tage loeschen |
| `log-memory-stats` | Sonntags 03:10 | Statistiken in `cron_logs` schreiben |

## Indexierung

| Tabelle | Index | Typ | Zweck |
|---------|-------|-----|-------|
| memory_core | project, category, importance | B-Tree | Filter-Queries |
| memory_core | tags | GIN | Array-Contains-Suche |
| memory_active | project, category, resolved | B-Tree | Filter-Queries |
| memory_active | tags | GIN | Array-Contains-Suche |
| memory_sessions | project, session_id, tool | B-Tree | Filter-Queries |
| memory_sessions | created_at DESC | B-Tree | Sortierung nach Aktualitaet |

## Volltextsuche

Die Funktion `search_memory(search_term, filter_project)` durchsucht alle drei Tabellen mit `ILIKE` und gibt maximal 50 Ergebnisse zurueck, sortiert nach `created_at DESC`.

Suchfelder pro Tabelle:
- **Core**: title, content
- **Active**: title, content (nur nicht-resolved)
- **Sessions**: summary

## Request-Ablauf

```
1. Client sendet HTTP-Request
2. CORS-Preflight (OPTIONS) wird direkt beantwortet
3. Bearer Token wird validiert
4. Request-ID wird generiert (UUID, 8 Zeichen)
5. Je nach HTTP-Methode:
   GET  -> load_session / search / backup / list
   POST -> create oder update (upsert via id-Feld)
   DELETE -> soft-delete (active) oder hard-delete (core, sessions)
6. Ergebnis als JSON mit X-Request-Id Header
7. Logging: Request-ID, Methode, Erfolg/Fehler
```

## Abhaengigkeiten

### Runtime
- Supabase (PostgreSQL 17, Edge Functions / Deno)
- pg_cron Extension (fuer Retention-Jobs)
- pg_net Extension (optional, fuer Monitoring)

### Entwicklung
- Supabase CLI v2.x
- Python 3.8+ (nur Backup-Script)

### Keine weiteren Dependencies
Die Edge Function nutzt ausschliesslich Deno-Standardbibliothek und den Supabase JS Client. Kein npm, kein package.json.

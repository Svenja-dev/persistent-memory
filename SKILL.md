---
name: persistent-memory
description: Persistentes Memory-System ueber Supabase. Drei Schichten (Core/Active/Sessions) fuer projektuebergreifendes Wissen, aktuelle Arbeitsstaende und Session-Protokolle. Automatisches Laden bei Session-Start, Schreiben bei wichtigen Erkenntnissen, Backup in lokales Verzeichnis.
license: MIT
---

## Uebersicht

Dieses Skill steuert ein dreischichtiges Memory-System in Supabase:

| Schicht | Tabelle | Zweck | Lebensdauer |
|---------|---------|-------|-------------|
| Core | memory_core | Praeferenzen, Architektur, Patterns, Entscheidungen | Langfristig (Monate/Jahre) |
| Active | memory_active | Arbeitsstaende, offene Fragen, Blocker, naechste Schritte | Mittelfristig (Tage/Wochen) |
| Sessions | memory_sessions | Session-Zusammenfassungen, was wurde gemacht | Kurzfristig (Protokoll) |

## Konfiguration

Die API-Endpunkt-URL und ein Secret muessen als Umgebungsvariablen verfuegbar sein.
Falls nicht vorhanden, nutze diese Werte:

```
MEMORY_API_URL=https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager
```

Der API_SECRET ist derselbe wie fuer die anderen Supabase Edge Functions (get-roadmap, get-tasks).

Optional (empfohlen fuer getrennte Secrets pro Client):
- `API_SECRET_COWORK`
- `API_SECRET_CLAUDE_CODE`
- `API_SECRET_OPENCLAW`
- `API_SECRET_API`
- `API_SECRET_BACKUP`

Client-Hinweis pro Request ueber Header `X-Memory-Client` oder Query `?client=...`.

## PFLICHT: Session-Start

Bei JEDER neuen Session sofort das Memory laden:

```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  "$MEMORY_API_URL?action=load_session&project=PROJEKTNAME" | python3 -m json.tool
```

Ersetze PROJEKTNAME durch das aktuelle Projekt (z.B. fabrikiq, beast-masters-arena) oder lasse den Parameter weg fuer alle Projekte.

Das Ergebnis enthaelt:
- **core**: Alle langfristigen Eintraege (Praeferenzen, Patterns, Entscheidungen)
- **active**: Alle unerledigten Arbeitsstaende und offenen Fragen
- **recent_sessions**: Die letzten 5 Session-Zusammenfassungen

LIES ALLES und beruecksichtige es im weiteren Verlauf der Session.

## Wann Memory SCHREIBEN

### In memory_core schreiben bei:
- Neue Architektur-Entscheidung getroffen (category: architecture)
- Neues Pattern oder Best Practice entdeckt (category: pattern)
- Tool-Konfiguration geaendert (category: tool_config)
- Wichtige Entscheidung mit Begruendung (category: decision)
- Nutzer-Praeferenz geaendert (category: preference)
- Neuer Projekt-Kontext (category: context)

### In memory_active schreiben bei:
- Arbeit begonnen an einem Feature (category: work_state)
- Frage aufgetaucht die spaeter geklaert werden muss (category: open_question)
- Naechste Schritte identifiziert (category: next_step)
- Problem blockiert Fortschritt (category: blocker)
- Entscheidung steht aus (category: decision_pending)
- Frische Erkenntnis die noch validiert werden muss (category: learning)

### In memory_sessions schreiben bei:
- Session-Ende (PFLICHT): Zusammenfassung was gemacht wurde
- Feld `tool` konsistent setzen: `cowork`, `claude_code`, `openclaw`, `api` oder `other`

## API-Referenz

### Memory laden (Session-Start)
```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: openclaw" \
  "$MEMORY_API_URL?action=load_session&project=fabrikiq"
```

### Suchen
```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  "$MEMORY_API_URL?action=search&q=flutter&project=fabrikiq"
```

### Eintraege lesen (gefiltert)
```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  "$MEMORY_API_URL?tier=core&category=pattern&project=fabrikiq"
```

### Eintrag erstellen
```bash
curl -s -X POST -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: openclaw" \
  -H "Content-Type: application/json" \
  "$MEMORY_API_URL" \
  -d '{
    "tier": "core",
    "project": "fabrikiq",
    "category": "pattern",
    "title": "Edge Function Pattern",
    "content": "Alle Edge Functions nutzen API_SECRET Bearer Token Auth und CORS Headers",
    "tags": ["supabase", "edge-functions", "auth"],
    "importance": "high"
  }'
```

### Eintrag aktualisieren (mit id)
```bash
curl -s -X POST -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "$MEMORY_API_URL" \
  -d '{
    "tier": "active",
    "id": "UUID-HIER",
    "content": "Aktualisierter Inhalt",
    "priority": "high"
  }'
```

### Active-Eintrag als erledigt markieren (Soft Delete)
```bash
curl -s -X DELETE -H "Authorization: Bearer $API_SECRET" \
  "$MEMORY_API_URL?tier=active&id=UUID-HIER"
```

### Session-Zusammenfassung schreiben
```bash
curl -s -X POST -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "$MEMORY_API_URL" \
  -d '{
    "tier": "sessions",
    "session_id": "2026-02-26_openclaw_1",
    "project": "fabrikiq",
    "tool": "openclaw",
    "summary": "Memory-System implementiert: Supabase-Tabellen, Edge Function, Cowork-Skill",
    "decisions_made": ["Supabase als zentrale DB", "3-Tier Architektur", "Lokaler Backup"],
    "issues_encountered": ["Skills-Ordner ist read-only in Cowork"],
    "files_changed": ["memory_tables.sql", "memory-manager/index.ts", "SKILL.md"],
    "tags": ["infrastructure", "memory"]
  }'
```

### Backup exportieren
```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: backup" \
  "$MEMORY_API_URL?action=backup" > /pfad/zum/backup/memory_backup_$(date +%Y%m%d_%H%M%S).json
```

## Backup-Routine

Backup-Script: `persistent-memory/backup/backup_memory.py`

Das Script kann manuell oder per Scheduled Task ausgefuehrt werden:
```bash
cd persistent-memory/backup
python backup_memory.py
```

Es erstellt eine JSON-Datei mit Zeitstempel und loescht Backups aelter als 30 Tage.
Backup-Verzeichnis wird automatisch auf Google Drive gesichert (sofern konfiguriert).

## Kategorien-Referenz

### memory_core Kategorien
| Kategorie | Wann verwenden | Beispiel |
|-----------|----------------|----------|
| preference | Nutzer will etwas anders haben | "Keine Emojis in Antworten" |
| architecture | Technische Grundsatzentscheidung | "Supabase fuer alle DB-Beduerfnisse" |
| pattern | Wiederverwendbares Vorgehen | "Edge Functions immer mit API_SECRET" |
| context | Hintergrund zu Projekt/Person | "fabrikIQ: MES-Analytics, B2B SaaS" |
| tool_config | Setup eines Tools | "GitHub Actions mit Vercel Preview" |
| decision | Entscheidung mit Pro/Contra | "React statt Vue wegen Team-Erfahrung" |

### memory_active Kategorien
| Kategorie | Wann verwenden | Beispiel |
|-----------|----------------|----------|
| work_state | Aktueller Stand einer Arbeit | "Dashboard: 3/5 Widgets fertig" |
| open_question | Ungeklaerte Frage | "Welches Pricing-Modell fuer Premium?" |
| next_step | Geplanter naechster Schritt | "Unit Tests fuer API-Endpoints schreiben" |
| blocker | Etwas blockiert Fortschritt | "AWS Lambda Timeout bei grossen Dateien" |
| decision_pending | Entscheidung steht aus | "Mono-Repo vs Multi-Repo?" |
| learning | Frische Erkenntnis | "Deno Deploy ist schneller als Lambda" |

## Wichtige Regeln

1. **IMMER** beim Session-Start Memory laden (load_session)
2. **IMMER** beim Session-Ende eine Session-Zusammenfassung schreiben
3. Vor dem Schreiben in memory_core pruefen ob ein aehnlicher Eintrag existiert (search)
4. memory_active Eintraege als resolved markieren wenn erledigt, nicht loeschen
5. Tags konsistent verwenden (kleingeschrieben, Bindestriche)
6. Projekt-Name konsistent schreiben (kleingeschrieben: fabrikiq, beast-masters-arena)
7. Kein PII (persoenliche Daten) in Memory speichern
8. API_SECRET NIEMALS im Klartext in Dateien speichern

## Installation

### 1. Supabase Migration ausfuehren
```bash
cd persistent-memory
supabase link --project-ref naatzputlsusiiczltzp
supabase db push
```

### 2. Edge Function deployen
```bash
supabase functions deploy memory-manager --no-verify-jwt
```

### 3. Skill in Cowork installieren
Den Ordner `persistent-memory` ueber die Cowork-Oberflaeche als Skill hinzufuegen
oder nach `~/.claude/skills/persistent-memory/` kopieren (Claude Code).

### 4. Backup einrichten
```bash
cd persistent-memory/backup
cp .env.example .env
# .env editieren: API_SECRET_BACKUP=dein-secret
python backup_memory.py
```

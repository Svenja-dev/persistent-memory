---
name: persistent-memory
description: Persistentes Memory-System ueber Supabase. Drei Schichten (Core/Active/Sessions) fuer projektuebergreifendes Wissen, aktuelle Arbeitsstaende und Session-Protokolle. Automatisches Laden bei Session-Start, Schreiben bei wichtigen Erkenntnissen, Backup in lokales Verzeichnis.
license: MIT
---

## OBERSTE REGEL: Kein Fehler bei fehlendem Secret

**BEVOR du irgendetwas in diesem Skill ausfuehrst, lies diese Regel:**

Falls das API-Secret nicht aufgeloest werden kann (weder Umgebungsvariable noch Datei):
- **KEIN Hinweis, KEINE Fehlermeldung, KEIN Kommentar. NICHTS.**
- Ueberspringe ALLE Supabase-Memory-Operationen LAUTLOS.
- Arbeite normal weiter ohne Supabase-Memory.
- Generiere NIEMALS Saetze wie:
  - "API_SECRET nicht gesetzt"
  - "Memory konnte nicht geladen werden"
  - "Supabase Memory konnte nicht aktualisiert werden"
  - "kein API_SECRET in der Umgebung"
  - Oder irgendeine andere Variante davon.

**Wenn das Secret fehlt, ist das kein Fehler sondern ein erwarteter Zustand.**
Behandle es wie ein optionales Feature das gerade nicht aktiv ist — lautlos.

Diese Regel hat VORRANG vor allen anderen Regeln in diesem Dokument.
"Memory laden" ist KEIN Pflicht-Schritt. Es ist ein bedingter Schritt.

---

## Uebersicht

Dieses Skill steuert ein dreischichtiges Memory-System in Supabase:

| Schicht | Tabelle | Zweck | Lebensdauer |
|---------|---------|-------|-------------|
| Core | memory_core | Praeferenzen, Architektur, Patterns, Entscheidungen | Langfristig (Monate/Jahre) |
| Active | memory_active | Arbeitsstaende, offene Fragen, Blocker, naechste Schritte | Mittelfristig (Tage/Wochen) |
| Sessions | memory_sessions | Session-Zusammenfassungen, was wurde gemacht | Kurzfristig (Protokoll) |

## Secret Resolution (Multi-Pfad-Fallback)

VOR jedem curl-Befehl muss das API-Secret aufgeloest werden. Nutze diesen
Multi-Pfad-Fallback. Falls KEINE Stufe ein Secret liefert: **lautlos abbrechen** (siehe oberste Regel).

**WICHTIG — Warum Multi-Pfad noetig ist:**
- In **Claude Code CLI** ist `~` = `C:\Users\Anwender`, also `~/.claude/memory-secret` funktioniert.
- In **Cowork** laeuft eine Linux-VM. Dort ist `HOME=/sessions/<session>/` und `~/.claude/` existiert NICHT.
  Die echte Datei liegt unter `$HOME/mnt/Anwender/.claude/memory-secret` (gemountetes Windows-Home).
- `env`-Bloecke aus `settings.json` werden in Cowork NICHT als Umgebungsvariablen injiziert.

```bash
# Stufe 1: Umgebungsvariable (funktioniert in Claude Code CLI)
# Stufe 2: Datei-Fallback mit Multi-Pfad (funktioniert in CLI UND Cowork)
# Stufe 3: Lautlos abbrechen

_MS=""
for _P in \
  "$HOME/.claude/memory-secret" \
  "$HOME/mnt/Anwender/.claude/memory-secret" \
  "/c/Users/Anwender/.claude/memory-secret"; do
  [ -z "$_P" ] && continue
  [ -f "$_P" ] && _MS="$(cat "$_P" 2>/dev/null)" && break
done

API_SECRET="${API_SECRET:-${API_SECRET_COWORK:-${API_SECRET_CLAUDE_CODE:-$_MS}}}"
MEMORY_API_URL="${MEMORY_API_URL:-https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager}"

# Pruefen ob Secret aufgeloest wurde — wenn nicht: LAUTLOS abbrechen
if [ -z "$API_SECRET" ]; then exit 0; fi
```

**Erklaerung der Pfade:**
1. `$HOME/.claude/memory-secret` — Funktioniert in Claude Code CLI (HOME = C:\Users\Anwender)
2. `$HOME/mnt/Anwender/.claude/memory-secret` — Funktioniert in Cowork (HOME = /sessions/xxx, Windows-Home gemountet unter mnt/Anwender)
3. `/c/Users/Anwender/.claude/memory-secret` — Fallback fuer WSL/Git Bash

**Erklaerung der Env-Var-Kette:**
1. `$API_SECRET` — direkte Umgebungsvariable (Claude Code CLI via settings.json env-Block)
2. `$API_SECRET_COWORK` / `$API_SECRET_CLAUDE_CODE` — client-spezifische Variablen
3. Datei-Fallback `$_MS` — greift wenn keine Env-Var gesetzt ist (Normalfall in Cowork)

Die Datei `memory-secret` enthaelt nur den rohen API-Key (eine Zeile, kein Newline noetig).

Client-Hinweis pro Request ueber Header `X-Memory-Client` oder Query `?client=...`.

## Session-Start (bedingt)

Bei neuen Sessions das Memory laden, **sofern das Secret aufgeloest werden kann**:

```bash
_MS=""
for _P in \
  "$HOME/.claude/memory-secret" \
  "$HOME/mnt/Anwender/.claude/memory-secret" \
  "/c/Users/Anwender/.claude/memory-secret"; do
  [ -z "$_P" ] && continue
  [ -f "$_P" ] && _MS="$(cat "$_P" 2>/dev/null)" && break
done
API_SECRET="${API_SECRET:-${API_SECRET_COWORK:-${API_SECRET_CLAUDE_CODE:-$_MS}}}"
MEMORY_API_URL="${MEMORY_API_URL:-https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager}"
if [ -z "$API_SECRET" ]; then exit 0; fi

curl -s -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: cowork" \
  "$MEMORY_API_URL?action=load_session&project=PROJEKTNAME" | python3 -m json.tool 2>/dev/null || python -m json.tool 2>/dev/null
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
- Session-Ende: Zusammenfassung was gemacht wurde (sofern Secret verfuegbar)
- Feld `tool` konsistent setzen: `cowork`, `claude_code`, `api` oder `other` (Legacy: `openclaw` wird noch akzeptiert)

## API-Referenz

Alle Befehle setzen voraus, dass der Secret-Resolution-Block (siehe oben) bereits ausgefuehrt wurde.
Wenn `$API_SECRET` leer ist, fuehre KEINEN curl-Befehl aus und gib KEINE Meldung aus.

### Memory laden (Session-Start)
```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: cowork" \
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
  -H "X-Memory-Client: cowork" \
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
    "session_id": "2026-02-26_cowork_1",
    "project": "fabrikiq",
    "tool": "cowork",
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

1. Beim Session-Start Memory laden, **sofern Secret verfuegbar** (load_session)
2. Beim Session-Ende eine Session-Zusammenfassung schreiben, **sofern Secret verfuegbar**
3. Vor dem Schreiben in memory_core pruefen ob ein aehnlicher Eintrag existiert (search)
4. memory_active Eintraege als resolved markieren wenn erledigt, nicht loeschen
5. Tags konsistent verwenden (kleingeschrieben, Bindestriche)
6. Projekt-Name konsistent schreiben (kleingeschrieben: fabrikiq, beast-masters-arena)
7. Kein PII (persoenliche Daten) in Memory speichern
8. API_SECRET NIEMALS im Klartext in Code-Dateien speichern (Ausnahme: ~/.claude/memory-secret)
9. In Cowork keine `.env` im Skill-Snapshot voraussetzen; env-basierte Konfiguration hat Vorrang
10. **NIEMALS Fehlermeldungen generieren wenn Secret oder Shell nicht verfuegbar**

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

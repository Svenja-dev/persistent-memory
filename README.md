# Persistent Memory Skill

Dreischichtiges Memory-System fuer Claude (Cowork, Claude Code, OpenClaw, API).

## Architektur

```
Cowork / Claude Code / OpenClaw / API
        |
        v
  Edge Function (memory-manager)
        |
        v
  Supabase PostgreSQL
  ├── memory_core      (langfristig)
  ├── memory_active    (mittelfristig)
  └── memory_sessions  (kurzfristig)
        |
        v
  Lokales Backup (JSON) → Google Drive Sync
```

## Schnellstart

### Secrets (empfohlen)
Legacy: `API_SECRET`  
Client-spezifisch: `API_SECRET_COWORK`, `API_SECRET_CLAUDE_CODE`, `API_SECRET_OPENCLAW`, `API_SECRET_API`, `API_SECRET_BACKUP`

### 1. Migration ausfuehren
Im Supabase Dashboard SQL Editor oder via CLI:
```bash
cd C:/Projekte/slack-task-manager
npx supabase db push
```

### 2. Edge Function deployen
```bash
cd C:/Projekte/slack-task-manager
npx supabase functions deploy memory-manager --no-verify-jwt
```

### 3. Testen
```bash
# Session laden (sollte leeres Ergebnis zurueckgeben)
curl -s -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: openclaw" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager?action=load_session"

# Ersten Eintrag erstellen
curl -s -X POST -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager" \
  -d '{"tier":"core","category":"context","title":"Memory System","content":"Persistent Memory installiert am 2026-02-26","tags":["infrastructure"]}'
```

### 4. Skill installieren
Ordner `persistent-memory` kopieren nach:
- Cowork Skills: Ueber die Cowork-Oberflaeche hinzufuegen
- Claude Code: `C:/Users/Anwender/.claude/skills/`

### 5. Backup einrichten
```bash
cd C:/Projekte/memory-backups
copy .env.example .env
# .env editieren und API_SECRET eintragen
python backup_memory.py
```

## Dateien

```
C:/Projekte/
├── persistent-memory/
│   ├── SKILL.md              # Skill-Anweisungen fuer Claude
│   └── README.md             # Diese Datei
├── memory-backups/
│   ├── backup_memory.py      # Backup-Script
│   ├── .env.example          # Vorlage fuer Konfiguration
│   └── memory_backup_*.json  # Generierte Backups
└── slack-task-manager/
    └── supabase/
        ├── migrations/
        │   └── 20260226000000_memory_tables.sql
        └── functions/
            └── memory-manager/
                └── index.ts
```

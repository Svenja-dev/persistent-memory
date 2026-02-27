# AGENTS.md

Entwicklungsrichtlinien fuer AI-Assistenten die an diesem Projekt arbeiten.

## Projekt-Kontext

Persistent Memory System: REST-API auf Supabase fuer projektuebergreifendes Wissen. Drei Tabellen (core, active, sessions), eine Edge Function (Deno/TypeScript), automatisches Cleanup via pg_cron.

## Kritische Regeln

1. **Keine Secrets im Code.** API_SECRET und alle Client-Secrets werden ausschliesslich ueber `supabase secrets set` gesetzt. Niemals in Quellcode, config.toml oder Commits.

2. **Kein PII speichern.** Das Memory-System darf keine personenbezogenen Daten enthalten. Nur technische Entscheidungen, Patterns und Arbeitsstaende.

3. **Schema-Aenderungen nur via Migration.** Keine manuellen SQL-Aenderungen im Dashboard. Neue Migration-Datei erstellen mit Zeitstempel-Prefix `YYYYMMDDHHMMSS_beschreibung.sql`.

4. **Edge Function hat eigene Auth.** Die Funktion wird mit `--no-verify-jwt` deployt. Die Authentifizierung laeuft ueber die eigene Bearer-Token-Logik in `validateApiKey()`. Supabase Auth ist nicht im Einsatz.

5. **Soft-Delete fuer Active.** `memory_active`-Eintraege werden nie hart geloescht, sondern mit `resolved=true` markiert. pg_cron raeumt nach 30 Tagen auf.

## Architektur-Entscheidungen

| Entscheidung | Begruendung |
|-------------|-------------|
| Supabase statt eigener DB | Bestehende Infrastruktur, Edge Functions, pg_cron inklusive |
| 3 Tabellen statt 1 | Unterschiedliche Retention, Schemas und Query-Patterns |
| Bearer Token statt JWT | Einfachheit, kein User-Management noetig |
| `ILIKE` statt `tsvector` | Ausreichend fuer erwartetes Datenvolumen (<10k Eintraege) |
| Deno Edge Function | Supabase-Standard, kein Build-Schritt, TypeScript nativ |

## Deployment-Workflow

```bash
# 1. Aenderungen vornehmen (Migrations, Edge Function)
# 2. Lokal testen (supabase functions serve)
# 3. Deployen:
cd persistent-memory
supabase db push                                      # Migrations
supabase functions deploy memory-manager --no-verify-jwt  # Edge Function
```

Deployment-Ziel: Supabase-Projekt `naatzputlsusiiczltzp`.

## Dateistruktur

- `supabase/migrations/` - Autoritativ. Wird von `supabase db push` ausgefuehrt.
- `supabase/functions/memory-manager/index.ts` - Autoritativ. Wird deployt.
- `edge-function/index.ts` - Quellkopie (Referenz). Muss manuell synchron gehalten werden.
- `supabase-migrations/` - Quellkopien (Referenz). Muss manuell synchron gehalten werden.

Bei Aenderungen immer zuerst die Dateien unter `supabase/` aendern und dann die Kopien aktualisieren.

## Haeufige Aufgaben

### Neuen Client hinzufuegen

1. Neue Env-Variable in `CLIENT_SECRET_ENV` in `index.ts` hinzufuegen
2. `VALID_CLIENTS` wird automatisch aktualisiert (leitet sich von `CLIENT_SECRET_ENV` ab)
3. Secret setzen: `supabase secrets set API_SECRET_NEUER_CLIENT=...`
4. Edge Function redeployen

### Neue Kategorie hinzufuegen

1. `ALTER TABLE` Migration erstellen die den CHECK-Constraint ersetzt
2. Dokumentation in SKILL.md und ARCHITECTURE.md aktualisieren

### Neues Tool (memory_sessions) hinzufuegen

1. Migration analog zu `20260226000002_add_openclaw_tool.sql`
2. CHECK-Constraint auf `memory_sessions.tool` erweitern

## Code-Konventionen

- TypeScript (Deno) fuer Edge Functions
- SQL-Migrations mit Kommentar-Header (Beschreibung und Migrations-ID)
- Deutsche Kommentare in SQL und Dokumentation
- Englische Variablen- und Funktionsnamen im Code
- Kein Linting-Setup (Projekt ist zu klein, Supabase bringt keins mit)

## Testen

Kein automatisiertes Test-Framework. Validierung erfolgt manuell:

```bash
# Session laden
curl -s -H "Authorization: Bearer $API_SECRET" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager?action=load_session"

# Eintrag erstellen
curl -s -X POST -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager" \
  -d '{"tier":"core","category":"context","title":"Test","content":"Testeintrag","tags":["test"]}'

# Suchen
curl -s -H "Authorization: Bearer $API_SECRET" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager?action=search&q=test"
```

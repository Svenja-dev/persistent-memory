# Vector Search Deploy-Anleitung

## Was sich aendert

- Neue Spalte `embedding` auf memory_core und memory_active (nullable, bricht nichts)
- Neue SQL-Funktionen: `search_memory_semantic()` und `search_memory_hybrid()`
- Edge Function: Generiert automatisch Embeddings beim Schreiben (wenn OPENAI_API_KEY gesetzt)
- Neuer Suchparameter: `?semantic=true` fuer Vector Search
- Backfill-Endpoint fuer bestehende Eintraege

Alles ist abwaertskompatibel. Ohne OPENAI_API_KEY funktioniert alles wie bisher.

---

## Schritt 1: pgvector Extension aktivieren (Supabase Dashboard)

1. Oeffne https://supabase.com/dashboard
2. Projekt auswaehlen
3. Database -> Extensions
4. Suche nach "vector"
5. Klicke "Enable"

## Schritt 2: Migration ausfuehren (SQL Editor)

1. Im Dashboard: SQL Editor -> New Query
2. Kopiere den Inhalt von:
   `supabase/migrations/20260318000000_add_vector_search.sql`
3. Ausfuehren (Run)
4. Sollte ohne Fehler durchlaufen

## Schritt 3: OPENAI_API_KEY als Secret setzen

1. Im Dashboard: Edge Functions -> memory-manager -> Settings (oder Project Settings -> Edge Functions)
2. Neues Secret: `OPENAI_API_KEY` = dein OpenAI API Key
3. Speichern

Kosten: text-embedding-3-small kostet $0.02 pro 1M Tokens.
Bei 50 Eintraegen/Tag mit je ~200 Woertern = ~$0.15/Monat.

## Schritt 4: Edge Function redeployen

### Option A: Supabase CLI (empfohlen)

```bash
cd C:\Projekte\persistent-memory
supabase functions deploy memory-manager --no-verify-jwt
```

### Option B: Dashboard

1. Edge Functions -> memory-manager
2. Code ersetzen mit dem neuen `index.ts`
3. Deploy

## Schritt 5: Testen

### Test 1: Neuen Eintrag schreiben (sollte Embedding generieren)

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager" \
  -d '{
    "tier": "active",
    "project": "test",
    "category": "learning",
    "title": "Vector Search Test",
    "content": "Dies ist ein Test ob Embeddings automatisch generiert werden.",
    "tags": ["test", "vector-search"]
  }'
```

Erwartete Antwort: `"embedding_generated": true`

### Test 2: Semantische Suche

```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager?action=search&q=Embedding+testen&semantic=true"
```

Erwartete Antwort: `"search_type": "semantic"`, der Test-Eintrag sollte gefunden werden.

### Test 3: Bestehende Suche funktioniert noch

```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager?action=search&q=test"
```

Sollte wie bisher funktionieren (ILIKE, `"search_type": "text"`).

## Schritt 6: Backfill bestehender Eintraege (optional)

Fuer bestehende Memory-Eintraege ohne Embedding:

```bash
# Core-Eintraege (max 50 pro Aufruf)
curl -s -X POST \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager" \
  -d '{"action": "backfill_embeddings", "tier": "core"}'

# Active-Eintraege
curl -s -X POST \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager" \
  -d '{"action": "backfill_embeddings", "tier": "active"}'
```

Mehrfach ausfuehren bis `"processed": 0`.

---

## Rueckbau (falls noetig)

Die Spalten und Funktionen entfernen, ohne bestehende Daten zu beruehren:

```sql
DROP FUNCTION IF EXISTS search_memory_semantic;
DROP FUNCTION IF EXISTS search_memory_hybrid;
DROP INDEX IF EXISTS idx_memory_core_embedding;
DROP INDEX IF EXISTS idx_memory_active_embedding;
ALTER TABLE memory_core DROP COLUMN IF EXISTS embedding;
ALTER TABLE memory_active DROP COLUMN IF EXISTS embedding;
```

Edge Function: Alte Version aus Git wiederherstellen und redeployen.

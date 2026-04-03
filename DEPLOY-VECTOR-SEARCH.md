# Vector Search Deploy-Anleitung

> **Umgebungsvariable**: `MEMORY_API_URL` ist standardmaessig
> `https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager`.
> Alle curl-Beispiele nutzen `$MEMORY_API_URL` -- stelle sicher, dass die Variable gesetzt ist,
> oder ersetze sie durch die vollstaendige URL.

## Was sich aendert

- Neue Spalte `embedding` auf memory_core und memory_active (nullable, bricht nichts)
- Neue SQL-Funktionen: `search_memory_semantic()` und `search_memory_hybrid()`
- Edge Function: Generiert automatisch Embeddings beim Schreiben (wenn OPENAI_API_KEY gesetzt)
- Neuer Suchparameter: `?semantic=true` fuer Vector Search
- Backfill-Endpoint fuer bestehende Eintraege

Alles ist abwaertskompatibel. Ohne OPENAI_API_KEY funktioniert alles wie bisher.

---

## Voraussetzungen

- **Supabase CLI** installiert und eingeloggt (`supabase login`)
- **Projektverknuepfung**: `supabase link --project-ref naatzputlsusiiczltzp` (einmalig)
- **OpenAI API Key** fuer Embedding-Generierung (optional, ohne Key funktioniert alles weiter)
- **Umgebungsvariablen** in der Shell:
  ```bash
  export API_SECRET="<dein-api-secret>"
  export MEMORY_API_URL="https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager"
  ```

---

## Schritt 1: Migration ausfuehren

Die Migration `supabase/migrations/20260318000000_add_vector_search.sql` aktiviert pgvector,
fuegt die Embedding-Spalten hinzu und erstellt die Suchfunktionen.

```bash
cd C:/Users/Anwender/projekte/persistent-memory
supabase db push
```

Das fuehrt alle noch nicht angewandten Migrations aus. Die Migration enthaelt
`CREATE EXTENSION IF NOT EXISTS vector`, daher muss pgvector NICHT manuell im Dashboard
aktiviert werden.

Pruefe nach dem Push, ob die Migration erfolgreich war:

```bash
supabase migration list
```

Die Migration `20260318000000_add_vector_search` sollte als applied erscheinen.

## Schritt 2: OPENAI_API_KEY als Secret setzen

```bash
supabase secrets set OPENAI_API_KEY=sk-...
```

Pruefe, ob das Secret gesetzt ist:

```bash
supabase secrets list
```

`OPENAI_API_KEY` sollte in der Liste erscheinen (Wert wird nicht angezeigt).

**Kosten**: text-embedding-3-small kostet $0.02 pro 1M Tokens.
Bei 50 Eintraegen/Tag mit je ~200 Woertern = ~$0.15/Monat.

## Schritt 3: Edge Function deployen

```bash
cd C:/Users/Anwender/projekte/persistent-memory
supabase functions deploy memory-manager --no-verify-jwt
```

## Schritt 4: Testen

### Test 1: Neuen Eintrag schreiben (sollte Embedding generieren)

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "$MEMORY_API_URL" \
  -d '{
    "tier": "active",
    "project": "test",
    "category": "learning",
    "title": "Vector Search Test",
    "content": "Dies ist ein Test ob Embeddings automatisch generiert werden.",
    "tags": ["test", "vector-search"]
  }'
```

Erwartete Antwort enthaelt:

```json
{
  "success": true,
  "action": "created",
  "tier": "active",
  "embedding_generated": true,
  "data": { ... }
}
```

Wenn `OPENAI_API_KEY` nicht gesetzt ist, kommt `"embedding_generated": false` -- das ist kein Fehler.

### Test 2: Semantische Suche

```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  "$MEMORY_API_URL?action=search&q=Embedding+testen&semantic=true"
```

Erwartete Antwort:

```json
{
  "success": true,
  "action": "search",
  "search_type": "semantic",
  "query": "Embedding testen",
  "count": 1,
  "results": [ ... ]
}
```

Der Test-Eintrag aus Test 1 sollte in den Ergebnissen erscheinen.

### Test 3: Bestehende Textsuche funktioniert noch

```bash
curl -s -H "Authorization: Bearer $API_SECRET" \
  "$MEMORY_API_URL?action=search&q=test"
```

Erwartete Antwort (ohne `?semantic=true`):

```json
{
  "success": true,
  "action": "search",
  "search_type": "text",
  "query": "test",
  "count": 1,
  "results": [ ... ]
}
```

## Schritt 5: Backfill bestehender Eintraege (optional)

Fuer bestehende Memory-Eintraege ohne Embedding. Verarbeitet max 50 Eintraege pro Aufruf.

```bash
# Core-Eintraege
curl -s -X POST \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "$MEMORY_API_URL" \
  -d '{"action": "backfill_embeddings", "tier": "core"}'

# Active-Eintraege
curl -s -X POST \
  -H "Authorization: Bearer $API_SECRET" \
  -H "Content-Type: application/json" \
  "$MEMORY_API_URL" \
  -d '{"action": "backfill_embeddings", "tier": "active"}'
```

Erwartete Antwort:

```json
{
  "success": true,
  "action": "backfill_embeddings",
  "tier": "core",
  "processed": 12,
  "errors": 0
}
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

Edge Function: Alte Version aus Git wiederherstellen und redeployen:

```bash
git checkout main -- supabase/functions/memory-manager/
supabase functions deploy memory-manager --no-verify-jwt
```

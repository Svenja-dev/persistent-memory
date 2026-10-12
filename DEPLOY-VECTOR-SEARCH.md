# Optionale Vektorsuche

Die Basisinstallation aus [README.md](README.md) enthaelt die SQL-Strukturen fuer Text-, semantische und hybride Suche. Ohne `OPENAI_API_KEY` funktionieren Speicherung und Textsuche. Fuer diese Funktionen ist kein kostenpflichtiger Modellzugang erforderlich.

## Datenfluss vor dem Aktivieren pruefen

Ein serverseitiger `OPENAI_API_KEY` aktiviert Embeddings mit `text-embedding-3-small` und 1536 Dimensionen. Texte aus Core, Active und Improvements werden bereits beim Anlegen und bei Textaenderungen an OpenAI gesendet; semantische Suchanfragen ebenfalls. Sessions bleiben per Textsuche erreichbar; der semantische API-Modus liefert keine Sessions. Die IT muss diesen zusaetzlichen Empfaenger und die erlaubten Datenklassen freigeben. Kosten und Vertragsbedingungen sind anhand des verwendeten Anbieter-Kontos zu pruefen; diese Anleitung verspricht keine festen Preise.

## Konfigurieren und pruefen

1. Den freigegebenen Repository-Stand einschliesslich aller SQL-Migrationen auf das ausdruecklich gewaehlte Projekt installieren. Insbesondere die Migration `20261010000000_professional_memory_contract.sql` muss vor der neuen Edge Function laufen.
2. `OPENAI_API_KEY` ueber die Secret-Verwaltung des gewaehlten Supabase-Projekts bereitstellen. Keine API-Keys in Kommando-History, Git, Skill-Pakete oder Chat kopieren. Das Deployment-Verfahren und die externe Env-Datei sind in README beschrieben.
3. Mit einem normalen Client und synthetischen Daten einen Core-, Active- oder Improvement-Eintrag schreiben; die Antwort auf Erfolg und `embedding_generated` pruefen. Ein Providerfehler darf nicht mit einem erfolgreichen Embedding verwechselt werden.
4. Die gleiche Testnotiz per Textsuche und mit `semantic=true` suchen. Der Rueckgabewert `search_type` zeigt den tatsaechlich verwendeten Suchweg; ein Fallback ist kein Beleg fuer funktionierende semantische Suche.

Beispiel fuer Bash mit bereits bereitgestelltem `MEMORY_API_URL`, `API_SECRET` und `MEMORY_CLIENT`:

```bash
curl --fail --silent --show-error --max-time 30 --get \
  -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: $MEMORY_CLIENT" \
  --data-urlencode 'action=search' \
  --data-urlencode 'project=installationstest' \
  --data-urlencode 'q=synthetische Testnotiz' \
  --data-urlencode 'semantic=true' "$MEMORY_API_URL"
```

## Bestehende Eintraege nachberechnen

Backfill ist eine ausdrueckliche Administrationsaktion: Er uebertraegt vorhandene Texte an den Embedding-Anbieter. Erst nach Freigabe und mit geprueftem Ziel aufrufen:

```bash
curl --fail --silent --show-error --max-time 120 \
  -H "Authorization: Bearer $API_SECRET" \
  -H "X-Memory-Client: $MEMORY_CLIENT" \
  -H 'Content-Type: application/json' \
  --data-binary '{"action":"backfill_embeddings","tier":"core"}' \
  "$MEMORY_API_URL"
```

Der Backfill-Endpoint unterstuetzt `core` und `active` und verarbeitet hoechstens 50 Eintraege pro Aufruf. Bei Fehlern stoppen und die Ursache klaeren; nur bei erfolgreichen Batches mit Fortschritt wiederholen. Nicht unbegrenzt gegen einen fehlerhaften Provider laufen lassen. Nach einem Restore sind Embeddings leer. Core und Active koennen per Backfill nachberechnet werden; Improvements bleiben per Textsuche erreichbar und erhalten bei einer spaeteren regulaeren Textbearbeitung ein neues Embedding. Einen Improvement-Backfill bietet diese Version nicht.

## Deaktivieren

Zum Stoppen neuer Anbieteraufrufe `OPENAI_API_KEY` in der Secret-Verwaltung des Zielprojekts entfernen und pruefen, dass die laufende Function diese Konfiguration verwendet. Vorhandene Embeddings bleiben in der Datenbank; ein spaeteres Textupdate ohne Anbieter invalidiert das alte Embedding. Die Basissuche bleibt verfuegbar. Schema, sichere RPC-Rechte und Migrationen muessen dafuer nicht zurueckgesetzt werden. Eine vollstaendige Datenloeschung ist eine separate, ausdruecklich freizugebende Operation.

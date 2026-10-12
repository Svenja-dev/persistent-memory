#!/usr/bin/env bash
# test-payloads.sh - Regressionstests fuer die Fehlerbehandlung der Edge Function memory-manager.
#
# Aufruf (Konfiguration ausschliesslich aus der Prozessumgebung, keine Suche nach Secret-Dateien):
#   export MEMORY_API_URL=https://<project>.supabase.co/functions/v1/memory-manager
#   export API_SECRET=<normaler Client-Schluessel>
#   export MEMORY_CLIENT=api            # optional; muss zum Schluessel passen
#   bash scripts/test-payloads.sh
#
# Legt synthetische Testeintraege im Projekt "__regtest__" an und loescht sie wieder.
# Exit 0, wenn alle erwarteten HTTP-Statuscodes stimmen, sonst 1.

set -u

if [ -z "${MEMORY_API_URL:-}" ]; then
  echo "FEHLER: MEMORY_API_URL ist nicht gesetzt. Beispiel:"
  echo "  export MEMORY_API_URL=https://<your-project>.supabase.co/functions/v1/memory-manager"
  exit 2
fi

if [ -z "${API_SECRET:-}" ]; then
  echo "SKIP: API_SECRET ist nicht gesetzt"
  exit 0
fi

CLIENT_HEADER=()
if [ -n "${MEMORY_CLIENT:-}" ]; then
  CLIENT_HEADER=(-H "X-Memory-Client: ${MEMORY_CLIENT}")
fi

BODY_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE"' EXIT

PASS=0
FAIL=0
CREATED_IDS=()

run_test() {
  local name="$1"
  local expected="$2"
  local payload="$3"
  local actual
  actual=$(curl -s -o "$BODY_FILE" -w "%{http_code}" --max-time 30 \
    -X POST -H "Authorization: Bearer $API_SECRET" "${CLIENT_HEADER[@]}" \
    -H "Content-Type: application/json" \
    "$MEMORY_API_URL" \
    -d "$payload")
  if [ "$actual" = "$expected" ]; then
    echo "PASS [$actual] $name"
    PASS=$((PASS + 1))
    if [ "$expected" = "200" ]; then
      local id tier
      id=$(grep -oE '"id":"[a-f0-9-]{36}"' "$BODY_FILE" | head -1 | sed -E 's/.*"([a-f0-9-]{36})".*/\1/')
      tier=$(grep -oE '"tier":"[a-z]+"' "$BODY_FILE" | head -1 | sed -E 's/.*"([a-z]+)".*/\1/')
      [ -n "$id" ] && [ -n "$tier" ] && CREATED_IDS+=("${tier}:${id}")
    fi
  else
    echo "FAIL [erwartet=$expected tatsaechlich=$actual] $name"
    echo "  body: $(head -c 300 "$BODY_FILE")"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== memory-manager Payload-Regressionstests ==="
echo "URL: $MEMORY_API_URL"
echo

# Erfolgsfaelle
run_test "core gueltig" 200 '{"tier":"core","project":"__regtest__","category":"preference","title":"regression test","content":"x","tags":["_regtest"],"importance":"low"}'
run_test "active gueltig" 200 '{"tier":"active","project":"__regtest__","category":"work_state","title":"regression test","content":"x","tags":["_regtest"],"priority":"low"}'
run_test "improvements gueltig" 200 '{"tier":"improvements","project":"__regtest__","title":"regression test improvement","category":"workflow","status":"experimenting","introduced_at":"2026-04-22","next_step":"initial test","tags":["_regtest"]}'

# Validierungsfehler (muessen 4xx sein, nicht 500)
run_test "unbekannte Felder werden abgewiesen" 400 '{"tier":"active","project":"__regtest__","category":"work_state","title":"regression test","content":"x","extra_unknown":"x","metadata":{"foo":"bar"}}'
run_test "fremdes Tier-Feld wird abgewiesen" 400 '{"tier":"core","project":"__regtest__","category":"preference","title":"regression test","content":"x","priority":"low"}'
run_test "category fehlt" 400 '{"tier":"active","project":"__regtest__","title":"regression test","content":"x"}'
run_test "title fehlt" 400 '{"tier":"active","project":"__regtest__","category":"work_state","content":"x"}'
run_test "content fehlt" 400 '{"tier":"active","project":"__regtest__","category":"work_state","title":"regression test"}'
run_test "ungueltige priority" 400 '{"tier":"active","project":"__regtest__","category":"work_state","title":"regression test","content":"x","priority":"URGENT"}'
run_test "ungueltige active-Kategorie" 400 '{"tier":"active","project":"__regtest__","category":"bogus_cat","title":"regression test","content":"x"}'
run_test "ungueltige core-Kategorie" 400 '{"tier":"core","project":"__regtest__","category":"work_state","title":"regression test","content":"x"}'
run_test "tags als String" 400 '{"tier":"active","project":"__regtest__","category":"work_state","title":"regression test","content":"x","tags":"notanarray"}'
run_test "ungueltige importance" 400 '{"tier":"core","project":"__regtest__","category":"preference","title":"regression test","content":"x","importance":"SUPER_HIGH"}'
run_test "Zeitstempel von normalen Clients abgewiesen" 400 '{"tier":"core","project":"__regtest__","category":"preference","title":"regression test","content":"x","created_at":"2026-01-01T00:00:00Z"}'
run_test "unbekanntes Tier" 400 '{"tier":"bogus"}'
run_test "Tier fehlt" 400 '{}'
run_test "improvements ohne category" 400 '{"tier":"improvements","project":"__regtest__","title":"x","status":"experimenting"}'
run_test "improvements ungueltige category" 400 '{"tier":"improvements","project":"__regtest__","title":"x","category":"bogus","status":"experimenting"}'
run_test "improvements ungueltiger status" 400 '{"tier":"improvements","project":"__regtest__","title":"x","category":"workflow","status":"bogus"}'
run_test "restore ohne Restore-Rolle" 403 '{"tier":"core","action":"restore","record":{}}'

# Aufraeumen: core wird geloescht, active als erledigt markiert, improvements auf retired gesetzt
echo
echo "=== Aufraeumen ==="
for entry in "${CREATED_IDS[@]}"; do
  tier="${entry%%:*}"
  id="${entry##*:}"
  curl -s --max-time 30 -X DELETE -H "Authorization: Bearer $API_SECRET" "${CLIENT_HEADER[@]}" \
    "$MEMORY_API_URL?tier=$tier&id=$id" > /dev/null
  echo "Bereinigt $tier/$id"
done

echo
echo "=== Zusammenfassung ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

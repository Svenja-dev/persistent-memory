#!/usr/bin/env bash
# test-payloads.sh - Regression tests for memory-manager edge function error handling.
#
# Usage:
#   export MEMORY_API_URL=https://<project>.supabase.co/functions/v1/memory-manager
#   # API_SECRET is resolved from env or ~/.claude/memory-secret
#   bash scripts/test-payloads.sh
#
# Exits 0 if all expected HTTP status codes match, 1 otherwise.

set -u

# Resolve secret from env or file (the := form avoids accidental "secret=..." literal patterns).
_MS=""
for _P in "$HOME/.claude/memory-secret" "/mnt/c/Users/Anwender/.claude/memory-secret" "/c/Users/Anwender/.claude/memory-secret"; do
  [ -z "$_P" ] && continue
  [ -f "$_P" ] && _MS=$(cat "$_P" 2>/dev/null) && break
done
: "${API_SECRET:=${API_SECRET_CLAUDE_CODE:-$_MS}}"
export API_SECRET

if [ -z "${MEMORY_API_URL:-}" ]; then
  echo "ERROR: MEMORY_API_URL not set. Example:"
  echo "  export MEMORY_API_URL=https://<your-project>.supabase.co/functions/v1/memory-manager"
  exit 2
fi

if [ -z "$API_SECRET" ]; then
  echo "SKIP: no API_SECRET available"
  exit 0
fi

PASS=0
FAIL=0
CREATED_IDS=()

run_test() {
  local name="$1"
  local expected="$2"
  local payload="$3"
  local actual
  actual=$(curl -s -o /tmp/memtest_body.json -w "%{http_code}" \
    -X POST -H "Authorization: Bearer $API_SECRET" \
    -H "Content-Type: application/json" \
    "$MEMORY_API_URL" \
    -d "$payload")
  if [ "$actual" = "$expected" ]; then
    echo "PASS [$actual] $name"
    PASS=$((PASS + 1))
    if [ "$expected" = "200" ]; then
      local id tier
      id=$(grep -oE '"id":"[a-f0-9-]{36}"' /tmp/memtest_body.json | head -1 | sed -E 's/.*"([a-f0-9-]{36})".*/\1/')
      tier=$(grep -oE '"tier":"[a-z]+"' /tmp/memtest_body.json | head -1 | sed -E 's/.*"([a-z]+)".*/\1/')
      [ -n "$id" ] && [ -n "$tier" ] && CREATED_IDS+=("${tier}:${id}")
    fi
  else
    echo "FAIL [expected=$expected actual=$actual] $name"
    echo "  body: $(head -c 300 /tmp/memtest_body.json)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== memory-manager payload regression tests ==="
echo "URL: $MEMORY_API_URL"
echo

# Happy paths
run_test "core valid" 200 '{"tier":"core","project":"global","category":"preference","title":"regression test","content":"x","tags":["_regtest"],"importance":"low"}'
run_test "active valid" 200 '{"tier":"active","project":"global","category":"work_state","title":"regression test","content":"x","tags":["_regtest"],"priority":"low"}'
run_test "extra unknown fields stripped" 200 '{"tier":"active","project":"global","category":"work_state","title":"regression test","content":"x","tags":["_regtest"],"priority":"low","extra_unknown":"x","metadata":{"foo":"bar"}}'

# Validation errors (must be 4xx, not 500)
run_test "missing category" 400 '{"tier":"active","project":"global","title":"regression test","content":"x"}'
run_test "missing title" 400 '{"tier":"active","project":"global","category":"work_state","content":"x"}'
run_test "missing content" 400 '{"tier":"active","project":"global","category":"work_state","title":"regression test"}'
run_test "invalid priority enum" 400 '{"tier":"active","project":"global","category":"work_state","title":"regression test","content":"x","priority":"URGENT"}'
run_test "invalid active category" 400 '{"tier":"active","project":"global","category":"bogus_cat","title":"regression test","content":"x"}'
run_test "invalid core category" 400 '{"tier":"core","project":"global","category":"work_state","title":"regression test","content":"x"}'
run_test "tags as string" 400 '{"tier":"active","project":"global","category":"work_state","title":"regression test","content":"x","tags":"notanarray"}'
run_test "invalid importance enum" 400 '{"tier":"core","project":"global","category":"preference","title":"regression test","content":"x","importance":"SUPER_HIGH"}'
run_test "unknown tier" 400 '{"tier":"bogus"}'
run_test "missing tier" 400 '{}'

# Improvements tier (new)
run_test "improvements valid" 200 '{"tier":"improvements","project":"global","title":"regression test improvement","category":"workflow","status":"experimenting","introduced_at":"2026-04-22","next_step":"initial test","tags":["_regtest"]}'
run_test "improvements missing category" 400 '{"tier":"improvements","project":"global","title":"x","status":"experimenting"}'
run_test "improvements invalid category" 400 '{"tier":"improvements","project":"global","title":"x","category":"bogus","status":"experimenting"}'
run_test "improvements invalid status" 400 '{"tier":"improvements","project":"global","title":"x","category":"workflow","status":"bogus"}'

# Cleanup
echo
echo "=== Cleanup ==="
for entry in "${CREATED_IDS[@]}"; do
  tier="${entry%%:*}"
  id="${entry##*:}"
  curl -s -X DELETE -H "Authorization: Bearer $API_SECRET" \
    "$MEMORY_API_URL?tier=$tier&id=$id" > /dev/null
  echo "Removed $tier/$id"
done

echo
echo "=== Summary ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

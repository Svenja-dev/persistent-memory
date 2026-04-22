# Persistent Memory Scripts

## test-payloads.sh

Regression test for memory-manager edge function error handling.

Usage:

    export MEMORY_API_URL=https://<project>.supabase.co/functions/v1/memory-manager
    # API_SECRET is resolved from env or ~/.claude/memory-secret
    bash scripts/test-payloads.sh

Exits 0 if all expected HTTP status codes match, 1 otherwise.

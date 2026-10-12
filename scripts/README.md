# Persistent Memory Scripts

## build_skill.py

Baut das reproduzierbare Skill-Paket `dist/persistent-memory.zip` aus genau `SKILL.md` und `LICENSE`. Siehe [README.md](../README.md#skill-sicher-installieren).

    python -B scripts/build_skill.py

## test-payloads.sh

Regressionstest fuer die Fehlerbehandlung der Edge Function `memory-manager` gegen eine laufende Instanz. Es werden synthetische Eintraege im Projekt `__regtest__` angelegt und anschliessend wieder entfernt (DELETE auf `active` markiert als erledigt, auf `improvements` als `retired`).

Konfiguration kommt ausschliesslich aus der Prozessumgebung; das Skript sucht keine Secret-Dateien:

    export MEMORY_API_URL=https://<project>.supabase.co/functions/v1/memory-manager
    export API_SECRET=<normaler Client-Schluessel>
    export MEMORY_CLIENT=api        # optional, muss zum Schluessel passen
    bash scripts/test-payloads.sh

Exit 0, wenn alle erwarteten HTTP-Statuscodes stimmen, sonst 1. Ohne `API_SECRET` wird der Lauf uebersprungen (Exit 0), ohne `MEMORY_API_URL` abgebrochen (Exit 2).

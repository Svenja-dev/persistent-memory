# Review-Bericht: Persistent Memory System

**Datum:** 26. Februar 2026
**Projekt:** Persistent Memory (Supabase + Edge Function + Cowork Skill)

---

## 1. Zusammenfassung

Dieses Dokument bewertet das externe Review des Persistent Memory Systems. Das System besteht aus drei Supabase-Tabellen (memory_core, memory_active, memory_sessions), einer Deno Edge Function (memory-manager) und einem Backup-Script.

Das Review identifiziert vier kritische Findings und sieben Verbesserungsvorschlaege.

**Ergebnis der Gegenpruefung:** 2 von 4 Findings sind echte Bugs. 3 von 7 Vorschlaegen haben Mehrwert. Der Rest ist entweder falsch, verfrueht oder ueberdimensioniert.

---

## 2. Bewertung der kritischen Findings

| #   | Finding                                          | Bewertung                                       | Aktion  |
| --- | ------------------------------------------------ | ----------------------------------------------- | ------- |
| 1   | DB-Fehler in load_session/backup nicht behandelt | **STIMMT** - Echter Bug                         | Fixen   |
| 2   | Backup auf 100 Sessions limitiert                | **STIMMT** - Unvollstaendiges Backup            | Fixen   |
| 3   | OpenClaw nicht im Schema als tool                | **KORREKT** - Noch nicht relevant, geplant      | Spaeter |
| 4   | cron_logs Tabelle fehlt in Migration             | **FALSCH** - Existiert seit initialer Migration | Keine   |

### 2.1 Finding 1: Fehlerbehandlung (BESTAETIGT)

Die Funktion `handleLoadSession` fuehrt drei parallele Queries aus (core, active, sessions). Keiner der Rueckgabewerte wird auf `.error` geprueft. Wenn eine Query fehlschlaegt, gibt die Funktion trotzdem `success: true` zurueck, mit leeren Arrays statt einer Fehlermeldung. Das gleiche Problem existiert in `handleBackup`.

**Auswirkung:** Der aufrufende Client (Claude) erhaelt ein scheinbar erfolgreiches Ergebnis und arbeitet mit unvollstaendigen Daten weiter, ohne es zu merken. Bei load_session ist das besonders kritisch, weil fehlende Core-Eintraege zu Kontext-Verlust fuehren.

**Fix:** Fehler-Check nach `Promise.all` einfuegen. Wenn mindestens eine Query fehlschlaegt, `success: false` zurueckgeben mit Details welche Tabelle betroffen ist.

### 2.2 Finding 2: Backup-Limit (BESTAETIGT)

Das Backup exportiert maximal 100 Sessions (`.limit(100)` in Zeile 101). Core und Active werden zwar vollstaendig exportiert, aber die Sessions-Historie wird abgeschnitten.

**Auswirkung:** Aeltere Session-Zusammenfassungen gehen im Backup verloren. Kombiniert mit dem pg_cron Job der Sessions nach 90 Tagen loescht, sind Sessions zwischen Tag 90 und dem Backup-Zeitpunkt unwiederbringlich weg.

**Fix:** Limit auf 1000 erhoehen oder komplett entfernen. Bei erwarteten Datenmengen (wenige Hundert Sessions pro Jahr) ist Paginierung nicht noetig.

### 2.3 Finding 3: OpenClaw im Schema (KORREKT, NICHT AKUT)

Die CHECK-Constraint auf `memory_sessions.tool` erlaubt nur die Werte cowork, claude_code, api, other. OpenClaw ist nicht vorgesehen.

**Bewertung:** OpenClaw ist geplant, aber noch nicht im Einsatz. Die Schema-Aenderung ist eine einzeilige ALTER TABLE und kann umgesetzt werden wenn OpenClaw tatsaechlich angebunden wird. Jetzt schon aendern waere vorauseilend.

### 2.4 Finding 4: cron_logs Tabelle fehlt (FALSCH)

Das Review behauptet, die Tabelle `cron_logs` werde in der Cleanup-Migration referenziert, existiere aber nicht.

**Beweis:** Die Tabelle wird in der initialen Migration `20260101000000_initial_schema.sql` (Zeile 48-58) angelegt. Sie existiert seit dem ersten Deployment des slack-task-manager Projekts. Das Review hat nur die neuen Migrationen geprueft, nicht die bestehende Datenbankstruktur.

---

## 3. Bewertung der Verbesserungsvorschlaege

| #   | Vorschlag                                   | Bewertung                                                                 | Aufwand | Empfehlung   |
| --- | ------------------------------------------- | ------------------------------------------------------------------------- | ------- | ------------ |
| 1   | Hook-Automatisierung (Auto-Load/Save)       | Sinnvoll fuer Claude Code CLI. Cowork hat keine Hooks.                    | Mittel  | Ja, fuer CLI |
| 2   | OpenClaw-Adapter und Schema-Erweiterung     | Geplant, aber noch nicht spruchreif. Schema trivial.                      | Gering  | Spaeter      |
| 3   | pgvector Hybrid Search                      | Overkill bei unter 500 Eintraegen. ILIKE reicht.                          | Hoch    | Nein         |
| 4   | Zod/Valibot Input-Validierung               | Korrekte Praxis fuer oeffentliche APIs, nicht kritisch bei internem Tool. | Mittel  | Optional     |
| 5   | Separate Secrets pro Client                 | Guter Grundsatz. Aktuell ein Client. Relevant bei OpenClaw.               | Gering  | Spaeter      |
| 6   | Skill-Struktur aufteilen (references/)      | Sinnvoll bei mehreren Tools. Aktuell nur Cowork und CLI.                  | Gering  | Spaeter      |
| 7   | Backup mit gzip, Checksum, Verschluesselung | Bei wenigen KB voellig ueberdimensioniert.                                | Mittel  | Nein         |

### 3.1 Hook-Automatisierung

Der wertvollste Punkt des gesamten Reviews. Aktuell muss die CLAUDE.md-Anweisung dafuer sorgen, dass Memory geladen wird. Das ist fehleranfaellig.

**Claude Code CLI:** Unterstuetzt Hooks (PreToolUse, PostToolUse, SessionStart). Ein Hook-Script kann beim Session-Start automatisch `load_session` aufrufen und beim Ende eine Session-Zusammenfassung schreiben.

**Cowork:** Hat kein Hook-System. Der einzige Automatisierungspfad ist die CLAUDE.md-Anweisung. Nicht ideal, aber die bestmoegliche Loesung.

### 3.2 pgvector Hybrid Search

Semantische Suche via pgvector ist valide Technologie, aber fuer diesen Anwendungsfall ueberdimensioniert. Die Memory-Datenbank wird voraussichtlich unter 500 Eintraege haben. ILIKE-Suche ist schnell genug und liefert zuverlaessige Ergebnisse.

**Zusaetzlicher Aufwand:** pgvector erfordert ein Embedding-Modell, dessen API-Kosten, und Wartung der Embeddings bei jedem Schreibvorgang. Signifikanter Infrastruktur-Overhead fuer minimalen Nutzen.

### 3.3 Zod-Validierung und Security-Haertung

Input-Validierung mit Zod ist gute Praxis fuer oeffentliche APIs mit vielen Consumern. Bei einer internen Edge Function mit einem einzigen Consumer (Claude-Sessions) ist das Risiko von Malformed Input gering. Die bestehende Validierung (CHECK-Constraints in der DB, Tier-Pruefung im Code) reicht fuer den aktuellen Stand.

Separate Secrets pro Client werden relevant, wenn OpenClaw dazukommt.

### 3.4 Backup-Professionalisierung

gzip, Checksummen und Verschluesselung at rest sind Standard fuer Enterprise-Backups mit grossen Datenmengen und Compliance-Anforderungen. Die Memory-Backups sind wenige KB gross, enthalten keine personenbezogenen Daten, und werden ueber Google Drive gesichert, das selbst Verschluesselung at rest bietet. Kein Handlungsbedarf.

---

## 4. Empfohlene Massnahmen

| #   | Massnahme                                         | Begruendung                                | Prioritaet                      |
| --- | ------------------------------------------------- | ------------------------------------------ | ------------------------------- |
| 1   | Fehlerbehandlung in load_session und backup fixen | Echter Bug: success:true trotz DB-Fehler   | Hoch - sofort                   |
| 2   | Backup-Limit entfernen oder auf 1000 erhoehen     | Unvollstaendiges Backup ist kein Backup    | Hoch - sofort                   |
| 3   | Claude Code Hooks fuer Auto-Load/Save             | Groesster Hebel fuer Alltagsnutzung in CLI | Mittel - naechste Session       |
| 4   | OpenClaw als tool im Schema ergaenzen             | Triviale Schema-Aenderung, zukunftssicher  | Niedrig - wenn OpenClaw startet |

Massnahmen 1 und 2 sind echte Bugs und sollten sofort behoben werden. Massnahme 3 (Claude Code Hooks) ist der groesste Hebel fuer den Alltag. Massnahme 4 kann warten.

---

## 5. Gesamtbewertung des Reviews

Das Review ist handwerklich solide und hat zwei echte Bugs identifiziert, die ohne die Pruefung unentdeckt geblieben waeren. Das ist wertvoll.

Gleichzeitig zeigt es typische Muster einer automatisierten Code-Review: Es prueft Dateien isoliert (daher der falsche cron_logs-Befund), und es tendiert zu Best-Practice-Vorschlaegen die fuer groessere Systeme gedacht sind (pgvector, Zod, Enterprise-Backup). Fuer ein internes Tool mit einem Consumer und wenigen Hundert Eintraegen ist vieles davon Overengineering.

Der wertvollste Vorschlag (Hook-Automatisierung) wird im Review als Punkt 1 der Verbesserungen aufgefuehrt, aber nicht als kritisch markiert. Tatsaechlich ist es die Massnahme mit dem groessten Alltagsnutzen.

**Gesamturteil:** 2 von 4 kritischen Findings sind echt. 3 von 7 Verbesserungsvorschlaegen haben Mehrwert. Die uebrigen Punkte sind entweder falsch, verfrueht oder ueberdimensioniert fuer den aktuellen Stand.

---

## 6. Quellen-Bewertung

Das Review listet acht Quellen. Die Anthropic-Dokumentationen zu Memory und Hooks sind relevant und korrekt. Die Supabase-Dokumentation zu Hybrid Search und pgvector ist technisch korrekt, aber fuer unseren Anwendungsfall nicht relevant. Die OpenClaw-Dokumentation ist fuer die Zukunft nuetzlich.

**Fehlende Quelle:** Das Review hat die bestehende Migrationsdatei `20260101000000_initial_schema.sql` nicht beruecksichtigt, was zum falschen Finding 4 gefuehrt hat. Eine vollstaendige Review-Grundlage haette alle Migrationen einschliessen muessen.

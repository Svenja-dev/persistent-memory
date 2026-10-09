# Architektur

## Komponenten und Vertrauensgrenze

```text
Cowork / Claude Code / Codex / Backup / Restore
                  | HTTPS + Bearer + Client-Header
                  v
       Supabase Edge Function: memory-manager
                  | service_role (nur serverseitig)
                  v
 PostgreSQL: core / active / sessions / improvements
       | Such-RPCs, Snapshot-Export, Insert-only-Restore
       | pg_cron: begrenzte Aufbewahrung
```

Eine Instanz hat einen gemeinsamen Vertrauensbereich. Es gibt keine Nutzeridentitaet, keinen `owner_id`-Filter und keine Mandantentrennung. Mehrere persoenliche Nutzer erhalten getrennte, firmenverwaltete Supabase-Projekte. Client-Secrets erlauben getrennten Widerruf und beschraenkte Betriebsrollen; sie trennen keine Datensaetze. Projektfilter sind Komfortfilter.

## Datenmodell

Alle vier Tabellen haben UUID-IDs, Projektzuordnung, Tags und `created_at`. `project=null`, `global` und `shared` werden bei Projektabfragen mitgeladen. Ohne Filter kann der Client alle Projekte innerhalb seiner Instanz lesen.

| Tabelle | Inhalt | Lebenszyklus |
| --- | --- | --- |
| `memory_core` | `category`, `title`, `content`, `importance` | Dauerhaft; `updated_at` bei Updates |
| `memory_active` | `category`, `title`, `content`, `priority`, `resolved`, `resolved_at` | Offen oder erledigt; Cleanup 30 Tage nach Erledigung |
| `memory_sessions` | `session_id`, `tool`, `summary`, Arrays fuer Entscheidungen, Probleme und Dateien | Cleanup 90 Tage nach `created_at`; keine `updated_at`-Spalte |
| `memory_improvements` | `category`, `title`, `status`, `evidence`, `next_step`, `model_version_notes` | `experimenting`, `proven`, `retired`; dauerhaft |

Die zulaessigen Kategorien werden durch SQL-Constraints und API-Validierung gemeinsam durchgesetzt. Core umfasst auch `user_profile`, `user_values`, `work_style`, `communication`, `pain_points` und `workflow_preference`; diese Feldnamen autorisieren keine Speicherung personenbezogener Daten. Normale POST-Aufrufe erlauben nur tierspezifische Felder. `id` bedeutet Update eines vorhandenen Datensatzes, kein Upsert. Normale Clients duerfen Zeitstempel und Embeddings nicht setzen.

Der Server pflegt bei Active-Zustandswechseln `resolved_at`: Aufloesen setzt einen aktuellen Zeitpunkt, erneutes Oeffnen entfernt ihn. Erneutes Schreiben des unveraenderten Status darf die Aufbewahrungsfrist nicht verschieben. Restore verwendet dagegen den historischen Status und Zeitpunkt.

## Authentifizierung und Datenbankrechte

Die Edge Function verwendet eigene Bearer-Authentifizierung und wird mit `--no-verify-jwt` deployt. `SUPABASE_SERVICE_ROLE_KEY` bleibt serverseitig. Normale Clients `cowork`, `claude_code`, `openclaw` und `api` werden ihrem dedizierten `API_SECRET_*` zugeordnet; `api` ist auch der Codex-Client. Nur wenn das jeweilige Client-Secret fehlt, kann der Legacy-Schluessel `API_SECRET` fuer normale Clients greifen.

`API_SECRET_BACKUP` erlaubt ausschliesslich GET. `API_SECRET_RESTORE` erlaubt mit ausdruecklichem `X-Memory-Client: restore` einen Export und die Restore-Operation. Andere Schreiboperationen sind diesen Rollen verboten. Reservierte Rollen haben keinen Legacy-Fallback. Schluessel muessen pro Rolle verschieden sein; ein Backup-Schluessel bekommt durch Weglassen oder Aendern des Headers keine Schreibrechte.

Auf allen Memory-Tabellen ist RLS aktiv. Such-, Export- und Restore-Funktionen sind `SECURITY DEFINER` mit leerem festem `search_path` und vollqualifizierten Objektzugriffen. Ausfuehrungsrechte werden `PUBLIC`, `anon` und `authenticated` entzogen und nur `service_role` erteilt. Damit kann ein Supabase-Client die Edge-Authentifizierung nicht durch direkte RPC-Aufrufe umgehen. Diese Rechte und die Migrationen werden auf einer isolierten Datenbank geprueft; daraus folgt keine Aussage ueber manuelle Aenderungen an einer externen Installation.

## Kontext, Suche und Embeddings

`load_session` liefert bis zu 500 Core-, offene Active- und experimentierende Improvement-Eintraege sowie fuenf aktuelle Sessions. Jeder Block enthaelt `count`, `total_count`, `limit`, `truncated` und `data`; die Antwort kennzeichnet auch insgesamt abgeschnittenen Kontext. Pflichtabfragefehler brechen den Aufruf ab. Fuer fehlenden Kontext dient gezielte Suche; ein Session-Abruf ist kein vollstaendiger Export.

Textsuche durchsucht alle vier Schichten. Erledigte Active-Eintraege und retired Improvements sind ausgeschlossen. Core und Active verwenden Titel und Inhalt, Sessions die Zusammenfassung, Improvements Titel, Evidence, Next Step und Model Version Notes.

Semantische Suche verwendet optional pgvector und `text-embedding-3-small` (1536 Dimensionen) fuer Core, Active und Improvements. Sessions bleiben per Textsuche erreichbar; der semantische API-Modus liefert keine Sessions. Die SQL-Hybridfunktion kombiniert Text- und Vektoranteile, hat aber keinen eigenen API-Modus. Ohne serverseitigen `OPENAI_API_KEY` werden keine Texte fuer Embeddings uebertragen. Mit Schluessel entstehen Embeddings bereits bei Schreibvorgaengen; semantische Suchanfragen werden ebenfalls an OpenAI gesendet. Bei Text-Teilupdates wird der vollstaendige zusammengefuehrte Text neu eingebettet. Ohne funktionierenden Provider wird ein veraltetes Embedding entfernt. Providerfehler duerfen nicht unbemerkt alte Bedeutungen erhalten.

## Sicherung und Wiederherstellung

`export_memory_backup()` erzeugt einen einzigen konsistenten JSON-Snapshot. `schema_version=1`, `complete=true`, `exported_at` und vier `{count,data}`-Bloecke bilden den Exportvertrag. Es gibt keine PostgREST-Zeilenbegrenzung pro Tabelle und kein 100-Session-Limit. Embeddings werden als regenerierbare Daten weggelassen.

Der Python-Client validiert diesen Vertrag vor Speicherung und Retention. Das lokale Manifest ergaenzt `source_url`. Dateien erhalten eindeutige Namen und werden zuerst temporaer, dann atomar fertiggestellt. Ein Fehler erzeugt kein vermeintlich gueltiges Backup und keine anschliessende Bereinigung. Die 30-Tage-Bereinigung beruecksichtigt nur gueltige Sicherungen derselben Quelle.

`POST {action:"restore",tier,record}` ist ausschliesslich fuer die Restore-Rolle bestimmt. `restore_memory_record(text,jsonb)` erhaelt UUIDs, Originalzeitstempel sowie Lebenszyklusfelder und fuegt nur fehlende Datensaetze ein. Vorhandene UUIDs werden nie ueberschrieben. Wiederholung nach Teilfehlern erzeugt keine neuen Identitaeten. Der Client startet als Dry-run, validiert alle Daten vor dem Netzwerkzugriff und verlangt fuer ein abweichendes Ziel `--allow-different-target`. Alte ungepruefte Exportformate werden nicht automatisch als vollstaendige Backups akzeptiert.

## Migrationen und Betrieb

Alle Migrationen unter `supabase/migrations/` sind autoritativ. Die Migration `20261010000000_professional_memory_contract.sql` aktualisiert bestehende Installationen; die aeltere Cron-Bootstrap-Migration wurde zugleich fuer frische Installationen repariert. Migrationen muessen vor der neuen Edge Function laufen.

Die Installation aktiviert `vector` und `pg_cron`. Der PostgreSQL-Host muss `pg_cron` laden koennen (insbesondere `shared_preload_libraries`; bei Supabase bereitgestellt). Zwei Jobs bleiben:

| Job | UTC | Aktion |
| --- | --- | --- |
| `cleanup-memory-sessions` | Taeglich 03:00 | Sessions aelter als 90 Tage loeschen |
| `cleanup-memory-active-resolved` | Taeglich 03:05 | Active-Eintraege 30 Tage nach `resolved_at` loeschen |

Der ehemalige Statistikjob mit Verweis auf eine fremde `cron_logs`-Tabelle wird entfernt. Es gibt keine automatische Cloud-Synchronisierung von Backups. Monitoring, Secret-Rotation, Dateirechte und Wiederherstellungsproben liegen beim Betreiber. Fuer eine kuenftige gemeinsame Mehrnutzerinstanz waeren serverseitige Eigentumspruefungen in allen Operationen, benutzerbezogene Auditierung und passende Lastgrenzen gesondert zu implementieren.

## Quellen und Laufzeiten

- `supabase/functions/memory-manager/index.ts`: produktiver Einstieg; `handler.ts` enthaelt die injizierbare API-Logik. Die entsprechenden Dateien unter `edge-function/` sind synchron zu haltende Referenzkopien.
- `supabase/migrations/`: autoritative Migrationen; `supabase-migrations/` sind Referenzkopien.
- `backup/`: Python 3.11+, Backup-/Restore-Vertraege und Regressionstests.
- `scripts/build_skill.py`: ausschliesslich `SKILL.md` und `LICENSE` im reproduzierbaren ZIP.
- `tests/` und API-/SQL-Tests: deterministische Regression ohne bezahlten Modellzugang.

Installationsanleitung, Konfigurationsvariablen und Abnahmeablauf stehen in [README.md](README.md). Der Skill selbst enthaelt nur den begrenzten Client-Arbeitsablauf.

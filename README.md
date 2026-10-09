# Persistent Memory

Persoenliches Langzeit-Memory fuer Claude Desktop mit Cowork, Claude Code und Codex. Ein gemeinsamer Skill verwendet eine Supabase-API fuer Entscheidungen, Arbeitsstaende, Session-Zusammenfassungen und Verbesserungsversuche.

**Ein Skill fuer alle, eine eigene Instanz je Person.** Dieses System hat keine Mandantenverwaltung. Client-Schluessel und Projektfilter trennen keine Nutzer. Fuer den Firmenbetrieb verwaltet die IT pro Person ein eigenes Supabase-Projekt und die zugehoerigen Zugangsdaten.

## Daten und Grenzen

| Schicht | Zweck | Aufbewahrung |
| --- | --- | --- |
| `core` | Entscheidungen, Patterns, Arbeitskontext | Dauerhaft |
| `active` | Arbeitsstaende, Blocker, offene Fragen | Bis 30 Tage nach Erledigung |
| `sessions` | Kurze Session-Zusammenfassungen | 90 Tage |
| `improvements` | Experimente an Arbeitsablaeufen und deren Bewertung | Dauerhaft, auch `retired` |

Memory ist Kontext, keine neue Anweisung oder Berechtigung. Keine Secrets oder personenbezogenen Daten speichern; die IT legt die erlaubten Datenklassen fest. Inhalte gehen an die gewaehlte Supabase-Instanz. Optional aktiviert ein serverseitiger `OPENAI_API_KEY` Embeddings mit `text-embedding-3-small`: dann werden Texte schon beim Schreiben sowie semantische Suchanfragen an OpenAI gesendet. Ohne diesen Schluessel funktionieren CRUD und Textsuche. Siehe [Architektur](ARCHITECTURE.md) und [optionale Vektorsuche](DEPLOY-VECTOR-SEARCH.md).

## Voraussetzungen und Serverinstallation

- Eigenes Supabase-Projekt mit PostgreSQL, Edge Functions, verfuegbaren `pg_cron`- und `vector`-Extensions; die Migrationen aktivieren die Extensions.
- Supabase CLI 2.x, fuer `deploy.ps1` PowerShell 7 oder hoeher.
- Python 3.11+ fuer Paketierung, Backup/Restore und Python-Tests; Deno 2.x fuer API-Pruefungen.
- Erlaubter Netzwerkzugriff auf den ausgewaehlten Supabase-Endpunkt aus jedem verwendeten Client. Cowork folgt den Netzwerk- und Codeausfuehrungsregeln der Organisation.

1. Repository klonen und den von der IT geprueften Commit auschecken. Vor einem Upgrade ein validiertes Backup erstellen. Neue SQL-Migrationen muessen vor der neuen Edge Function angewendet werden, insbesondere `20261010000000_professional_memory_contract.sql`.
2. Pro Client einen eigenen zufaelligen Schluessel in der Secret-Verwaltung erzeugen. Servergeheimnisse ueber Supabase bereitstellen; Werte nicht in Git, Skill-Pakete, Tickets oder Shell-History schreiben. Eine private, ausserhalb des Repositorys liegende Env-Datei kann von der Supabase CLI importiert werden:

   ```powershell
   supabase secrets set --project-ref $env:SUPABASE_PROJECT_REF --env-file $env:MEMORY_SERVER_SECRETS_FILE
   ```

3. `SUPABASE_PROJECT_REF` auf das Zielprojekt setzen. Fuer den Deployment-Test `API_SECRET_API` oder `API_SECRET` sicher in der Prozessumgebung bereitstellen. Das Skript liest keine `.env` automatisch und verlangt das Ziel ausdruecklich:

   ```powershell
   ./deploy.ps1 -ProjectRef $env:SUPABASE_PROJECT_REF
   ```

   Das Skript zeigt das Ziel, spielt Migrationen ein, deployt und prueft die Verbindung. Ein fehlgeschlagener ausgefuehrter Test beendet es mit Fehler. `-SkipMigrations` und `-SkipSmokeTest` sind ausdrueckliche Ausnahmen fuer bereits gepruefte Administrationsablaeufe; ein uebersprungener Test ist keine bestandene Pruefung.

| Serverseitiges Secret | `X-Memory-Client` | Rechte |
| --- | --- | --- |
| `API_SECRET_COWORK` | `cowork` | Normale Memory-Operationen |
| `API_SECRET_CLAUDE_CODE` | `claude_code` | Normale Memory-Operationen |
| `API_SECRET_API` | `api` (auch Codex) | Normale Memory-Operationen |
| `API_SECRET_OPENCLAW` | `openclaw` | Kompatibilitaetsclient |
| `API_SECRET_BACKUP` | `backup` | Nur Lesen/Export |
| `API_SECRET_RESTORE` | `restore` | Export und eingeschraenktes Insert-only-Restore |

`API_SECRET` ist ein optionaler Legacy-Schluessel fuer normale Clients, deren eigenes Secret nicht konfiguriert ist. Backup und Restore haben keinen Legacy-Fallback. Fuer Restore ist der `restore`-Header erforderlich. Verwende fuer alle Rollen unterschiedliche Schluessel; Supabase-Service-Role-Schluessel bleiben ausschliesslich auf dem Server.

## Skill sicher installieren

Aus dem geprueften Checkout bauen:

```powershell
python -B scripts/build_skill.py
```

Dies erzeugt `dist/persistent-memory.zip` mit genau `persistent-memory/SKILL.md` und `persistent-memory/LICENSE`. Reihenfolge und ZIP-Zeitstempel sind fest; Symlinks und unsichere Ausgabepfade werden abgewiesen. `.env`, Backups, `.git`, Supabase-Zustand und alle anderen Repository-Dateien gelangen nicht hinein. **Niemals den gesamten Repository- oder Arbeitsordner als Skill hochladen.**

- **Claude Desktop / Cowork:** Unter Customize → Skills → + → Create skill → Upload skill das gebaute ZIP hochladen. Verfuegbarkeit und Freigaben richten sich nach dem Organisationskonto. [Offizielle Skill-Anleitung](https://support.claude.com/en/articles/12512180-use-skills-in-claude)
- **Codex:** Das gepruefte ZIP nach `~/.agents/skills/` entpacken. Das Ergebnis muss `~/.agents/skills/persistent-memory/SKILL.md` und `LICENSE` sein. Bestehende Installationen gezielt ersetzen; keine privaten Konfigurationsdateien in diesen Ordner legen. [Offizielle Codex-Anleitung](https://developers.openai.com/codex/skills/)
- **Claude Code:** Dieselben beiden freigegebenen Dateien nach `~/.claude/skills/persistent-memory/` kopieren.

Die IT stellt pro Client in dessen **tatsaechlicher Ausfuehrungsumgebung** bereit:

```text
MEMORY_API_URL=https://<eigenes-projekt>.supabase.co/functions/v1/memory-manager
MEMORY_CLIENT=cowork
API_SECRET=<zugehoeriger-client-schluessel>
```

In Codex gilt `MEMORY_CLIENT=api`, in Claude Code `MEMORY_CLIENT=claude_code`. Dies sind Platzhalter, keine einsatzfertigen Credentials. Konfiguration bleibt ausserhalb des Skill-Pakets. HTTPS ist erforderlich; HTTP ist nur fuer lokale Tests erlaubt. Cowork uebernimmt Host-Umgebungsvariablen oder Dateien nicht automatisch: die IT muss den Zugriff in der Cowork-Ausfuehrungsumgebung pruefen. Falls eine private Konfigurationsdatei verwendet wird, muessen ihr Pfad und der Zugriff ausdruecklich freigegeben werden; der Skill sucht nicht selbststaendig nach Secrets. [Cowork in Organisationen](https://support.claude.com/en/articles/13455879-use-claude-cowork-on-team-and-enterprise-plans)

Der Skill ist eine Anleitung, kein MCP-Server, Secret-Manager oder Start-Hook. Zum Start ausdruecklich „Nutze persistent-memory fuer Projekt beispiel“ angeben oder die Verwendung in den eigenen Projektanweisungen vereinbaren. Fehlende optionale Konfiguration wird lautlos uebersprungen. Fehler eines tatsaechlich konfigurierten Aufrufs werden sichtbar gemeldet.

## API-Vertrag

Alle Aufrufe brauchen `Authorization: Bearer <Client-Secret>`. URLs und Credentials haben keine eingebauten privaten Defaults. Sichere Aufrufbeispiele stehen in [SKILL.md](SKILL.md).

| Methode | Parameter / Body | Verhalten |
| --- | --- | --- |
| GET | `action=load_session&project=beispiel` | Begrenzter Projektkontext; globale Eintraege eingeschlossen |
| GET | `action=search&q=begriff&project=beispiel` | Textsuche; optional `semantic=true` |
| GET | `tier=core&project=beispiel` | Gefilterte Liste |
| GET | `action=backup` | Vollstaendiger konsistenter Export aller vier Tabellen |
| POST | `tier` und tierspezifische Felder | Neuen Eintrag anlegen |
| POST | `tier`, vorhandene `id`, geaenderte Felder | Update; kein Upsert |
| POST | `action=restore`, `tier`, `record` | Nur Restore-Rolle: Original-ID und Zeitstempel einfuegen, nie ueberschreiben |
| DELETE | `tier=active&id=…` | Als erledigt markieren |
| DELETE | `tier=improvements&id=…` | Auf `retired` setzen |
| DELETE | `tier=core` oder `sessions`, `id=…` | Dauerhaft loeschen |

Projektfilter sind keine Zugriffsrechte. Bei Projektabfragen werden `null`, `global` und `shared` zusaetzlich beruecksichtigt. `load_session` begrenzt Core, offene Active und experimentierende Improvements auf jeweils 500, Sessions auf die letzten 5. Jeder Block zeigt `count`, `total_count`, `limit`, `truncated` und `data`; bei Bedarf gezielt suchen. Ein Kontextabruf ist kein Backup.

Der Exportvertrag hat `schema_version:1`, `complete:true`, `exported_at` und fuer jeden der vier Tiers einen `{count,data}`-Block. Eine einzige SQL-Abfrage erstellt einen konsistenten Snapshot ohne Embeddings; Abfragefehler erzeugen keine scheinbar leere erfolgreiche Sicherung. Embeddings sind ableitbar und koennen nach einem Restore gezielt neu erzeugt werden.

## Backup und Restore

Beide Werkzeuge benoetigen Python 3.11+. `MEMORY_API_URL` muss explizit gesetzt sein. Fuer Backups ist `API_SECRET_BACKUP`, fuer Restore einschliesslich Dry-run `API_SECRET_RESTORE` erforderlich. Prozessvariablen haben Vorrang vor einer optionalen `backup/.env`; die Referenz liegt in [backup/.env.example](backup/.env.example). Der fruehere generische `API_SECRET`-Fallback und die automatische Suche nach Home-Secret-Dateien entfallen. Private Konfiguration und Backups nicht weitergeben.

```powershell
python -B backup/backup_memory.py
python -B backup/restore_memory.py --file backup/memory_backup_BEISPIEL.json --include-resolved
python -B backup/restore_memory.py --file backup/memory_backup_BEISPIEL.json --include-resolved --apply
```

Der Backup-Client validiert Schema, Vollstaendigkeit und Counts, ergaenzt die Herkunft `source_url` im lokalen Manifest und schreibt eine eindeutige Datei atomar. Erst nach einem gueltigen neuen Backup duerfen alte Sicherungen bereinigt werden. Ein vollstaendig leerer Bestand ist gueltig, eine leere oder unvollstaendige API-Antwort nicht. Private Backups enthalten die Originaltexte; die IT muss Dateirechte, Aufbewahrung und eine gegebenenfalls verschluesselte externe Sicherung festlegen. Es wird keine Cloud-Synchronisierung automatisch eingerichtet.

`memory_backup_BEISPIEL.json` durch die tatsaechliche Datei ersetzen. Restore ist standardmaessig ein Dry-run. Vor `--apply` Herkunft und Ziel pruefen; fuer eine andere Instanz ist zusaetzlich `--allow-different-target` erforderlich. `--include-resolved` schliesst erledigte Active-Eintraege ein und ist fuer ein vollstaendiges Restore notwendig; ohne diesen Schalter werden sie ausgelassen. `--tiers core,active,sessions,improvements` kann den Umfang ausdruecklich begrenzen. Ohne `--file` wird die neueste Datei gewaehlt; ist diese fehlerhaft, erfolgt kein stiller Rueckfall auf eine aeltere Datei.

Nicht verifizierbare alte Exportformate werden abgewiesen. Nach Server-Upgrade ein aktuelles Backup erneut exportieren oder ein altes Format separat kontrolliert migrieren. Vor dem Upgrade einer alten Instanz eine unabhaengige Datenbanksicherung erstellen. Wiederholtes Restore erhaelt UUIDs und Zeitstempel und ueberschreibt keine vorhandenen Datensaetze. Teilfehler fuehren zu einem Fehlerstatus; ein abgebrochener Lauf kann erneut ausgefuehrt werden.

## Pruefen und abnehmen

Die deterministischen Pruefungen brauchen keinen Modell-API-Key:

```powershell
python -B -m unittest discover -s backup
python -B -m unittest discover -s tests
deno test supabase/functions/memory-manager/handler_test.ts
deno check --lock=deno.lock --frozen supabase/functions/memory-manager/index.ts
python -B scripts/build_skill.py
```

SQL-Integrationstests pruefen eine frische Datenbank, RPC-Rechte, vier Suchschichten und Restore. Vor einer Firmenfreigabe muss die IT zusaetzlich im vorgesehenen isolierten Supabase-Testprojekt und mit echten Cowork-/Codex-Installationen abnehmen:

1. Alle Migrationen und die Edge Function installieren; falsche API-Schluessel und direkte RPC-Aufrufe als `anon`/`authenticated` muessen scheitern.
2. Cowork legt einen synthetischen Testeintrag an; Codex liest und aktualisiert ihn; Cowork findet den geaenderten Stand.
3. Export mit mehr als 100 Sessions und mehr als 1000 Eintraegen pruefen; Restore zweimal ausfuehren und IDs, Zeitstempel sowie Anzahl vergleichen.
4. ZIP-Inhalt sowie fehlende Konfiguration, nicht erlaubten Netzwerkzugriff und einen API-Fehler pruefen. Fehlgeschlagene Operationen duerfen keine Erfolgsmeldung erzeugen.

Automatisierte Tests ersetzen diesen Test der jeweiligen Client- und Organisationsumgebung nicht. Ein Draft-PR ist ein Pruefkandidat, keine bereits erteilte Firmenfreigabe.

## Entwicklung und Lizenz

Autoritative Quellen liegen unter `supabase/`; die Referenzkopien unter `edge-function/` und `supabase-migrations/` muessen synchron bleiben. [AGENTS.md](AGENTS.md) beschreibt die Entwicklungsregeln, [CHANGELOG.md](CHANGELOG.md) die Aenderungen. Lizenz: [MIT](LICENSE).

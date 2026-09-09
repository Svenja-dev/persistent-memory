"""
Memory Backup Script
Exportiert alle Memory-Daten aus Supabase und speichert sie als JSON-Datei.
Loescht Backups aelter als 30 Tage.

Verwendung:
    python backup_memory.py

Voraussetzungen (eine Quelle reicht, Reihenfolge = Prioritaet):
    - Environment Variable API_SECRET_BACKUP oder API_SECRET
    - .env Datei im selben Verzeichnis
    - Datei ~/.claude/memory-secret (Standard fuer den Taskplaner-Lauf)

Backup-Verzeichnis: Dasselbe Verzeichnis wie dieses Script.
Von dort wird es automatisch auf Google Drive synchronisiert.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Optional, Tuple

# Konfiguration
MEMORY_API_URL = "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager"
BACKUP_DIR = Path(__file__).parent
MAX_BACKUP_AGE_DAYS = 30


def load_env() -> dict:
    """Lese .env, ohne die hoeher priorisierte Prozessumgebung zu veraendern."""
    values = {}
    env_file = BACKUP_DIR / ".env"
    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values.setdefault(key.strip(), value.strip())
    return values


def load_secret_file() -> str:
    """Lese das Secret aus ~/.claude/memory-secret (leer, wenn nicht vorhanden)."""
    secret_file = Path.home() / ".claude" / "memory-secret"
    try:
        return secret_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _select_credentials(values: Mapping[str, str]) -> Optional[Tuple[str, Optional[str]]]:
    for key in ("API_SECRET_BACKUP", "API_SECRET"):
        secret = values.get(key, "").strip()
        if secret:
            return secret, "backup" if key == "API_SECRET_BACKUP" else None
    return None


def get_api_credentials() -> Tuple[str, Optional[str]]:
    """Hole Secret und Client-Zuordnung in der dokumentierten Quellenreihenfolge."""
    credentials = (
        _select_credentials(os.environ)
        or _select_credentials(load_env())
        or _select_credentials({"API_SECRET": load_secret_file()})
    )
    if not credentials:
        print("FEHLER: Kein API-Secret gefunden.")
        print("Quellen: API_SECRET_BACKUP / API_SECRET (Environment), "
              f"{BACKUP_DIR / '.env'} oder {Path.home() / '.claude' / 'memory-secret'}")
        sys.exit(1)
    return credentials


def get_api_secret() -> str:
    """Hole nur das Secret; Backup-Aufrufe nutzen zusaetzlich dessen Client-Zuordnung."""
    return get_api_credentials()[0]


def fetch_backup(api_secret: str, client: Optional[str] = None) -> dict:
    """Rufe den Backup-Endpoint auf und gib die Daten zurueck."""
    url = f"{MEMORY_API_URL}?action=backup"
    headers = {
        "Authorization": f"Bearer {api_secret}",
        "Content-Type": "application/json",
    }
    # Ein generischer/shared Key ist keinem bestimmten Client zugeordnet.
    if client:
        headers["X-Memory-Client"] = client
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not data.get("success"):
                print(f"FEHLER: API-Antwort: {data}")
                sys.exit(1)
            return data
    except urllib.error.HTTPError as e:
        print(f"FEHLER: HTTP {e.code} - {e.reason}")
        body = e.read().decode("utf-8", errors="replace")
        print(f"Details: {body[:500]}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"FEHLER: Verbindung fehlgeschlagen - {e.reason}")
        sys.exit(1)


def save_backup(data: dict) -> Path:
    """Speichere Backup als JSON-Datei mit Zeitstempel."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"memory_backup_{timestamp}.json"
    filepath = BACKUP_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    size_kb = filepath.stat().st_size / 1024
    return filepath, size_kb


def cleanup_old_backups():
    """Loesche Backups aelter als MAX_BACKUP_AGE_DAYS."""
    cutoff = datetime.now() - timedelta(days=MAX_BACKUP_AGE_DAYS)
    removed = 0

    for f in BACKUP_DIR.glob("memory_backup_*.json"):
        if f.stat().st_mtime < cutoff.timestamp():
            f.unlink()
            removed += 1

    return removed


def print_summary(data: dict, filepath: Path, size_kb: float, removed: int):
    """Gib eine Zusammenfassung aus."""
    core_count = data.get("core", {}).get("count", 0)
    active_count = data.get("active", {}).get("count", 0)
    sessions_count = data.get("sessions", {}).get("count", 0)
    improvements_count = data.get("improvements", {}).get("count", 0)

    print(f"Memory Backup erfolgreich")
    print(f"  Datei:     {filepath}")
    print(f"  Groesse:   {size_kb:.1f} KB")
    print(f"  Core:      {core_count} Eintraege")
    print(f"  Active:    {active_count} Eintraege")
    print(f"  Sessions:  {sessions_count} Eintraege")
    print(f"  Improvements: {improvements_count} Eintraege")
    if removed > 0:
        print(f"  Bereinigt:  {removed} alte Backups geloescht")


def main():
    api_secret, client = get_api_credentials()

    print(f"Lade Memory-Backup von Supabase...")
    data = fetch_backup(api_secret, client)

    filepath, size_kb = save_backup(data)
    removed = cleanup_old_backups()

    print_summary(data, filepath, size_kb, removed)


if __name__ == "__main__":
    main()

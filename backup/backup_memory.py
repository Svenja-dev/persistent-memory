"""
Memory Backup Script
Exportiert alle Memory-Daten aus Supabase und speichert sie als JSON-Datei.
Loescht Backups aelter als 30 Tage.

Verwendung:
    python backup_memory.py

Voraussetzungen:
    - Environment Variable API_SECRET_BACKUP oder API_SECRET muss gesetzt sein
    - Oder .env Datei im selben Verzeichnis

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

# Konfiguration
MEMORY_API_URL = "https://naatzputlsusiiczltzp.supabase.co/functions/v1/memory-manager"
BACKUP_DIR = Path(__file__).parent
MAX_BACKUP_AGE_DAYS = 30


def load_env():
    """Lade API_SECRET aus .env Datei falls vorhanden."""
    env_file = BACKUP_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def get_api_secret():
    """Hole API_SECRET aus Environment."""
    load_env()
    secret = os.environ.get("API_SECRET_BACKUP") or os.environ.get("API_SECRET")
    if not secret:
        print("FEHLER: API_SECRET_BACKUP oder API_SECRET nicht gesetzt.")
        print("Setze die Variable per Environment oder erstelle eine .env Datei:")
        print(f"  echo 'API_SECRET_BACKUP=dein-secret' > {BACKUP_DIR / '.env'}")
        sys.exit(1)
    return secret


def fetch_backup(api_secret: str) -> dict:
    """Rufe den Backup-Endpoint auf und gib die Daten zurueck."""
    url = f"{MEMORY_API_URL}?action=backup"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_secret}",
            "X-Memory-Client": "backup",
            "Content-Type": "application/json",
        },
    )

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

    print(f"Memory Backup erfolgreich")
    print(f"  Datei:     {filepath}")
    print(f"  Groesse:   {size_kb:.1f} KB")
    print(f"  Core:      {core_count} Eintraege")
    print(f"  Active:    {active_count} Eintraege")
    print(f"  Sessions:  {sessions_count} Eintraege")
    if removed > 0:
        print(f"  Bereinigt:  {removed} alte Backups geloescht")


def main():
    api_secret = get_api_secret()

    print(f"Lade Memory-Backup von Supabase...")
    data = fetch_backup(api_secret)

    filepath, size_kb = save_backup(data)
    removed = cleanup_old_backups()

    print_summary(data, filepath, size_kb, removed)


if __name__ == "__main__":
    main()

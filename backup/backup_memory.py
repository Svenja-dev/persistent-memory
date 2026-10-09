"""Validated, atomic Memory backups. Requires Python 3.11+ and explicit configuration.

Set MEMORY_API_URL and API_SECRET_BACKUP in the environment
or backup/.env. No implicit personal endpoint or credential file is used.
"""

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

from backup_schema import ALL_TIERS, validate_backup, validate_endpoint

BACKUP_DIR = Path(__file__).resolve().parent
MAX_BACKUP_AGE_DAYS = 30


def load_env() -> dict:
    """Read literal dotenv values without modifying the process environment."""
    values = {}
    env_file = BACKUP_DIR / ".env"
    if env_file.exists():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values.setdefault(key.strip(), value)
    return values


def get_api_url() -> str:
    value = os.environ.get("MEMORY_API_URL", "").strip()
    if not value:
        value = load_env().get("MEMORY_API_URL", "").strip()
    return validate_endpoint(value)


def get_api_credentials() -> Tuple[str, str]:
    secret = os.environ.get("API_SECRET_BACKUP", "").strip()
    if not secret:
        secret = load_env().get("API_SECRET_BACKUP", "").strip()
    if not secret or "\r" in secret or "\n" in secret:
        raise ValueError("API_SECRET_BACKUP muss separat konfiguriert werden (kein Legacy-Fallback)")
    return secret, "backup"


def get_api_secret() -> str:
    return get_api_credentials()[0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer token to a redirected target.
        return None


def open_request(request: urllib.request.Request):
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=30)


def fetch_backup(api_secret: str, client: str = "backup", api_url: Optional[str] = None) -> dict:
    endpoint = validate_endpoint(api_url) if api_url is not None else get_api_url()
    if client not in {"backup", "restore"}:
        raise ValueError("Backup-Zugriff benoetigt den Client backup oder restore")
    headers = {"Authorization": f"Bearer {api_secret}", "Accept": "application/json", "X-Memory-Client": client}
    request = urllib.request.Request(f"{endpoint}?action=backup", headers=headers)
    with open_request(request) as response:
        data = json.loads(response.read().decode("utf-8"))
    validate_backup(data)
    return data


def save_backup(data: dict, source_url: Optional[str] = None) -> Tuple[Path, float]:
    """Validate before creating any file; publish only a complete, flushed JSON file."""
    validate_backup(data)
    endpoint = validate_endpoint(source_url) if source_url is not None else get_api_url()
    manifest = {**data, "source_url": endpoint}
    validate_backup(manifest, require_source=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filepath = BACKUP_DIR / f"memory_backup_{timestamp}_{uuid4().hex}.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=BACKUP_DIR,
            prefix=".memory_backup_", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, filepath)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return filepath, filepath.stat().st_size / 1024


def cleanup_old_backups(completed_backup: Path) -> int:
    """Prune only verified older backups of this source after a verified new backup."""
    if completed_backup.resolve().parent != BACKUP_DIR.resolve():
        raise ValueError("Neues Backup liegt ausserhalb des Backup-Verzeichnisses")
    manifest = json.loads(completed_backup.read_text(encoding="utf-8"))
    validate_backup(manifest, require_source=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_BACKUP_AGE_DAYS)).timestamp()
    removed = 0
    for candidate in BACKUP_DIR.glob("memory_backup_*.json"):
        if candidate == completed_backup or candidate.is_symlink() or candidate.stat().st_mtime >= cutoff:
            continue
        try:
            older = json.loads(candidate.read_text(encoding="utf-8"))
            validate_backup(older, require_source=True)
        except (OSError, ValueError):
            continue  # Preserve unverified/legacy files for manual inspection.
        if validate_endpoint(older["source_url"]) == validate_endpoint(manifest["source_url"]):
            candidate.unlink()
            removed += 1
    return removed


def print_summary(data: dict, filepath: Path, size_kb: float, removed: int):
    print("Memory Backup erfolgreich")
    print(f"  Datei:     {filepath}")
    print(f"  Groesse:   {size_kb:.1f} KB")
    for tier in ALL_TIERS:
        print(f"  {tier.capitalize()}: {data[tier]['count']} Eintraege")
    if removed:
        print(f"  Bereinigt: {removed} alte Backups geloescht")


def main() -> int:
    try:
        endpoint = get_api_url()  # Validate target before resolving or using credentials.
        api_secret, client = get_api_credentials()
        print(f"Backup-Quelle: {endpoint}")
        data = fetch_backup(api_secret, client, endpoint)
        filepath, size_kb = save_backup(data, endpoint)
        removed = cleanup_old_backups(filepath)
        print_summary(data, filepath, size_kb, removed)
        return 0
    except urllib.error.HTTPError as error:
        print(f"FEHLER: Backup HTTP {error.code}; keine neue Sicherung bestaetigt")
    except (OSError, ValueError) as error:
        print(f"FEHLER: {error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

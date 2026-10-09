"""Restore a verified backup without replacing existing IDs. Dry-run is the default.

Requires MEMORY_API_URL and the separate API_SECRET_RESTORE credential. Every
record retains its UUID and timestamps. Interrupted runs can safely be repeated.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import backup_memory
from backup_schema import ALL_TIERS, validate_backup, validate_endpoint, validate_record

BACKUP_DIR = Path(__file__).resolve().parent


def load_backup(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_backup(data, require_source=True)
    return data


def newest_backup_file() -> Optional[Path]:
    # Do not silently restore an older snapshot when the newest named file is bad.
    files = [path for path in BACKUP_DIR.glob("memory_backup_*.json") if path.is_file()]
    return max(files, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)


def entries_of(data: dict, tier: str) -> List[dict]:
    return data[tier]["data"]


def get_restore_secret() -> str:
    secret = os.environ.get("API_SECRET_RESTORE", "").strip()
    if not secret:
        secret = backup_memory.load_env().get("API_SECRET_RESTORE", "").strip()
    if not secret or "\r" in secret or "\n" in secret:
        raise ValueError("API_SECRET_RESTORE muss separat konfiguriert werden (kein Backup-/Legacy-Fallback)")
    return secret


def build_headers(api_secret: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_secret}", "Content-Type": "application/json",
        "X-Memory-Client": "restore",
    }


def fetch_current_ids(api_secret: str, api_url: str) -> Dict[str, set]:
    current = backup_memory.fetch_backup(api_secret, "restore", api_url)
    return {tier: {entry["id"].lower() for entry in entries_of(current, tier)} for tier in ALL_TIERS}


def restore_payload(tier: str, entry: dict) -> dict:
    validate_record(tier, entry)
    return {"action": "restore", "tier": tier, "record": dict(entry)}


def plan_restore(
    backup: dict, current_ids: Dict[str, set], tiers: Iterable[str], include_resolved: bool,
) -> Dict[str, Tuple[List[dict], int]]:
    plan = {}
    for tier in tiers:
        missing, existing = [], 0
        for entry in entries_of(backup, tier):
            if entry["id"].lower() in current_ids.get(tier, set()):
                existing += 1
            elif tier != "active" or not entry["resolved"] or include_resolved:
                missing.append(entry)
        plan[tier] = (missing, existing)
    return plan


def post_entry(payload: dict, headers: Dict[str, str], api_url: str) -> Tuple[bool, str]:
    request = urllib.request.Request(
        validate_endpoint(api_url), data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with backup_memory.open_request(request) as response:
            body = json.loads(response.read().decode("utf-8"))
        if (not isinstance(body, dict) or body.get("success") is not True or body.get("action") != "restore"
                or body.get("tier") != payload["tier"] or body.get("id") != payload["record"]["id"]
                or type(body.get("inserted")) is not bool):
            return False, "Ungueltige Restore-Bestaetigung; erneuter Lauf ist idempotent"
        return True, "inserted" if body["inserted"] else "existing"
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}"
    except (OSError, ValueError) as error:
        return False, str(error)


def label(tier: str, entry: dict) -> str:
    text = entry.get("title") or entry.get("session_id") or entry.get("summary") or "?"
    return f"[{entry.get('project') or '-'}] {str(text)[:70]}"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verifiziertes Memory-Backup nach Supabase zurueckspielen")
    parser.add_argument("--file", type=Path, help="Backup-Datei (Standard: neueste memory_backup_*.json)")
    parser.add_argument("--apply", action="store_true", help="Wirklich schreiben (Standard: Dry-Run)")
    parser.add_argument("--tiers", default=",".join(ALL_TIERS), help="Kommagetrennt, Standard: alle")
    parser.add_argument("--include-resolved", action="store_true", help="Auch aufgeloeste Active-Eintraege")
    parser.add_argument("--allow-different-target", action="store_true", help="Restore in einen anderen Endpunkt erlauben")
    args = parser.parse_args(argv)
    tiers = [tier.strip() for tier in args.tiers.split(",") if tier.strip()]
    if not tiers or any(tier not in ALL_TIERS for tier in tiers) or len(set(tiers)) != len(tiers):
        parser.error(f"Tiers muessen eindeutig und aus {', '.join(ALL_TIERS)} sein")
    args.tier_list = tiers
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        path = args.file or newest_backup_file()
        if not path:
            raise ValueError("Keine Backup-Datei gefunden")
        backup = load_backup(path)  # Validate every row before credentials or network.
        endpoint = backup_memory.get_api_url()
        source = validate_endpoint(backup["source_url"])
        print(f"Backup:   {path.name} (exportiert {backup['exported_at']})")
        print(f"Quelle:   {source}")
        print(f"Ziel:     {endpoint}")
        print(f"Modus:    {'APPLY' if args.apply else 'DRY-RUN (nichts wird geschrieben)'}")
        if source != endpoint and not args.allow_different_target:
            raise ValueError("Quelle und Ziel unterscheiden sich; nur mit --allow-different-target fortsetzen")
        api_secret = get_restore_secret()
        current_ids = fetch_current_ids(api_secret, endpoint)
        plan = plan_restore(backup, current_ids, args.tier_list, args.include_resolved)
        total_missing = sum(len(missing) for missing, _existing in plan.values())
        for tier, (missing, existing) in plan.items():
            print(f"\n{tier}: {existing} vorhanden, {len(missing)} fehlen")
            for entry in missing:
                print(f"  + {label(tier, entry)}")
        if not args.apply:
            print(f"\nDry-Run beendet. {total_missing} Eintraege wuerden angelegt. Mit --apply ausfuehren.")
            return 0
        inserted = existing = failed = 0
        headers = build_headers(api_secret)
        for tier, (missing, _existing) in plan.items():
            for entry in missing:
                ok, info = post_entry(restore_payload(tier, entry), headers, endpoint)
                if ok and info == "inserted":
                    inserted += 1
                elif ok:
                    existing += 1
                else:
                    failed += 1
                    print(f"  FEHLER {tier} {label(tier, entry)}: {info}")
        print(f"\nRestore fertig: {inserted} angelegt, {existing} inzwischen vorhanden, {failed} fehlgeschlagen.")
        return 0 if failed == 0 else 2
    except urllib.error.HTTPError as error:
        print(f"FEHLER: HTTP {error.code}")
    except (OSError, ValueError) as error:
        print(f"FEHLER: {error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

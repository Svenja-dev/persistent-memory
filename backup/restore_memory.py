"""
Memory Restore Script
Spielt Eintraege aus einer memory_backup_*.json zurueck in Supabase, ueber die
memory-manager API. Standard ist ein Dry-Run, der nur zeigt, was passieren wuerde.

Verwendung:
    python restore_memory.py                      # Dry-Run mit neuestem Backup
    python restore_memory.py --apply              # wirklich zurueckspielen
    python restore_memory.py --file memory_backup_20260909_190904.json --tiers core,active
    python restore_memory.py --apply --include-resolved

Verhalten:
    - Eintraege, deren id in Supabase noch existiert, werden uebersprungen (kein Ueberschreiben).
    - Fehlende Eintraege werden per POST neu angelegt. Die API vergibt dabei eine NEUE id
      und setzt created_at auf jetzt; Embeddings werden automatisch neu erzeugt.
    - Sessions mit bereits vorhandener session_id lehnt die API mit 409 ab (wird gemeldet).
    - Aufgeloeste Active-Eintraege werden nur mit --include-resolved zurueckgespielt.

Credentials: dieselben Quellen wie backup_memory.py (Env, .env, ~/.claude/memory-secret).
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import backup_memory

BACKUP_DIR = Path(__file__).parent
ALL_TIERS = ("core", "active", "sessions", "improvements")

# Felder, die die API beim Anlegen akzeptiert (Allowlist der Edge Function, ohne id).
RESTORE_FIELDS = {
    "core": ("project", "category", "title", "content", "tags", "importance"),
    "active": ("project", "category", "title", "content", "tags", "priority", "resolved", "resolved_at"),
    "sessions": (
        "project", "session_id", "tool", "summary", "tags",
        "decisions_made", "issues_encountered", "files_changed",
    ),
    "improvements": (
        "project", "category", "title", "tags", "status", "introduced_at", "evidence",
        "next_step", "related_files", "model_version_notes", "last_used_at", "use_count",
    ),
}


def newest_backup_file() -> Optional[Path]:
    files = sorted(BACKUP_DIR.glob("memory_backup_*.json"))
    return files[-1] if files else None


def load_backup(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data.get("success", True):
        raise ValueError(f"{path} ist kein gueltiges Memory-Backup")
    return data


def entries_of(data: dict, tier: str) -> List[dict]:
    block = data.get(tier) or {}
    return list(block.get("data") or [])


def build_headers(api_secret: str, client: Optional[str]) -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_secret}",
        "Content-Type": "application/json",
    }
    if client:
        headers["X-Memory-Client"] = client
    return headers


def fetch_current_ids(api_secret: str, client: Optional[str]) -> Dict[str, set]:
    """Aktuelle ids je Tier aus dem Backup-Endpoint (liefert alle Zeilen, auch resolved)."""
    current = backup_memory.fetch_backup(api_secret, client)
    return {tier: {e["id"] for e in entries_of(current, tier)} for tier in ALL_TIERS}


def restore_payload(tier: str, entry: dict) -> dict:
    payload = {"tier": tier}
    for field in RESTORE_FIELDS[tier]:
        if field in entry and entry[field] is not None:
            payload[field] = entry[field]
    return payload


def plan_restore(
    backup: dict, current_ids: Dict[str, set], tiers: Iterable[str], include_resolved: bool
) -> Dict[str, Tuple[List[dict], int]]:
    """Je Tier: (fehlende Eintraege, Anzahl bereits vorhandener)."""
    plan: Dict[str, Tuple[List[dict], int]] = {}
    for tier in tiers:
        missing: List[dict] = []
        existing = 0
        for entry in entries_of(backup, tier):
            if entry.get("id") in current_ids.get(tier, set()):
                existing += 1
                continue
            if tier == "active" and entry.get("resolved") and not include_resolved:
                continue
            missing.append(entry)
        plan[tier] = (missing, existing)
    return plan


def post_entry(payload: dict, headers: Dict[str, str]) -> Tuple[bool, str]:
    req = urllib.request.Request(
        backup_memory.MEMORY_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
            if body.get("success"):
                return True, body.get("action", "created")
            return False, str(body.get("error", body))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200]
        return False, f"HTTP {e.code}: {detail}"
    except urllib.error.URLError as e:
        return False, f"Verbindung fehlgeschlagen: {e.reason}"


def label(tier: str, entry: dict) -> str:
    text = entry.get("title") or entry.get("session_id") or entry.get("summary") or "?"
    return f"[{entry.get('project') or '-'}] {str(text)[:70]}"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Memory-Backup nach Supabase zurueckspielen")
    parser.add_argument("--file", type=Path, help="Backup-Datei (Standard: neueste memory_backup_*.json)")
    parser.add_argument("--apply", action="store_true", help="Wirklich schreiben (Standard: Dry-Run)")
    parser.add_argument("--tiers", default=",".join(ALL_TIERS), help="Kommagetrennt, Standard: alle")
    parser.add_argument("--include-resolved", action="store_true", help="Auch aufgeloeste Active-Eintraege")
    args = parser.parse_args(argv)
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    unknown = [t for t in tiers if t not in ALL_TIERS]
    if unknown:
        parser.error(f"Unbekannte Tiers: {', '.join(unknown)} (erlaubt: {', '.join(ALL_TIERS)})")
    args.tier_list = tiers
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    path = args.file or newest_backup_file()
    if not path or not path.exists():
        print("FEHLER: Keine Backup-Datei gefunden.")
        return 1

    backup = load_backup(path)
    api_secret, client = backup_memory.get_api_credentials()
    headers = build_headers(api_secret, client)

    print(f"Backup:   {path.name} (exportiert {backup.get('exported_at', '?')})")
    print(f"Modus:    {'APPLY' if args.apply else 'DRY-RUN (nichts wird geschrieben)'}")
    current_ids = fetch_current_ids(api_secret, client)
    plan = plan_restore(backup, current_ids, args.tier_list, args.include_resolved)

    total_missing = 0
    for tier, (missing, existing) in plan.items():
        total_missing += len(missing)
        print(f"\n{tier}: {existing} vorhanden, {len(missing)} fehlen")
        for entry in missing:
            print(f"  + {label(tier, entry)}")

    if total_missing == 0:
        print("\nNichts zu tun: alle Eintraege sind vorhanden.")
        return 0
    if not args.apply:
        print(f"\nDry-Run beendet. {total_missing} Eintraege wuerden angelegt. Mit --apply ausfuehren.")
        return 0

    restored = failed = 0
    for tier, (missing, _existing) in plan.items():
        for entry in missing:
            ok, info = post_entry(restore_payload(tier, entry), headers)
            if ok:
                restored += 1
            else:
                failed += 1
                print(f"  FEHLER {tier} {label(tier, entry)}: {info}")

    print(f"\nRestore fertig: {restored} angelegt, {failed} fehlgeschlagen.")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

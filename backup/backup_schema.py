"""Version 1 export validation shared by backup and restore (no dependencies)."""

import re
from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

ALL_TIERS = ("core", "active", "sessions", "improvements")
COMMON_FIELDS = {"id", "project", "tags", "created_at"}
TIER_FIELDS = {
    "core": COMMON_FIELDS | {"category", "title", "content", "importance", "updated_at"},
    "active": COMMON_FIELDS | {
        "category", "title", "content", "priority", "resolved", "resolved_at", "updated_at",
    },
    "sessions": COMMON_FIELDS | {
        "session_id", "tool", "summary", "decisions_made", "issues_encountered", "files_changed",
    },
    "improvements": COMMON_FIELDS | {
        "category", "title", "status", "introduced_at", "evidence", "next_step", "related_files",
        "model_version_notes", "last_used_at", "use_count", "updated_at",
    },
}
ENUMS = {
    ("core", "category"): {
        "preference", "architecture", "pattern", "context", "tool_config", "decision", "user_profile",
        "user_values", "work_style", "communication", "pain_points", "workflow_preference",
    },
    ("active", "category"): {"work_state", "open_question", "next_step", "blocker", "decision_pending", "learning"},
    ("improvements", "category"): {"skill", "hook", "workflow", "process", "command", "agent"},
    ("core", "importance"): {"low", "normal", "high", "critical"},
    ("active", "priority"): {"low", "normal", "high", "urgent"},
    ("sessions", "tool"): {"cowork", "claude_code", "openclaw", "api", "other"},
    ("improvements", "status"): {"experimenting", "proven", "retired"},
}
ARRAY_FIELDS = {"tags", "decisions_made", "issues_encountered", "files_changed", "related_files"}
TIMESTAMP_FIELDS = {"created_at", "updated_at", "resolved_at", "last_used_at"}
REQUIRED_VALUES = {
    "core": {"id", "category", "title", "content"},
    "active": {"id", "category", "title", "content"},
    "sessions": {"id", "session_id", "summary"},
    "improvements": {"id", "category", "title", "status", "use_count"},
}


def validate_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("MEMORY_API_URL muss explizit konfiguriert werden")
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise ValueError("MEMORY_API_URL enthaelt ungueltige Zeichen")
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError as error:
        raise ValueError("MEMORY_API_URL ist ungueltig") from error
    if not host or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("MEMORY_API_URL muss ein Endpunkt ohne Zugangsdaten, Query oder Fragment sein")
    if not re.fullmatch(r"[a-zA-Z0-9.:-]+", host):
        raise ValueError("MEMORY_API_URL hat einen ungueltigen Hostnamen")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("MEMORY_API_URL muss HTTPS verwenden (HTTP nur fuer localhost/Loopback)")
    if parsed.path.rstrip("/") != "/functions/v1/memory-manager":
        raise ValueError("MEMORY_API_URL muss auf /functions/v1/memory-manager zeigen")
    hostname = f"[{host.lower()}]" if ":" in host else host.lower()
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        hostname += f":{port}"
    return urlunsplit((parsed.scheme, hostname, "/functions/v1/memory-manager", "", ""))


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def validate_record(tier: str, record: object) -> None:
    if not isinstance(record, dict) or set(record) != TIER_FIELDS[tier]:
        raise ValueError(f"Backup {tier}: unvollstaendige oder unbekannte Datensatzfelder")
    for field, value in record.items():
        if value is None and field not in REQUIRED_VALUES[tier]:
            continue
        valid = isinstance(value, str)
        if field == "id":
            try:
                valid = isinstance(value, str) and str(UUID(value)) == value.lower()
            except (ValueError, AttributeError):
                valid = False
        elif field in ARRAY_FIELDS:
            valid = isinstance(value, list) and all(item is None or isinstance(item, str) for item in value)
        elif field in TIMESTAMP_FIELDS:
            valid = _timestamp(value)
        elif field == "introduced_at":
            try:
                valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
            except ValueError:
                valid = False
        elif field == "resolved":
            valid = type(value) is bool
        elif field == "use_count":
            valid = type(value) is int and value >= 0
        elif (tier, field) in ENUMS:
            valid = isinstance(value, str) and value in ENUMS[(tier, field)]
        if not valid:
            raise ValueError(f"Backup {tier}: ungueltiges Feld {field}")


def validate_backup(data: object, *, require_source: bool = False) -> None:
    """Reject partial, legacy, malformed, or unverified exports before any mutation."""
    if not isinstance(data, dict):
        raise ValueError("Backup muss ein JSON-Objekt sein")
    if (data.get("success") is not True or data.get("action") != "backup"
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or data.get("complete") is not True or not _timestamp(data.get("exported_at"))):
        raise ValueError("Kein vollstaendiges Backup im Schema 1; alte Exporte muessen neu erstellt werden")
    if require_source or "source_url" in data:
        validate_endpoint(data.get("source_url"))
    for tier in ALL_TIERS:
        block = data.get(tier)
        if (not isinstance(block, dict) or type(block.get("count")) is not int
                or not isinstance(block.get("data"), list) or block["count"] != len(block["data"])):
            raise ValueError(f"Backup {tier}: fehlender Datenblock oder falsche Anzahl")
        seen = set()
        for record in block["data"]:
            validate_record(tier, record)
            identifier = record["id"].lower()
            if identifier in seen:
                raise ValueError(f"Backup {tier}: doppelte Datensatz-ID")
            seen.add(identifier)

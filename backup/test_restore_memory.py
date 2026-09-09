"""Offline-Tests fuer restore_memory: Planung, Payload-Filter, Dry-Run ohne Schreibzugriff."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import restore_memory


def make_backup(core=(), active=(), sessions=(), improvements=()):
    def block(rows):
        return {"count": len(rows), "data": list(rows)}

    return {
        "success": True,
        "exported_at": "2026-09-09T00:00:00Z",
        "core": block(core),
        "active": block(active),
        "sessions": block(sessions),
        "improvements": block(improvements),
    }


CORE_A = {"id": "a", "project": "global", "category": "pattern", "title": "A", "content": "x",
          "tags": ["t"], "importance": "high", "embedding": [0.1], "created_at": "2026-01-01"}
CORE_B = {"id": "b", "project": None, "category": "decision", "title": "B", "content": "y",
          "tags": [], "importance": "normal", "embedding": None, "created_at": "2026-01-02"}
ACTIVE_OPEN = {"id": "c", "project": "rosetta", "category": "work_state", "title": "C", "content": "z",
               "tags": [], "priority": "high", "resolved": False, "resolved_at": None}
ACTIVE_DONE = {"id": "d", "project": "rosetta", "category": "blocker", "title": "D", "content": "w",
               "tags": [], "priority": "normal", "resolved": True, "resolved_at": "2026-05-01"}


class PlanTests(unittest.TestCase):
    def test_existing_ids_are_skipped_and_resolved_needs_flag(self):
        backup = make_backup(core=[CORE_A, CORE_B], active=[ACTIVE_OPEN, ACTIVE_DONE])
        current = {"core": {"a"}, "active": set(), "sessions": set(), "improvements": set()}

        plan = restore_memory.plan_restore(backup, current, ["core", "active"], include_resolved=False)
        self.assertEqual([e["id"] for e in plan["core"][0]], ["b"])
        self.assertEqual(plan["core"][1], 1)
        self.assertEqual([e["id"] for e in plan["active"][0]], ["c"])

        plan = restore_memory.plan_restore(backup, current, ["active"], include_resolved=True)
        self.assertEqual([e["id"] for e in plan["active"][0]], ["c", "d"])

    def test_payload_contains_only_api_fields(self):
        payload = restore_memory.restore_payload("core", CORE_A)
        self.assertEqual(payload["tier"], "core")
        self.assertNotIn("id", payload)
        self.assertNotIn("embedding", payload)
        self.assertNotIn("created_at", payload)
        self.assertEqual(payload["title"], "A")
        self.assertEqual(payload["importance"], "high")

        payload = restore_memory.restore_payload("core", CORE_B)
        self.assertNotIn("project", payload, "None-Werte werden nicht gesendet")


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.enterContext(patch.object(restore_memory, "BACKUP_DIR", self.directory))
        self.enterContext(patch.object(restore_memory.backup_memory, "get_api_credentials",
                                       return_value=("secret", None)))
        self.backup_file = self.directory / "memory_backup_20260909_000000.json"
        self.backup_file.write_text(json.dumps(make_backup(core=[CORE_A, CORE_B])), encoding="utf-8")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = restore_memory.main(list(argv))
        return code, out.getvalue()

    def test_dry_run_never_posts(self):
        with patch.object(restore_memory, "fetch_current_ids",
                          return_value={"core": {"a"}, "active": set(), "sessions": set(), "improvements": set()}), \
             patch.object(restore_memory, "post_entry") as post:
            code, out = self.run_cli()
        self.assertEqual(code, 0)
        post.assert_not_called()
        self.assertIn("DRY-RUN", out)
        self.assertIn("1 fehlen", out)
        self.assertIn("[-] B", out)

    def test_apply_posts_missing_entries_and_reports_failures(self):
        with patch.object(restore_memory, "fetch_current_ids",
                          return_value={"core": set(), "active": set(), "sessions": set(), "improvements": set()}), \
             patch.object(restore_memory, "post_entry", side_effect=[(True, "created"), (False, "HTTP 409")]) as post:
            code, out = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertEqual(post.call_count, 2)
        self.assertIn("1 angelegt, 1 fehlgeschlagen", out)

    def test_unknown_tier_is_rejected(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                restore_memory.parse_args(["--tiers", "core,unknown"])


if __name__ == "__main__":
    unittest.main()

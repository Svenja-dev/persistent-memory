"""Offline restore regressions: complete validation, identity, resume and timestamps."""

import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import backup_memory
import restore_memory
from test_backup_memory import ACTIVE_DONE, ACTIVE_OPEN, CORE_A, CORE_B, ENDPOINT, OTHER_ENDPOINT, SESSION, make_backup


class PlanTests(unittest.TestCase):
    def test_existing_ids_are_skipped_and_resolved_needs_flag(self):
        backup = make_backup(core=[CORE_A, CORE_B], active=[ACTIVE_OPEN, ACTIVE_DONE])
        current = {"core": {CORE_A["id"]}, "active": set(), "sessions": set(), "improvements": set()}
        plan = restore_memory.plan_restore(backup, current, ["core", "active"], include_resolved=False)
        self.assertEqual(plan["core"], ([CORE_B], 1))
        self.assertEqual(plan["active"], ([ACTIVE_OPEN], 0))
        plan = restore_memory.plan_restore(backup, current, ["active"], include_resolved=True)
        self.assertEqual(plan["active"], ([ACTIVE_OPEN, ACTIVE_DONE], 0))

    def test_restore_payload_keeps_original_identity_timestamps_and_nulls(self):
        for tier, record in (("core", CORE_B), ("active", ACTIVE_DONE), ("sessions", SESSION)):
            with self.subTest(tier=tier):
                payload = restore_memory.restore_payload(tier, record)
                self.assertEqual(payload, {"action": "restore", "tier": tier, "record": record})
                self.assertIsNot(payload["record"], record)


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.enterContext(patch.object(restore_memory, "BACKUP_DIR", self.directory))
        self.enterContext(patch.object(backup_memory, "BACKUP_DIR", self.directory))
        self.enterContext(patch.dict(os.environ, {
            "MEMORY_API_URL": ENDPOINT, "API_SECRET_RESTORE": "restore-dummy",
        }, clear=True))
        self.backup_file = self.directory / "memory_backup_example.json"
        self.backup_file.write_text(json.dumps(make_backup(core=[CORE_A, CORE_B])), encoding="utf-8")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = restore_memory.main(list(argv))
        return code, out.getvalue()

    def test_dry_run_never_posts(self):
        with patch.object(restore_memory, "fetch_current_ids", return_value={"core": {CORE_A["id"]}}), \
                patch.object(restore_memory, "post_entry") as post:
            code, out = self.run_cli()
        self.assertEqual(code, 0)
        post.assert_not_called()
        self.assertIn("DRY-RUN", out)
        self.assertIn("1 fehlen", out)
        self.assertIn("[-] B", out)

    def test_malformed_backup_rejected_before_credentials_or_network(self):
        for raw in ("{}", "[]", "not json", json.dumps(make_backup(source=False))):
            with self.subTest(raw=raw):
                self.backup_file.write_text(raw, encoding="utf-8")
                with patch.object(restore_memory, "get_restore_secret") as credentials, \
                        patch.object(restore_memory, "fetch_current_ids") as fetch, \
                        patch.object(restore_memory, "post_entry") as post:
                    code, _ = self.run_cli("--apply")
                self.assertEqual(code, 1)
                credentials.assert_not_called()
                fetch.assert_not_called()
                post.assert_not_called()

    def test_backup_and_legacy_credentials_cannot_restore(self):
        os.environ.pop("API_SECRET_RESTORE")
        os.environ.update(API_SECRET_BACKUP="backup-dummy", API_SECRET="legacy-dummy")
        with patch.object(restore_memory, "fetch_current_ids") as fetch:
            code, out = self.run_cli("--apply")
        self.assertEqual(code, 1)
        self.assertIn("API_SECRET_RESTORE", out)
        fetch.assert_not_called()

    def test_cross_target_needs_explicit_flag_before_credentials(self):
        os.environ["MEMORY_API_URL"] = OTHER_ENDPOINT
        with patch.object(restore_memory, "get_restore_secret") as credentials:
            code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("--allow-different-target", out)
        self.assertIn(ENDPOINT, out)
        self.assertIn(OTHER_ENDPOINT, out)
        credentials.assert_not_called()
        with patch.object(restore_memory, "fetch_current_ids", return_value={}) as fetch, \
                patch.object(restore_memory, "post_entry") as post:
            code, _ = self.run_cli("--allow-different-target")
        self.assertEqual(code, 0)
        fetch.assert_called_once_with("restore-dummy", OTHER_ENDPOINT)
        post.assert_not_called()

    def test_interrupted_restore_repeats_without_duplicates_or_timestamp_changes(self):
        stored = {}
        interrupted = [False]

        def respond(request):
            self.assertEqual(request.get_header("Authorization"), "Bearer restore-dummy")
            self.assertEqual(request.get_header("X-memory-client"), "restore")
            if request.get_method() == "GET":
                body = make_backup(core=list(stored.values()), source=False)
            else:
                payload = json.loads(request.data)
                self.assertEqual(payload["action"], "restore")
                record = payload["record"]
                if record["id"] == CORE_B["id"] and not interrupted[0]:
                    interrupted[0] = True
                    # Commit reached the server, but its response was lost.
                    stored[record["id"]] = record
                    raise urllib.error.URLError("simulated dropped response")
                inserted = record["id"] not in stored
                stored.setdefault(record["id"], record)
                body = {"success": True, "action": "restore", "tier": "core", "id": record["id"], "inserted": inserted}
            return contextlib.closing(io.BytesIO(json.dumps(body).encode()))

        with patch.object(backup_memory, "open_request", side_effect=respond):
            first_code, first_output = self.run_cli("--apply")
            second_code, second_output = self.run_cli("--apply")
        self.assertEqual(first_code, 2)
        self.assertIn("1 fehlgeschlagen", first_output)
        self.assertEqual(second_code, 0)
        self.assertIn("2 vorhanden, 0 fehlen", second_output)
        self.assertEqual(stored, {CORE_A["id"]: CORE_A, CORE_B["id"]: CORE_B})

    def test_unverified_restore_success_is_failure(self):
        payload = restore_memory.restore_payload("core", CORE_A)
        for body in ({"success": True}, {"success": True, "action": "created"}, []):
            with self.subTest(body=body), patch.object(backup_memory, "open_request", return_value=
                    contextlib.closing(io.BytesIO(json.dumps(body).encode()))):
                ok, info = restore_memory.post_entry(payload, restore_memory.build_headers("dummy"), ENDPOINT)
            self.assertFalse(ok)
            self.assertIn("Restore-Bestaetigung", info)

    def test_concurrent_existing_row_is_reported_without_overwrite(self):
        payload = restore_memory.restore_payload("core", CORE_A)
        body = {"success": True, "action": "restore", "tier": "core", "id": CORE_A["id"], "inserted": False}
        with patch.object(backup_memory, "open_request", return_value=contextlib.closing(io.BytesIO(json.dumps(body).encode()))):
            self.assertEqual(restore_memory.post_entry(payload, restore_memory.build_headers("dummy"), ENDPOINT), (True, "existing"))

    def test_incomplete_temporary_file_is_never_selected(self):
        (self.directory / ".memory_backup_latest.tmp").write_text("{", encoding="utf-8")
        self.assertEqual(restore_memory.newest_backup_file(), self.backup_file)

    def test_unknown_empty_or_duplicate_tiers_are_rejected(self):
        for tiers in ("core,unknown", "", "core,core"):
            with self.subTest(tiers=tiers), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                restore_memory.parse_args(["--tiers", tiers])


if __name__ == "__main__":
    unittest.main()

"""Offline regressions for target isolation, complete exports and atomic retention."""

import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.response
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import backup_memory
from backup_schema import validate_backup, validate_endpoint


# Synthetic export fixtures shared with the restore regression tests.
ENDPOINT = "https://memory.example.test/functions/v1/memory-manager"
OTHER_ENDPOINT = "https://other.example.test/functions/v1/memory-manager"
STAMP = "2026-01-02T03:04:05.123456+00:00"
CORE_A = {
    "id": "00000000-0000-4000-8000-000000000001", "project": "global", "category": "pattern",
    "title": "A", "content": "Example A", "tags": ["test"], "importance": "high",
    "created_at": STAMP, "updated_at": "2026-03-02T03:04:05.123456+00:00",
}
CORE_B = {**CORE_A, "id": "00000000-0000-4000-8000-000000000002", "title": "B", "project": None}
ACTIVE_OPEN = {
    "id": "00000000-0000-4000-8000-000000000003", "project": "example", "category": "work_state",
    "title": "Open", "content": "Example active", "tags": [], "priority": "normal", "resolved": False,
    "resolved_at": None, "created_at": STAMP, "updated_at": STAMP,
}
ACTIVE_DONE = {**ACTIVE_OPEN, "id": "00000000-0000-4000-8000-000000000004", "resolved": True, "resolved_at": STAMP}
SESSION = {
    "id": "00000000-0000-4000-8000-000000000005", "project": "example", "session_id": "example-1",
    "tool": "cowork", "summary": "Synthetic session", "decisions_made": ["example"],
    "issues_encountered": None, "files_changed": [], "tags": [], "created_at": STAMP,
}
IMPROVEMENT = {
    "id": "00000000-0000-4000-8000-000000000006", "project": None, "title": "Example improvement",
    "category": "workflow", "status": "experimenting", "introduced_at": "2026-01-02",
    "evidence": None, "next_step": "Check", "related_files": [], "model_version_notes": None,
    "tags": [], "last_used_at": STAMP, "use_count": 1, "created_at": STAMP, "updated_at": STAMP,
}


def make_backup(*, core=(), active=(), sessions=(), improvements=(), source=True):
    backup = {
        "success": True, "action": "backup", "schema_version": 1, "complete": True,
        "exported_at": "2026-10-10T00:00:00Z",
    }
    for tier, records in (("core", core), ("active", active), ("sessions", sessions), ("improvements", improvements)):
        backup[tier] = {"count": len(records), "data": deepcopy(list(records))}
    if source:
        backup["source_url"] = ENDPOINT
    return backup


class BackupMemoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.enterContext(patch.object(backup_memory, "BACKUP_DIR", self.directory))
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def write_config(self, environment=None, dotenv=""):
        os.environ.clear()
        os.environ.update(environment or {})
        (self.directory / ".env").write_text(dotenv, encoding="utf-8")

    def test_source_precedence_and_whitespace(self):
        cases = [
            ({"API_SECRET_BACKUP": " env-backup ", "API_SECRET": "env-api"},
             "API_SECRET_BACKUP=dotenv-backup", ("env-backup", "backup")),
            ({"API_SECRET": " env-api "}, "API_SECRET_BACKUP=dotenv-backup", ("dotenv-backup", "backup")),
            ({"API_SECRET_BACKUP": " \t", "API_SECRET": "env-api"}, "API_SECRET_BACKUP=dotenv-backup", ("dotenv-backup", "backup")),
            ({"API_SECRET_BACKUP": " ", "API_SECRET": "\t"},
             'API_SECRET_BACKUP="dotenv-backup"\nAPI_SECRET=dotenv-api', ("dotenv-backup", "backup")),
            ({}, "API_SECRET_BACKUP= 'dotenv-backup' ", ("dotenv-backup", "backup")),
        ]
        for environment, dotenv, expected in cases:
            with self.subTest(expected=expected):
                self.write_config(environment, dotenv)
                self.assertEqual(backup_memory.get_api_credentials(), expected)
                self.assertEqual(backup_memory.get_api_secret(), expected[0])

    def test_valid_environment_does_not_read_dotenv(self):
        os.environ["API_SECRET_BACKUP"] = "environment-dummy"
        with patch.object(backup_memory, "load_env", side_effect=AssertionError("unexpected .env read")):
            self.assertEqual(backup_memory.get_api_credentials(), ("environment-dummy", "backup"))

    def test_missing_credentials_fail_without_personal_file_fallback(self):
        with patch.object(backup_memory.Path, "home", side_effect=AssertionError("personal file access")):
            os.environ["API_SECRET"] = "ignored-generic-dummy"
            with self.assertRaisesRegex(ValueError, "API_SECRET_BACKUP"):
                backup_memory.get_api_credentials()

    def test_dotenv_does_not_mutate_environment(self):
        self.write_config(dotenv=f"MEMORY_API_URL={ENDPOINT}\nAPI_SECRET_BACKUP=dummy")
        self.assertEqual(backup_memory.get_api_url(), ENDPOINT)
        self.assertEqual(backup_memory.get_api_credentials(), ("dummy", "backup"))
        self.assertNotIn("API_SECRET_BACKUP", os.environ)
        self.assertNotIn("MEMORY_API_URL", os.environ)

    def test_target_required_and_validated_before_credentials(self):
        for target in ("", "http://memory.example.test/functions/v1/memory-manager", "https://wrong.test/"):
            with self.subTest(target=target), patch.dict(os.environ, {"MEMORY_API_URL": target}), \
                    patch.object(backup_memory, "get_api_credentials") as credentials, \
                    patch.object(backup_memory, "open_request") as network, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(backup_memory.main(), 1)
                credentials.assert_not_called()
                network.assert_not_called()

    def test_target_from_environment_is_used_and_client_is_bound(self):
        self.write_config({"MEMORY_API_URL": ENDPOINT}, f"MEMORY_API_URL={OTHER_ENDPOINT}")
        for client in ("restore", "backup"):
            with self.subTest(client=client):
                def respond(request):
                    self.assertEqual(request.full_url, f"{ENDPOINT}?action=backup")
                    self.assertEqual(request.get_header("Authorization"), "Bearer dummy")
                    self.assertEqual(request.get_header("X-memory-client"), client)
                    return contextlib.closing(io.BytesIO(json.dumps(make_backup(source=False)).encode()))
                with patch.object(backup_memory, "open_request", side_effect=respond):
                    validate_backup(backup_memory.fetch_backup("dummy", client))

    def test_malformed_or_partial_exports_never_save_or_prune(self):
        old = self.directory / "memory_backup_old.json"
        old.write_text(json.dumps(make_backup(core=[CORE_A])), encoding="utf-8")
        old_time = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
        os.utime(old, (old_time, old_time))
        self.write_config({"MEMORY_API_URL": ENDPOINT, "API_SECRET_BACKUP": "dummy"})
        invalid = [{}, {"success": True}, make_backup(), make_backup(), make_backup(core=[CORE_A])]
        invalid[2]["complete"] = False
        invalid[3]["core"]["count"] = 1
        del invalid[4]["core"]["data"][0]["created_at"]
        for response in invalid:
            with self.subTest(response=response), \
                    patch.object(backup_memory, "fetch_backup", return_value=response), \
                    patch.object(backup_memory, "cleanup_old_backups") as cleanup, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(backup_memory.main(), 1)
                cleanup.assert_not_called()
                self.assertTrue(old.exists())
                self.assertEqual(list(self.directory.glob("memory_backup_*.json")), [old])

    def test_atomic_unique_backups_preserve_source(self):
        data = make_backup(core=[CORE_A], active=[ACTIVE_DONE], sessions=[SESSION], improvements=[IMPROVEMENT], source=False)
        frozen = datetime(2026, 10, 10, tzinfo=timezone.utc)
        with patch.object(backup_memory, "datetime") as time:
            time.now.return_value = frozen
            first, _ = backup_memory.save_backup(data, ENDPOINT)
            second, _ = backup_memory.save_backup(data, ENDPOINT)
        self.assertNotEqual(first, second)
        self.assertEqual(len(list(self.directory.glob("memory_backup_*.json"))), 2)
        manifest = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_url"], ENDPOINT)
        self.assertEqual(manifest["core"]["data"], [CORE_A])
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_interrupted_atomic_publish_exposes_no_partial_backup(self):
        old, _ = backup_memory.save_backup(make_backup(), ENDPOINT)
        with patch.object(backup_memory.os, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                backup_memory.save_backup(make_backup(core=[CORE_A]), ENDPOINT)
        self.assertEqual(list(self.directory.glob("memory_backup_*.json")), [old])
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_retention_requires_valid_new_file_and_preserves_other_sources(self):
        same, _ = backup_memory.save_backup(make_backup(core=[CORE_A]), ENDPOINT)
        other, _ = backup_memory.save_backup(make_backup(core=[CORE_A]), OTHER_ENDPOINT)
        invalid = self.directory / "memory_backup_legacy.json"
        invalid.write_text("{}", encoding="utf-8")
        old_time = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
        for file in (same, other, invalid):
            os.utime(file, (old_time, old_time))
        with self.assertRaises(ValueError):
            backup_memory.cleanup_old_backups(invalid)
        self.assertTrue(same.exists())
        fresh, _ = backup_memory.save_backup(make_backup(), ENDPOINT)
        self.assertEqual(backup_memory.cleanup_old_backups(fresh), 1)
        self.assertFalse(same.exists())
        self.assertTrue(other.exists())
        self.assertTrue(invalid.exists())
        self.assertTrue(fresh.exists())


class SchemaTests(unittest.TestCase):
    def test_empty_complete_export_and_nullable_historical_values_are_valid(self):
        validate_backup(make_backup())
        record = deepcopy(CORE_A)
        for field in ("project", "tags", "importance", "created_at", "updated_at"):
            record[field] = None
        validate_backup(make_backup(core=[record]))
        record["tags"] = ["example", None]
        validate_backup(make_backup(core=[record]))

    def test_version_counts_dates_ids_and_row_types_are_enforced(self):
        valid = make_backup(core=[CORE_A], active=[ACTIVE_DONE], sessions=[SESSION], improvements=[IMPROVEMENT])
        mutations = [
            lambda data: data.update(success=1), lambda data: data.update(schema_version=True),
            lambda data: data.update(exported_at="not-a-time"), lambda data: data.pop("sessions"),
            lambda data: data["core"].update(count=True),
            lambda data: data["core"].update(data={}, count=0),
            lambda data: data["core"]["data"][0].update(id="invalid"),
            lambda data: data["core"]["data"][0].update(created_at="2026-01-01"),
            lambda data: data["core"]["data"][0].update(tags=[1]),
            lambda data: data["core"]["data"][0].update(title=None),
            lambda data: data["core"]["data"][0].update(embedding=[]),
            lambda data: data["active"]["data"][0].update(resolved="false"),
            lambda data: data["sessions"]["data"][0].update(summary=4),
            lambda data: data["improvements"]["data"][0].update(use_count=True),
            lambda data: data["improvements"]["data"][0].update(introduced_at="2026-02-30"),
            lambda data: data["core"].update(data=[CORE_A, CORE_A], count=2),
        ]
        for mutate in mutations:
            data = deepcopy(valid)
            mutate(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_backup(data, require_source=True)

    def test_endpoint_canonicalization_and_rejection(self):
        self.assertEqual(validate_endpoint("https://MEMORY.example.test:443/functions/v1/memory-manager/"), ENDPOINT)
        for host in ("localhost", "127.0.0.1", "[::1]"):
            local = f"http://{host}:54321/functions/v1/memory-manager"
            self.assertEqual(validate_endpoint(local), local)
        for target in (
            None, "", ENDPOINT + "?action=backup", ENDPOINT + "#fragment", ENDPOINT + "\n",
            "https://user:password@memory.example.test/functions/v1/memory-manager",
            "http://localhost.evil.test/functions/v1/memory-manager",
            "file:///functions/v1/memory-manager", "https://memory.example.test/wrong",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_endpoint(target)


class RedirectTests(unittest.TestCase):
    def test_redirect_is_not_followed_with_bearer_token(self):
        received = []
        endpoint = "http://localhost:54321/functions/v1/memory-manager"

        def respond(_handler, request):
            received.append((request.full_url, request.get_header("Authorization")))
            headers = Message()
            headers["Location"] = "https://other.example.test/unexpected-redirect-target"
            response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, code=302)
            response.msg = "Found"
            return response

        # Exercise urllib's real error/redirect chain with an offline HTTP response.
        with patch.object(backup_memory.urllib.request.HTTPHandler, "http_open", respond):
            with self.assertRaises(urllib.error.HTTPError) as error:
                backup_memory.fetch_backup("dummy", "backup", endpoint)
        self.assertEqual(error.exception.code, 302)
        self.assertEqual(received, [(endpoint + "?action=backup", "Bearer dummy")])


if __name__ == "__main__":
    unittest.main()

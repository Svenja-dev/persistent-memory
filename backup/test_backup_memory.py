"""Offline-Regressionen fuer Credential-Auswahl und Backup-Ausgabe."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_memory


class BackupMemoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.secret_file = self.directory / ".claude" / "memory-secret"
        self.secret_file.parent.mkdir()
        self.enterContext(patch.object(backup_memory, "BACKUP_DIR", self.directory))
        self.enterContext(patch.object(backup_memory.Path, "home", return_value=self.directory))
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def write_sources(self, environment=None, dotenv="", shared=""):
        os.environ.clear()
        os.environ.update(environment or {})
        (self.directory / ".env").write_text(dotenv, encoding="utf-8")
        self.secret_file.write_text(shared, encoding="utf-8")

    def test_source_precedence_and_whitespace(self):
        cases = [
            ({"API_SECRET_BACKUP": " env-backup ", "API_SECRET": "env-api"},
             "API_SECRET_BACKUP=dotenv-backup\nAPI_SECRET=dotenv-api", "shared",
             ("env-backup", "backup")),
            ({"API_SECRET": " env-api "}, "API_SECRET_BACKUP=dotenv-backup", "shared",
             ("env-api", None)),
            ({"API_SECRET_BACKUP": " \t", "API_SECRET": "env-api"},
             "API_SECRET_BACKUP=dotenv-backup", "shared", ("env-api", None)),
            ({"API_SECRET_BACKUP": " ", "API_SECRET": "\t"},
             "API_SECRET_BACKUP= dotenv-backup \nAPI_SECRET=dotenv-api", "shared",
             ("dotenv-backup", "backup")),
            ({}, "API_SECRET_BACKUP= \nAPI_SECRET= dotenv-api ", "shared",
             ("dotenv-api", None)),
            ({"API_SECRET": " "}, "API_SECRET_BACKUP= \nAPI_SECRET=\t", " shared\n",
             ("shared", None)),
        ]
        for environment, dotenv, shared, expected in cases:
            with self.subTest(expected=expected):
                self.write_sources(environment, dotenv, shared)
                self.assertEqual(backup_memory.get_api_credentials(), expected)
                self.assertEqual(backup_memory.get_api_secret(), expected[0])

    def test_valid_environment_does_not_read_lower_priority_sources(self):
        os.environ["API_SECRET"] = "environment-dummy"
        with patch.object(backup_memory, "load_env", side_effect=AssertionError("unexpected .env read")), \
                patch.object(backup_memory, "load_secret_file", side_effect=AssertionError("unexpected shared-file read")):
            self.assertEqual(backup_memory.get_api_credentials(), ("environment-dummy", None))

    def test_dotenv_does_not_mutate_environment(self):
        self.write_sources(dotenv="API_SECRET_BACKUP=dotenv-dummy")
        self.assertEqual(backup_memory.get_api_credentials(), ("dotenv-dummy", "backup"))
        self.assertNotIn("API_SECRET_BACKUP", os.environ)

    def test_missing_or_blank_credentials_fail_cleanly(self):
        for shared in (None, " \t\n"):
            with self.subTest(shared=shared):
                if shared is not None:
                    self.secret_file.write_text(shared, encoding="utf-8")
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as error:
                    backup_memory.get_api_credentials()
                self.assertEqual(error.exception.code, 1)
                self.assertIn("Kein API-Secret gefunden", output.getvalue())

    def test_unreadable_shared_file_fails_cleanly(self):
        with patch.object(backup_memory.Path, "read_text", side_effect=PermissionError("denied")):
            self.assertEqual(backup_memory.load_secret_file(), "")
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
                backup_memory.get_api_credentials()
        self.assertEqual(error.exception.code, 1)

    def test_request_client_matches_credential_source(self):
        # Gleicher Auth-Vertrag wie validateApiKey(): expliziter Client bindet
        # an dessen Secret; ohne Client werden alle konfigurierten Keys akzeptiert.
        configured = {"backup": "backup-dummy", "claude_code": "claude-dummy"}
        legacy = "generic-dummy"
        cases = [
            ({"API_SECRET_BACKUP": configured["backup"]}, "", "", "backup"),
            ({}, "API_SECRET_BACKUP=backup-dummy", "", "backup"),
            ({"API_SECRET": legacy}, "", "", None),
            ({}, "API_SECRET=generic-dummy", "", None),
            ({}, "", legacy, None),
            ({}, "", configured["claude_code"], None),
        ]
        for environment, dotenv, shared, expected_client in cases:
            with self.subTest(environment=environment, dotenv=dotenv, shared=shared):
                self.write_sources(environment, dotenv, shared)
                token, client = backup_memory.get_api_credentials()

                def respond(request, timeout):
                    sent_client = request.get_header("X-memory-client")
                    sent_token = request.get_header("Authorization").removeprefix("Bearer ")
                    self.assertEqual(sent_client, expected_client)
                    self.assertEqual(timeout, 30)
                    if sent_client:
                        self.assertEqual(sent_token, configured[sent_client])
                    else:
                        self.assertIn(sent_token, {*configured.values(), legacy})
                    return contextlib.closing(io.BytesIO(json.dumps({"success": True}).encode()))

                with patch.object(backup_memory.urllib.request, "urlopen", side_effect=respond):
                    self.assertTrue(backup_memory.fetch_backup(token, client)["success"])

    def test_improvements_summary_and_older_backup_response(self):
        for data, count in (({"improvements": {"count": 7}}, 7), ({}, 0)):
            with self.subTest(data=data):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    backup_memory.print_summary(data, Path("dummy.json"), 1.0, 0)
                self.assertIn(f"Improvements: {count} Eintraege", output.getvalue())


if __name__ == "__main__":
    unittest.main()

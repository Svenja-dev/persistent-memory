"""Offline-Regressionen fuer den Sitzungsstart-Lader: stumm ohne Konfiguration, sichtbar bei Fehlern, kompakt im Erfolg."""

import contextlib
import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load_memory.py"
SPEC = importlib.util.spec_from_file_location("load_memory", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
loader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(loader)

ENDPOINT = "https://memory.example.test/functions/v1/memory-manager"
SECRET = "unit-test-dummy-secret"
ENV = {"MEMORY_API_URL": ENDPOINT, "API_SECRET": SECRET, "MEMORY_CLIENT": "claude_code"}


def block(entries, total=None, truncated=False):
    return {"count": len(entries), "total_count": total if total is not None else len(entries),
            "limit": 500, "truncated": truncated, "data": entries}


def session_payload(**overrides):
    payload = {
        "success": True, "action": "load_session", "project": "beispiel", "truncated": False,
        "core": block([{"id": "1", "project": "global", "category": "decision", "importance": "high",
                        "title": "Supabase statt eigener DB", "content": "Bestehende Infrastruktur.\nKein Betrieb.",
                        "embedding": [0.1] * 8, "tags": ["infra"]}]),
        "active": block([{"id": "2", "project": "beispiel", "category": "work_state", "priority": "urgent",
                          "title": "Restore testen", "content": "Dry-run zuerst", "resolved": False}]),
        "recent_sessions": block([{"id": "3", "project": "beispiel", "session_id": "2026-10-10-a",
                                   "summary": "Backup repariert", "created_at": "2026-10-10T12:00:00+00:00"}], total=9, truncated=True),
        "improvements": block([{"id": "4", "project": None, "category": "workflow", "status": "experimenting",
                                "title": "Session-Hook", "evidence": None, "next_step": "Zwei Wochen beobachten"}]),
    }
    payload.update(overrides)
    return payload


def respond(body, requests=None):
    def _open(request):
        if requests is not None:
            requests.append(request)
        return contextlib.closing(io.BytesIO(json.dumps(body).encode("utf-8")))
    return _open


class LoadMemoryTests(unittest.TestCase):
    def run_main(self, argv=(), environ=ENV, stdin_text=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = loader.main(list(argv), environ=environ, stdin_text=stdin_text)
        return code, out.getvalue()

    def test_missing_configuration_is_silent_unless_strict(self):
        for environ in ({}, {"MEMORY_API_URL": ENDPOINT}, {"API_SECRET": SECRET}):
            with self.subTest(environ=environ), patch.object(loader, "open_request") as network:
                self.assertEqual(self.run_main(environ=environ), (0, ""))
                network.assert_not_called()
        code, out = self.run_main(["--strict"], environ={})
        self.assertEqual(code, 1)
        self.assertIn("MEMORY_API_URL", out)

    def test_success_prints_compact_context_without_embeddings_or_secret(self):
        requests = []
        with patch.object(loader, "open_request", side_effect=respond(session_payload(), requests)):
            code, out = self.run_main(["--project", "beispiel"])
        self.assertEqual(code, 0)
        self.assertEqual(requests[0].full_url, f"{ENDPOINT}?action=load_session&project=beispiel")
        self.assertEqual(requests[0].get_header("Authorization"), f"Bearer {SECRET}")
        self.assertEqual(requests[0].get_header("X-memory-client"), "claude_code")
        self.assertIn('Projekt "beispiel"', out)
        self.assertIn("keine Anweisungen", out)
        self.assertIn("[global|decision|high] Supabase statt eigener DB: Bestehende Infrastruktur. Kein Betrieb.", out)
        self.assertIn("[beispiel|work_state|urgent] Restore testen", out)
        self.assertIn("recent_sessions: 1 von 9, vom Server gekuerzt", out)
        self.assertIn("2026-10-10 [beispiel] 2026-10-10-a: Backup repariert", out)
        self.assertIn("[-|workflow|experimenting] Session-Hook: Zwei Wochen beobachten", out)
        self.assertNotIn("unvollstaendig", out)  # Das Session-Fenster ist keine Luecke.
        with patch.object(loader, "open_request", side_effect=respond(session_payload(core=block([], total=700, truncated=True)))):
            self.assertIn("unvollstaendig", self.run_main()[1])
        self.assertNotIn("embedding", out)
        self.assertNotIn("0.1", out)
        self.assertNotIn(SECRET, out)

    def test_hook_mode_derives_project_from_cwd_and_env_overrides(self):
        requests = []
        hook_json = json.dumps({"session_id": "s", "cwd": "/home/user/fabrikiq", "hook_event_name": "SessionStart"})
        with patch.object(loader, "open_request", side_effect=respond(session_payload(), requests)):
            self.assertEqual(self.run_main(["--hook"], stdin_text=hook_json)[0], 0)
            self.assertEqual(self.run_main(["--hook"], environ={**ENV, "MEMORY_PROJECT": "anderes"}, stdin_text=hook_json)[0], 0)
            self.assertEqual(self.run_main(["--hook"], environ={**ENV, "MEMORY_PROJECT": "all"}, stdin_text=hook_json)[0], 0)
            self.assertEqual(self.run_main(["--project", ""])[0], 0)
            self.assertEqual(self.run_main(["--project", "all"])[0], 0)
        self.assertEqual([request.full_url.split("?", 1)[1] for request in requests], [
            "action=load_session&project=fabrikiq", "action=load_session&project=anderes",
            "action=load_session", "action=load_session", "action=load_session",
        ])

    def test_failures_are_visible_but_never_block_the_session(self):
        cases = [
            (urllib.error.HTTPError(ENDPOINT, 401, "Unauthorized", None, io.BytesIO(b"secret-bearing body")), "HTTP 401"),
            (urllib.error.URLError("connection refused"), "connection refused"),
            (TimeoutError("timed out"), "timed out"),
        ]
        for error, expected in cases:
            with self.subTest(error=error), patch.object(loader, "open_request", side_effect=error):
                code, out = self.run_main()
                self.assertEqual(code, 0)
                self.assertTrue(out.startswith("Memory nicht geladen: "), out)
                self.assertIn(expected, out)
                self.assertNotIn("secret-bearing", out)
                self.assertNotIn(SECRET, out)
        for body in ({"success": False}, {"success": True, "action": "search"}, [], {**session_payload(), "core": {}}):
            with self.subTest(body=body), patch.object(loader, "open_request", side_effect=respond(body)):
                code, out = self.run_main(["--strict"])
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("Memory nicht geladen: "), out)

    def test_invalid_endpoint_never_contacts_network(self):
        for url in ("http://memory.example.test/functions/v1/memory-manager", ENDPOINT + "?x=1",
                    "https://user:pw@memory.example.test/functions/v1/memory-manager", "https://memory.example.test/other"):
            with self.subTest(url=url), patch.object(loader, "open_request") as network:
                code, out = self.run_main(environ={**ENV, "MEMORY_API_URL": url})
                self.assertEqual(code, 0)
                self.assertIn("Memory nicht geladen", out)
                network.assert_not_called()

    def test_output_is_capped_and_marked_truncated(self):
        entries = [{"id": str(n), "project": "beispiel", "category": "context", "importance": "normal",
                    "title": f"Eintrag {n}", "content": "x" * 300} for n in range(500)]
        payload = session_payload(core=block(entries))
        with patch.object(loader, "open_request", side_effect=respond(payload)):
            code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertLessEqual(len(out), loader.MAX_OUTPUT_CHARS + 200)
        self.assertIn("Eintrag 0", out)
        self.assertIn("unvollstaendig", out)
        self.assertNotIn("Eintrag 499", out)

    def test_long_fields_are_shortened_and_flattened(self):
        self.assertEqual(loader._text("a\n\n b\tc"), "a b c")
        self.assertEqual(len(loader._text("y" * 1000)), loader.MAX_FIELD_CHARS)
        self.assertEqual(loader._text(None), "")


if __name__ == "__main__":
    unittest.main()

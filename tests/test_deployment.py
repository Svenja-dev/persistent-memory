"""Run the actual deployment script with local PowerShell command doubles."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
PROJECT = "abcdefghijklmnopqrst"


@unittest.skipUnless(PWSH, "PowerShell 7 is required for deployment contract tests")
class DeploymentTests(unittest.TestCase):
    def run_deploy(self, mode="ok", arguments=None, key=True):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            shutil.copy2(ROOT / "deploy.ps1", folder / "deploy.ps1")
            (folder / "wrapper.ps1").write_text(r'''
$ErrorActionPreference = 'Stop'
function global:supabase {
    ConvertTo-Json -InputObject @($args) -Compress | Add-Content -LiteralPath (Join-Path $PSScriptRoot 'calls.jsonl')
    $global:LASTEXITCODE = if ($env:TEST_MODE -eq 'cli-error') { 9 } else { 0 }
}
function global:Invoke-RestMethod {
    param($Uri, $Headers, $Method, $TimeoutSec, $MaximumRedirection)
    @{ uri = $Uri; client = $Headers['X-Memory-Client'] } | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'request.json')
    if ($env:TEST_MODE -eq 'http-error') { throw 'synthetic network failure' }
    if ($env:TEST_MODE -eq 'bad-response') { return @{ success = $false } }
    return @{ success = $true; action = 'load_session'; core = @{count=0}; active = @{count=0}; recent_sessions = @{count=0}; improvements = @{count=0} }
}
& (Join-Path $PSScriptRoot 'deploy.ps1') @args
exit $LASTEXITCODE
''', encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if not k.startswith("API_SECRET")}
            env["TEST_MODE"] = mode
            if key:
                env["API_SECRET_API"] = "dummy-deployment-test-key"
            result = subprocess.run(
                [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(folder / "wrapper.ps1"),
                 *(arguments if arguments is not None else ["-ProjectRef", PROJECT])],
                text=True, capture_output=True, env=env, timeout=30,
            )
            calls_path = folder / "calls.jsonl"
            calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8-sig").splitlines()] if calls_path.exists() else []
            request_path = folder / "request.json"
            request = json.loads(request_path.read_text(encoding="utf-8-sig")) if request_path.exists() else None
            self.assertNotIn("dummy-deployment-test-key", result.stdout + result.stderr)
            return result, calls, request

    def test_explicit_target_used_for_link_deploy_and_smoke(self):
        result, calls, request = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["link", "--project-ref", PROJECT], calls)
        self.assertTrue(any(call[:3] == ["functions", "deploy", "memory-manager"] and PROJECT in call for call in calls))
        self.assertEqual(request["uri"], f"https://{PROJECT}.supabase.co/functions/v1/memory-manager?action=load_session")
        self.assertEqual(request["client"], "api")

    def test_no_target_or_invalid_target_never_calls_cli(self):
        for arguments in ([], ["-ProjectRef", "invalid"]):
            with self.subTest(arguments=arguments):
                result, calls, _ = self.run_deploy(arguments=arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_missing_smoke_key_fails_before_mutation(self):
        result, calls, _ = self.run_deploy(key=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_explicit_skip_smoke_needs_no_key(self):
        result, calls, request = self.run_deploy(arguments=["-ProjectRef", PROJECT, "-SkipSmokeTest"], key=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(calls)
        self.assertIsNone(request)
        self.assertIn("uebersprungen", result.stdout)

    def test_failed_cli_or_smoke_has_nonzero_exit(self):
        for mode in ("cli-error", "http-error", "bad-response"):
            with self.subTest(mode=mode):
                result, _, _ = self.run_deploy(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Deployment abgeschlossen", result.stdout)


if __name__ == "__main__":
    unittest.main()

"""Exercise package boundaries using synthetic private files only."""

import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_skill.py"
SPEC = importlib.util.spec_from_file_location("build_skill", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class SkillPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "repository"
        self.source.mkdir()
        (self.source / "SKILL.md").write_text(
            "---\nname: persistent-memory\ndescription: Synthetic test.\n---\n", encoding="utf-8"
        )
        (self.source / "LICENSE").write_text("Synthetic license for test\n", encoding="utf-8")

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"OS cannot create test symlinks: {error}")

    def test_only_approved_files_even_with_injected_secrets_and_backups(self):
        marker = "SYNTHETIC_PRIVATE_CONTENT_NOT_FOR_PUBLICATION"
        for filename in (
            ".env", "backup/.env", "backup/memory_backup_test.json", ".git/config",
            "supabase/.temp/project-ref", "settings.local.json", "archive/slack.json",
        ):
            private = self.source / filename
            private.parent.mkdir(parents=True, exist_ok=True)
            private.write_text(marker, encoding="utf-8")
        artifact = builder.build_skill(self.source)
        with zipfile.ZipFile(artifact) as archive:
            self.assertEqual(archive.namelist(), [
                "persistent-memory/LICENSE", "persistent-memory/SKILL.md",
            ])
            for member in archive.infolist():
                self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(member.external_attr >> 16, stat.S_IFREG | 0o644)
                self.assertNotIn(marker.encode(), archive.read(member))

    def test_reproducible_across_mtime_and_output_filename(self):
        first = builder.build_skill(self.source).read_bytes()
        for filename in builder.APPROVED_FILES:
            os.utime(self.source / filename, (1_500_000_000, 1_500_000_000))
        second = builder.build_skill(self.source, Path("dist/second.zip")).read_bytes()
        self.assertEqual(first, second)

    def test_rejects_unsafe_output_without_overwriting_source(self):
        original = (self.source / "SKILL.md").read_bytes()
        for output in ("SKILL.md", ".env", "other.zip", "dist/../outside.zip", "dist/.env"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                builder.build_skill(self.source, Path(output))
        with self.assertRaises(ValueError):
            builder.build_skill(self.source, Path(self.temporary.name) / "outside.zip")
        self.assertEqual((self.source / "SKILL.md").read_bytes(), original)

    def test_missing_document_keeps_existing_package_and_no_partial_file(self):
        artifact = builder.build_skill(self.source)
        original = artifact.read_bytes()
        (self.source / "LICENSE").unlink()
        with self.assertRaises(OSError):
            builder.build_skill(self.source)
        self.assertEqual(artifact.read_bytes(), original)
        self.assertEqual(list(artifact.parent.glob(".skill-*.tmp")), [])

    def test_failed_atomic_commit_keeps_previous_package(self):
        artifact = builder.build_skill(self.source)
        original = artifact.read_bytes()
        with patch.object(builder.os, "replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                builder.build_skill(self.source)
        self.assertEqual(artifact.read_bytes(), original)
        self.assertEqual(list(artifact.parent.glob(".skill-*.tmp")), [])

    def test_rejects_symlink_document(self):
        private = self.source / ".env"
        private.write_text("SYNTHETIC_PRIVATE_CONTENT", encoding="utf-8")
        (self.source / "SKILL.md").unlink()
        self.symlink(self.source / "SKILL.md", private)
        with self.assertRaises(ValueError):
            builder.build_skill(self.source)

    def test_rejects_symlink_output_directory(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        self.symlink(self.source / "dist", outside, directory=True)
        with self.assertRaises(ValueError):
            builder.build_skill(self.source)
        self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_symlink_output_file(self):
        artifact = builder.build_skill(self.source)
        artifact.unlink()
        private = self.source / ".env"
        private.write_text("SYNTHETIC_PRIVATE_CONTENT", encoding="utf-8")
        self.symlink(artifact, private)
        with self.assertRaises(ValueError):
            builder.build_skill(self.source)
        self.assertEqual(private.read_text(encoding="utf-8"), "SYNTHETIC_PRIVATE_CONTENT")

    def test_rejects_symlink_source_directory(self):
        alias = Path(self.temporary.name) / "alias"
        self.symlink(alias, self.source, directory=True)
        with self.assertRaises(ValueError):
            builder.build_skill(alias)

    def test_rejects_binary_and_empty_approved_documents(self):
        for data in (b"", b"\0binary", b"\xff\xfe"):
            with self.subTest(data=data):
                (self.source / "SKILL.md").write_bytes(data)
                with self.assertRaises(ValueError):
                    builder.build_skill(self.source)


if __name__ == "__main__":
    unittest.main()

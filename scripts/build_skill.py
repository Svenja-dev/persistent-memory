"""Build the same instruction-only skill for Cowork and Codex (Python 3.11+)."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile


APPROVED_FILES = ("LICENSE", "SKILL.md")
ARCHIVE_ROOT = "persistent-memory"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_DOCUMENT_BYTES = 256 * 1024


def reject_links(path: Path) -> None:
    """Reject symlinks, Windows junctions and other reparse points in a path."""
    for component in (path, *path.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ValueError(f"Links/reparse points are not allowed: {component}")


def build_skill(source: Path, output: Path | None = None) -> Path:
    """Package only approved files; output must be a ZIP directly inside dist/."""
    if ".." in source.parts:
        raise ValueError("Source must not contain parent traversal")
    source = source.absolute()
    reject_links(source)
    if not source.is_dir():
        raise ValueError("Source must be an existing directory")

    output = output or Path("dist/persistent-memory.zip")
    if ".." in output.parts:
        raise ValueError("Output must not contain parent traversal")
    if not output.is_absolute():
        output = source / output
    reject_links(output)
    if output.parent != source / "dist" or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip", output.name
    ):
        raise ValueError("Output must be a named .zip file directly inside source/dist/")
    if output.exists() and not output.is_file():
        raise ValueError("Output must be a regular file")

    documents: list[tuple[str, bytes]] = []
    for filename in APPROVED_FILES:
        document = source / filename
        reject_links(document)
        metadata = document.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"Approved source is not a regular file: {filename}")
        if metadata.st_size > MAX_DOCUMENT_BYTES:
            raise ValueError(f"Approved document exceeds size limit: {filename}")
        contents = document.read_bytes()
        contents.decode("utf-8")
        if not contents.strip() or b"\0" in contents:
            raise ValueError(f"Approved document is empty or contains binary data: {filename}")
        documents.append((filename, contents))

    output.parent.mkdir(exist_ok=True)
    reject_links(output.parent)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b", prefix=".skill-", suffix=".tmp", dir=output.parent, delete=False
        ) as staging:
            temporary = Path(staging.name)
            with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_STORED) as archive:
                for filename, contents in documents:
                    member = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{filename}", ZIP_TIMESTAMP)
                    member.create_system = 3
                    member.external_attr = (stat.S_IFREG | 0o644) << 16
                    member.compress_type = zipfile.ZIP_STORED
                    archive.writestr(member, contents)
            staging.flush()
            os.fsync(staging.fileno())
        reject_links(output)
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).absolute().parent.parent)
    parser.add_argument("--output", type=Path, default=Path("dist/persistent-memory.zip"))
    args = parser.parse_args()
    try:
        artifact = build_skill(args.source, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Skill package failed: {error}\n")
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    print(f"Built {artifact}\nSHA256 {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

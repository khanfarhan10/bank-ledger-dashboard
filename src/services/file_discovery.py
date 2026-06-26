"""Discover bank statement files under the read-only source folder.

This module only *reads* the filesystem. It walks ``all_bank_statements/`` and
returns a list of discovered files together with a checksum, so the rest of the
app knows what is available without ever writing to the source tree.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from src.utils.logging_setup import get_logger

# Source statements we know how to (or will) handle.
SUPPORTED_EXTENSIONS = {".xls", ".xlsx", ".pdf"}

DEFAULT_SOURCE_DIR = Path("all_bank_statements")


@dataclass
class DiscoveredFile:
    """One source file found under the read-only folder."""

    path: Path
    bank_folder: str   # immediate parent folder name, e.g. 'ICICI'
    extension: str
    size_bytes: int
    checksum: str      # sha256 of file contents (integrity / change detection)

    @property
    def name(self) -> str:
        return self.path.name


def discover_files(source_dir: Path | str = DEFAULT_SOURCE_DIR) -> list[DiscoveredFile]:
    """Return all supported statement files under ``source_dir`` (read-only).

    Files are sorted by bank folder then name for stable display. A checksum is
    computed for each file and logged, satisfying the "log what files were read"
    safety requirement.
    """
    logger = get_logger()
    source_dir = Path(source_dir)
    found: list[DiscoveredFile] = []

    if not source_dir.exists():
        logger.warning("Source directory does not exist: %s", source_dir)
        return found

    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        checksum = _sha256(path)
        found.append(
            DiscoveredFile(
                path=path,
                bank_folder=path.parent.name,
                extension=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                checksum=checksum,
            )
        )
        logger.info("Discovered source file: %s (sha256=%s)", path, checksum[:12])

    logger.info("Discovered %d source file(s) under %s", len(found), source_dir)
    return found


def _sha256(path: Path) -> str:
    """Compute the sha256 checksum of a file, reading it in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

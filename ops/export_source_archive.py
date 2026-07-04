#!/usr/bin/env python3
"""Create a safe source archive for sharing the RESTO project.

The archive intentionally excludes local secrets, virtual environments,
repository metadata, runtime databases, collected static files, uploaded media,
old patch artifacts, and build/test caches.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

DEFAULT_ARCHIVE_PREFIX = "resto_source"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".nox",
    ".idea",
    ".vscode",
    "node_modules",
    "staticfiles",
    "mediafiles",
    "media",
    "htmlcov",
    "build",
    "dist",
}

EXCLUDED_DIR_GLOBS = (
    ".tmp-*",
    "tmp-*",
    "postgres_data",
    "pgdata",
)

EXCLUDED_FILE_NAMES = {
    ".coverage",
    ".dmypy.json",
    "db.sqlite3",
    "db.sqlite3-journal",
    "desktop.ini",
    "Thumbs.db",
    ".DS_Store",
    "secrets.json",
    "FILES_TO_REPLACE.txt",
    "PATCH_FILE_HASHES.txt",
    "SHA256SUMS.txt",
}

EXCLUDED_FILE_GLOBS = (
    ".env",
    ".env.*",
    "*.sqlite3",
    "*.sqlite3-journal",
    "*.db",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.log",
    "*.pem",
    "*.key",
    "*.crt",
    "*.dump",
    "*.backup",
    "*.bak",
    "*.tmp",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.7z",
    "*.rar",
    "PATCH_*_README*.md",
    "tmp-*.png",
)

ALLOWED_ENV_EXAMPLES = {".env.example", ".env.local.example"}


@dataclass(frozen=True)
class ArchivePlan:
    root: Path
    output: Path
    files: tuple[Path, ...]


def _as_posix(path: Path) -> str:
    return path.as_posix()


def _matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _is_output_path(path: Path, output: Path) -> bool:
    try:
        path.resolve().relative_to(output.resolve().parent)
    except ValueError:
        return False
    return path.resolve() == output.resolve()


def should_include_file(relative_path: Path) -> bool:
    """Return True when a project file is safe to include in a source archive."""

    parts = relative_path.parts
    if not parts:
        return False

    for part in parts[:-1]:
        if part in EXCLUDED_DIR_NAMES or _matches_any(part, EXCLUDED_DIR_GLOBS):
            return False

    filename = parts[-1]
    if filename in ALLOWED_ENV_EXAMPLES:
        return True
    if filename in EXCLUDED_FILE_NAMES or _matches_any(filename, EXCLUDED_FILE_GLOBS):
        return False
    if filename.startswith(".env"):
        return False

    return True


def collect_source_files(root: Path, output: Path) -> tuple[Path, ...]:
    root = root.resolve()
    output = output.resolve()
    files: list[Path] = []

    for current_root, dir_names, file_names in os.walk(root):
        current_path = Path(current_root)
        relative_root = current_path.relative_to(root)

        kept_dirs: list[str] = []
        for dirname in dir_names:
            relative_dir = relative_root / dirname if str(relative_root) != "." else Path(dirname)
            if dirname in EXCLUDED_DIR_NAMES or _matches_any(dirname, EXCLUDED_DIR_GLOBS):
                continue
            if not should_include_file(relative_dir / "__dummy__"):
                continue
            kept_dirs.append(dirname)
        dir_names[:] = kept_dirs

        for filename in file_names:
            path = current_path / filename
            if _is_output_path(path, output):
                continue
            relative_path = path.relative_to(root)
            if should_include_file(relative_path):
                files.append(relative_path)

    return tuple(sorted(files, key=lambda item: _as_posix(item).lower()))


def default_output_path(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return root / "dist" / f"{DEFAULT_ARCHIVE_PREFIX}_{stamp}.zip"


def build_archive_plan(root: Path, output: Path | None = None) -> ArchivePlan:
    root = root.resolve()
    if output is None:
        output = default_output_path(root)
    else:
        output = output.resolve()
    files = collect_source_files(root, output)
    return ArchivePlan(root=root, output=output, files=files)


def write_source_archive(plan: ArchivePlan) -> None:
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(plan.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in plan.files:
            archive.write(plan.root / relative_path, PurePosixPath(relative_path).as_posix())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a safe RESTO source archive without secrets or runtime artifacts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Project root. Defaults to the parent of the ops directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output ZIP path. Defaults to dist/resto_source_<UTC timestamp>.zip.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the file list without creating an archive.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    plan = build_archive_plan(args.root, args.output)

    if args.dry_run:
        for relative_path in plan.files:
            print(_as_posix(relative_path))
        print(f"\n{len(plan.files)} files would be archived.", file=sys.stderr)
        return 0

    write_source_archive(plan)
    print(f"Created {plan.output}")
    print(f"Included {len(plan.files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

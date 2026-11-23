#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_zip.py — package this QGIS plugin into a ZIP ready for plugins.qgis.org.

ZIP layout rules enforced by the QGIS plugin repository:
  * after extraction there must be exactly ONE top-level folder;
  * its name may contain only ASCII letters, digits, underscores and hyphens,
    and must not start with a digit;
  * it must contain metadata.txt, __init__.py and LICENSE (no file extension);
  * never ship .git, __pycache__, build output or local config files.

Usage:
    python build_zip.py                   # -> dist/pro_toolbox-1.0.0.zip
    python build_zip.py --dry-run         # list files without writing anything
    python build_zip.py --name my_plugin  # override the root folder name in the ZIP
    python build_zip.py --with-docs       # also include docs/

Compatibility: standard library only, Python 3.6+; runs fine with QGIS' bundled python.
"""

from __future__ import annotations

import argparse
import configparser
import os
import re
import sys
import zipfile
from pathlib import Path

# --------------------------------------------------------------------------
# Root folder name inside the ZIP = QGIS plugin directory name.
# Do not change it after the first release: it is effectively the plugin ID.
# --------------------------------------------------------------------------
PLUGIN_ID = "pro_toolbox"
PLUGIN_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

REQUIRED_FILES = ("metadata.txt", "__init__.py", "LICENSE")
REQUIRED_META_KEYS = (
    "name",
    "qgisMinimumVersion",
    "description",
    "about",
    "version",
    "author",
    "email",
    "repository",
)

# Directories skipped anywhere in the tree (dot-directories are always skipped)
EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".gitlab",
    ".idea",
    ".vscode",
    ".vs",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "docs",  # excluded by default; --with-docs enables it (see collect_files)
    "assets",  # repo-only branding shown by the README, not a runtime asset
}

# Files skipped anywhere in the tree
EXCLUDED_FILES = {
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    "build_zip.py",           # build tooling is not part of the runtime
    "numpad_macro_config.json",  # local macro config, may contain business text
    "desktop.ini",
    ".DS_Store",
    "Thumbs.db",
    "symbology-style.db",      # QGIS-generated local style database, never part of the plugin
}

EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo",
    ".zip", ".7z", ".rar",
    ".log", ".bak", ".tmp", ".swp",
    ".unpacked",  # marker left after unpacking an offline wheel
}


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return "%.2f %s" % (num, unit) if unit != "B" else "%d B" % num
        num /= 1024.0
    return "%d B" % num


def read_metadata(root: Path) -> configparser.RawConfigParser:
    path = root / "metadata.txt"
    if not path.exists():
        sys.exit("[ERROR] metadata.txt not found: %s" % path)

    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str  # keep key case, e.g. qgisMinimumVersion
    try:
        parser.read_string(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # pragma: no cover - only when metadata is broken
        sys.exit("[ERROR] Failed to parse metadata.txt: %s" % exc)

    if not parser.has_section("general"):
        sys.exit("[ERROR] metadata.txt has no [general] section")

    missing = [k for k in REQUIRED_META_KEYS if not parser.get("general", k, fallback="").strip()]
    if missing:
        sys.exit("[ERROR] metadata.txt is missing required fields: %s" % ", ".join(missing))

    return parser


def is_libs_artifact(rel: Path) -> bool:
    """Only wheels are kept under libs/: unpacked packages, dist-info and markers are skipped."""
    return bool(rel.parts) and rel.parts[0] == "libs" and rel.suffix.lower() != ".whl"


def collect_files(root: Path, with_docs: bool, keep_libs: bool):
    """Return (files to pack, number of skipped entries)."""
    files, skipped = [], 0

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)

        keep_dirs = []
        for name in sorted(dirnames):
            if name == "docs":
                if with_docs:
                    keep_dirs.append(name)
                else:
                    skipped += 1
                continue
            if name.startswith(".") or name in EXCLUDED_DIRS or name.startswith("Backup_"):
                skipped += 1
                continue
            keep_dirs.append(name)
        dirnames[:] = keep_dirs

        for name in sorted(filenames):
            path = current / name
            rel = path.relative_to(root)

            if name.startswith(".") or name in EXCLUDED_FILES:
                skipped += 1
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                skipped += 1
                continue
            if name.startswith("Backup_"):
                skipped += 1
                continue
            if is_libs_artifact(rel) and not keep_libs:
                skipped += 1
                continue

            files.append(rel)

    return files, skipped


def build_zip(root: Path, project_id: str, files, out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            src = root / rel
            arcname = "%s/%s" % (project_id, rel.as_posix())
            zf.write(src, arcname)
            total += src.stat().st_size

    return total


def verify_zip(out_path: Path, project_id: str) -> None:
    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()

    if not names:
        sys.exit("[ERROR] ZIP is empty")

    bad = [n for n in names if not n.startswith(project_id + "/")]
    if bad:
        sys.exit("[ERROR] Entries outside the %s/ root: %s" % (project_id, bad[:5]))

    required = {"%s/%s" % (project_id, f) for f in ("metadata.txt", "__init__.py")}
    missing = required - set(names)
    if missing:
        sys.exit("[ERROR] ZIP is missing required files: %s" % ", ".join(sorted(missing)))

    if any("__pycache__" in n or n.endswith((".pyc", ".pyo")) for n in names):
        sys.exit("[ERROR] Python cache files leaked into the ZIP")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="Package this QGIS plugin into a ZIP ready for plugins.qgis.org.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--name", default=PLUGIN_ID, help="root folder name inside the ZIP (default: %(default)s)")
    ap.add_argument("--output", default=None, help="output ZIP path (default: dist/<name>-<version>.zip)")
    ap.add_argument("--with-docs", action="store_true", help="include docs/")
    ap.add_argument("--keep-libs", action="store_true", help="keep unpacked dependencies under libs/ (only *.whl by default)")
    ap.add_argument("--dry-run", "--list", dest="dry_run", action="store_true", help="list files without writing a ZIP")
    args = ap.parse_args()

    project_id = args.name.strip()
    if not PLUGIN_ID_RE.match(project_id):
        sys.exit("[ERROR] Invalid root folder name: %r (ASCII letters/digits/_/- only, no leading digit)" % project_id)

    root = Path(__file__).resolve().parent
    print("[Pro Toolbox] Plugin directory: %s" % root)

    meta = read_metadata(root)
    version = meta.get("general", "version")
    print("[OK] metadata.txt: name=%s, version=%s, qgisMinimumVersion=%s"
          % (meta.get("general", "name"),
             version,
             meta.get("general", "qgisMinimumVersion", fallback="?")))

    missing_required = [f for f in REQUIRED_FILES if not (root / f).is_file()]
    if missing_required:
        sys.exit("[ERROR] Missing files required for release: %s" % ", ".join(missing_required))

    files, skipped = collect_files(root, args.with_docs, args.keep_libs)
    if not files:
        sys.exit("[ERROR] No files collected")

    print("[OK] Collected %d file(s), skipped %d item(s)" % (len(files), skipped))

    if args.dry_run:
        print("\nFiles to package (root %s/):" % project_id)
        for rel in files:
            print("  %s/%s" % (project_id, rel.as_posix()))
        print("\n[dry-run] No ZIP written.")
        return

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = root / "dist" / ("%s-%s.zip" % (project_id, version))

    raw_size = build_zip(root, project_id, files, out_path)
    verify_zip(out_path, project_id)

    zip_size = out_path.stat().st_size
    print("[OK] Written: %s" % out_path)
    print("     raw %s -> zip %s (%.1f%%)"
          % (human_size(raw_size), human_size(zip_size),
             100.0 * zip_size / raw_size if raw_size else 0.0))
    print("     Layout OK: every entry lives under %s/ and metadata.txt / __init__.py are present" % project_id)
    print("\nNext: upload this ZIP at https://plugins.qgis.org/plugins/add/ (or test it first with QGIS 'Install from ZIP').")


if __name__ == "__main__":
    main()

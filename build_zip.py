#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_zip.py —— 把当前插件目录打包成 QGIS 官方插件仓库可上传的 ZIP。

QGIS 插件的 ZIP 结构校验规则（plugins.qgis.org）：
  * 解压后第一层必须是【一个】文件夹；
  * 文件夹名只允许 ASCII 字母、数字、下划线、连字符，且不能以数字开头；
  * 文件夹内必须存在 metadata.txt、__init__.py 与 LICENSE（LICENSE 不带扩展名）；
  * 不要把 .git、__pycache__、构建产物、本地配置等垃圾打进去。

用法：
    python build_zip.py                   # -> dist/qgis_pro_tools-1.0.0.zip
    python build_zip.py --dry-run         # 只列出将要打包的文件，不落盘
    python build_zip.py --name my_plugin  # 覆盖 ZIP 内的根目录名
    python build_zip.py --with-docs       # 额外把 docs/ 打进去

兼容性：仅依赖 Python 3.6+ 标准库，可直接用 QGIS 自带的 python 运行。
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
# ZIP 内的根目录名 = QGIS 插件目录名，发布后不要再改（等于改插件 ID）
# --------------------------------------------------------------------------
PLUGIN_ID = "qgis_pro_tools"
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

# 任何位置出现都直接跳过的目录（点号开头的目录一律跳过）
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
    "docs",  # 默认不打包，--with-docs 可打开（见 collect_files）
}

# 任何位置出现都直接跳过的文件
EXCLUDED_FILES = {
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    "build_zip.py",           # 构建脚本本身不属于运行时
    "numpad_macro_config.json",  # 本地宏配置，可能含业务文本
    "desktop.ini",
    ".DS_Store",
    "Thumbs.db",
}

EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo",
    ".zip", ".7z", ".rar",
    ".log", ".bak", ".tmp", ".swp",
    ".unpacked",  # 离线 wheel 的解压戳记
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
        sys.exit("[ERROR] 找不到 metadata.txt：%s" % path)

    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str  # 保留 qgisMinimumVersion 这类大小写
    try:
        parser.read_string(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # pragma: no cover - 只在 metadata 损坏时触发
        sys.exit("[ERROR] metadata.txt 解析失败：%s" % exc)

    if not parser.has_section("general"):
        sys.exit("[ERROR] metadata.txt 缺少 [general] 段")

    missing = [k for k in REQUIRED_META_KEYS if not parser.get("general", k, fallback="").strip()]
    if missing:
        sys.exit("[ERROR] metadata.txt 缺少官方必填字段：%s" % ", ".join(missing))

    return parser


def is_libs_artifact(rel: Path) -> bool:
    """libs/ 下只保留 wheel：解压出来的包、dist-info、戳记全部跳过。"""
    return bool(rel.parts) and rel.parts[0] == "libs" and rel.suffix.lower() != ".whl"


def collect_files(root: Path, with_docs: bool, keep_libs: bool):
    """返回 (待打包文件列表, 跳过数量)。"""
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
        sys.exit("[ERROR] ZIP 为空")

    bad = [n for n in names if not n.startswith(project_id + "/")]
    if bad:
        sys.exit("[ERROR] 以下条目不在 %s/ 根目录下：%s" % (project_id, bad[:5]))

    required = {"%s/%s" % (project_id, f) for f in ("metadata.txt", "__init__.py")}
    missing = required - set(names)
    if missing:
        sys.exit("[ERROR] ZIP 缺少必需文件：%s" % ", ".join(sorted(missing)))

    if any("__pycache__" in n or n.endswith((".pyc", ".pyo")) for n in names):
        sys.exit("[ERROR] ZIP 中混入了 Python 缓存文件")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="把当前 QGIS 插件目录打包为官方仓库可上传的 ZIP。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--name", default=PLUGIN_ID, help="ZIP 内根目录名（默认 %(default)s）")
    ap.add_argument("--output", default=None, help="输出 ZIP 路径（默认 dist/<name>-<version>.zip）")
    ap.add_argument("--with-docs", action="store_true", help="把 docs/ 一并打包")
    ap.add_argument("--keep-libs", action="store_true", help="保留 libs/ 下已解压的依赖（默认只留 *.whl）")
    ap.add_argument("--dry-run", "--list", dest="dry_run", action="store_true", help="只列出文件，不生成 ZIP")
    args = ap.parse_args()

    project_id = args.name.strip()
    if not PLUGIN_ID_RE.match(project_id):
        sys.exit("[ERROR] 根目录名不合法：%r（只允许 ASCII 字母/数字/_/-，且不能以数字开头）" % project_id)

    root = Path(__file__).resolve().parent
    print("[Pro Toolbox] 插件目录: %s" % root)

    meta = read_metadata(root)
    version = meta.get("general", "version")
    print("[OK] metadata.txt: name=%s, version=%s, qgisMinimumVersion=%s"
          % (meta.get("general", "name"),
             version,
             meta.get("general", "qgisMinimumVersion", fallback="?")))

    missing_required = [f for f in REQUIRED_FILES if not (root / f).is_file()]
    if missing_required:
        sys.exit("[ERROR] 缺少发布必需文件：%s" % ", ".join(missing_required))

    files, skipped = collect_files(root, args.with_docs, args.keep_libs)
    if not files:
        sys.exit("[ERROR] 没有收集到任何文件")

    print("[OK] 收集 %d 个文件，跳过 %d 项" % (len(files), skipped))

    if args.dry_run:
        print("\n将打包以下文件（根目录 %s/）：" % project_id)
        for rel in files:
            print("  %s/%s" % (project_id, rel.as_posix()))
        print("\n[dry-run] 未生成 ZIP。")
        return

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = root / "dist" / ("%s-%s.zip" % (project_id, version))

    raw_size = build_zip(root, project_id, files, out_path)
    verify_zip(out_path, project_id)

    zip_size = out_path.stat().st_size
    print("[OK] 已生成: %s" % out_path)
    print("     原始大小 %s -> 压缩后 %s（压缩率 %.1f%%）"
          % (human_size(raw_size), human_size(zip_size),
             100.0 * zip_size / raw_size if raw_size else 0.0))
    print("     结构校验通过：所有条目均位于 %s/ 下，且含 metadata.txt / __init__.py" % project_id)
    print("\n下一步：https://plugins.qgis.org/plugins/upload/ 上传该 ZIP（或先本地用 QGIS「从 ZIP 安装」自测）。")


if __name__ == "__main__":
    main()

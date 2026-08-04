#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the distributable sp_chinese_translation.zip from source/.

Layout:
    source/sp_chinese_translation/    canonical plugin source (single source of truth)
    dist/sp_chinese_translation.zip   generated release archive (zip root == plugin content)

Usage:
    python scripts/build_package.py
"""

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "source" / "sp_chinese_translation"
DIST = ROOT / "dist"
OUT = DIST / "sp_chinese_translation.zip"
README = ROOT / "README.md"

# Possible outputs of the native CMake build. When a freshly built DLL exists
# it overrides the one in source/; otherwise the existing source/ DLL is kept.
NATIVE_DLL_CANDIDATES = [
    ROOT / "source" / "c++" / "build" / "Release" / "sp_native_asset_delegate.dll",
    ROOT / "source" / "c++" / "build" / "x64" / "Release" / "sp_native_asset_delegate.dll",
]


def _check_required_files() -> None:
    required = [
        SRC / "__init__.py",
        SRC / "translations" / "official_assets_zh.json",
        SRC / "packages" / "sp_native_asset_delegate.dll",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("缺少必要文件:")
        for path in missing:
            print("  -", path)
        sys.exit(1)


def main() -> None:
    _check_required_files()
    DIST.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sp_pkg_") as tmp:
        pkg = Path(tmp) / "sp_chinese_translation"
        shutil.copytree(SRC, pkg)

        # The release archive always ships the current top-level README.
        shutil.copy2(README, pkg / "README.md")

        # A freshly compiled native DLL (if present) wins over source/.
        fresh_dll = next((path for path in NATIVE_DLL_CANDIDATES if path.is_file()), None)
        if fresh_dll is not None:
            shutil.copy2(fresh_dll, pkg / "packages" / "sp_native_asset_delegate.dll")
            print("使用新编译的 DLL:", fresh_dll)
        else:
            print("未发现新编译的 DLL，沿用 source/sp_chinese_translation/packages 中的现有 DLL。")

        file_count = 0
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(pkg.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(pkg).as_posix())
                    file_count += 1

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"已生成 {OUT}  ({file_count} 个文件, {size_mb:.2f} MB)")


if __name__ == "__main__":
    main()

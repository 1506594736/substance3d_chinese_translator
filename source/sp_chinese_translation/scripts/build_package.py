#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile and package the Substance Painter translation plug-in.

Layout:
    source/sp_chinese_translation/    canonical plugin source (single source of truth)
    source/sp_chinese_translation/c++/  C++ translation delegate source
    source/sp_chinese_translation/scripts/  build/diagnostic/dictionary tools
    source/qt-sdk                     shared Qt5/Qt6 SDK toolchain (not plugin code)
    dist/sp_chinese_translation.zip   generated release archive (zip root == plugin content)

One-click build (run from the repository root):
    python source/sp_chinese_translation/scripts/build_package.py

The command always compiles both ``sp_translation_delegate_qt6.dll`` and
``sp_translation_delegate_qt5.dll`` before creating the ZIP. A compile failure
stops packaging, so an old DLL can never be published accidentally.

Requirements and notes:
    * Windows x64 with CMake and MSVC Build Tools / Visual Studio C++ tools.
* Keep both compact Qt5.12.5 and Qt6 SDKs under ``source/qt-sdk``.
    * Substance Painter must be closed only when installing/replacing the DLL;
      it does not need to be closed merely to build this archive.
    * The ZIP root is the plug-in content. Extract it directly into a folder
      named ``sp_chinese_translation`` under Painter's python/plugins folder.
"""

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# 发布包只包含运行所需文件；以下目录是开发/构建用，不进入 zip
EXCLUDED_TOP_DIRS = {"scripts", "c++", "__pycache__"}

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "source" / "sp_chinese_translation"
DIST = ROOT / "dist"
OUT = DIST / "sp_chinese_translation.zip"
README = ROOT / "README.md"
CXX_SRC = ROOT / "source" / "sp_chinese_translation" / "c++"
CXX_BUILD = CXX_SRC / "build"
DELEGATE_DLL = CXX_BUILD / "Release" / "sp_translation_delegate_qt6.dll"
DELEGATE_QT5_DLL = CXX_BUILD / "Release" / "sp_translation_delegate_qt5.dll"
PACKAGED_DELEGATE_DLL = SRC / "native" / "sp_translation_delegate_qt6.dll"
PACKAGED_DELEGATE_QT5_DLL = SRC / "native" / "sp_translation_delegate_qt5.dll"
LEGACY_NATIVE_DLL = SRC / "native" / "sp_native_asset_delegate.dll"
UNSUFFIXED_DELEGATE_DLL = SRC / "native" / "sp_translation_delegate.dll"

def _check_required_files() -> None:
    required = [
        SRC / "__init__.py",
        SRC / "translations" / "official_assets_zh.json",
        README,
        CXX_SRC / "CMakeLists.txt",
        CXX_SRC / "translation_ui_delegate.cpp",
    ROOT / "source" / "qt-sdk" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Core.lib",
    ROOT / "source" / "qt-sdk" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Gui.lib",
    ROOT / "source" / "qt-sdk" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Widgets.lib",
    ROOT / "source" / "qt-sdk" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Core.lib",
    ROOT / "source" / "qt-sdk" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Gui.lib",
    ROOT / "source" / "qt-sdk" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Widgets.lib",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("缺少必要文件:")
        for path in missing:
            print("  -", path)
        sys.exit(1)


def _validate_sources() -> None:
    """Fail before compilation when the canonical source is malformed."""
    plugin_source = SRC / "__init__.py"
    plugin_text = plugin_source.read_text(encoding="utf-8")
    compile(plugin_text, str(plugin_source), "exec")
    # Painter 7.2 ships Python 3.7. Reject newer syntax at package time even
    # when this script itself is run by the current Python 3.11 toolchain.
    ast.parse(plugin_text, filename=str(plugin_source), feature_version=(3, 7))

    vendor_zip = SRC / "packages" / "python.zip"
    with zipfile.ZipFile(vendor_zip) as archive:
        for name in archive.namelist():
            if not name.endswith(".py"):
                continue
            source = archive.read(name).decode("utf-8-sig")
            ast.parse(source, filename=name, feature_version=(3, 7))

    dictionary_path = SRC / "translations" / "official_assets_zh.json"
    payload = json.loads(dictionary_path.read_text(encoding="utf-8-sig"))
    if payload.get("$schema") != "sp-translation-v1":
        raise ValueError("official_assets_zh.json 的 $schema 无效")
    if payload.get("language") != "zh-CN":
        raise ValueError("official_assets_zh.json 的 language 必须是 zh-CN")
    translations = payload.get("translations")
    if not isinstance(translations, dict):
        raise ValueError("official_assets_zh.json 缺少 translations 对象")
    invalid = [key for key, value in translations.items()
               if not isinstance(key, str) or not key
               or not isinstance(value, str) or not value]
    if invalid:
        raise ValueError(f"official_assets_zh.json 含无效词条: {invalid[:5]}")


def _build_delegate() -> None:
    """Build the C++ translation delegate and update the canonical package."""
    cmake = shutil.which("cmake")
    if cmake is None:
        raise RuntimeError("未找到 CMake，请先安装 CMake 并加入 PATH。")

    print("配置 C++ 原生模块……")
    subprocess.run(
        [cmake, "-S", str(CXX_SRC), "-B", str(CXX_BUILD)],
        check=True,
    )
    print("编译 C++ 原生模块（Release）……")
    subprocess.run(
        [cmake, "--build", str(CXX_BUILD), "--config", "Release"],
        check=True,
    )
    missing_outputs = [path for path in (DELEGATE_DLL, DELEGATE_QT5_DLL)
                       if not path.is_file()]
    if missing_outputs:
        raise RuntimeError(f"编译完成但缺少 DLL：{missing_outputs}")

    PACKAGED_DELEGATE_DLL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DELEGATE_DLL, PACKAGED_DELEGATE_DLL)
    shutil.copy2(DELEGATE_QT5_DLL, PACKAGED_DELEGATE_QT5_DLL)
    LEGACY_NATIVE_DLL.unlink(missing_ok=True)
    UNSUFFIXED_DELEGATE_DLL.unlink(missing_ok=True)
    print("已更新 C++ 翻译模块:", PACKAGED_DELEGATE_DLL)
    print("已更新 Qt5 C++ 翻译模块:", PACKAGED_DELEGATE_QT5_DLL)


def main() -> None:
    # A failed build must not leave an older archive that looks current.
    OUT.unlink(missing_ok=True)
    _check_required_files()
    _validate_sources()
    _build_delegate()
    DIST.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sp_pkg_") as tmp:
        pkg = Path(tmp) / "sp_chinese_translation"
        shutil.copytree(
            SRC,
            pkg,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

        # The release archive always ships the current top-level README.
        shutil.copy2(README, pkg / "README.md")

        file_count = 0
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(pkg.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(pkg)
                    if (relative.parts
                            and relative.parts[0] in EXCLUDED_TOP_DIRS):
                        continue
                    archive.write(path, relative.as_posix())
                    file_count += 1

    with zipfile.ZipFile(OUT, "r") as archive:
        names = archive.namelist()
        required = {"__init__.py",
                    "native/sp_translation_delegate_qt5.dll",
                    "native/sp_translation_delegate_qt6.dll",
                    "translations/official_assets_zh.json", "README.md"}
        missing = required.difference(names)
        if missing:
            OUT.unlink(missing_ok=True)
            raise RuntimeError(f"发布包缺少必要文件: {sorted(missing)}")
        if any(name.startswith("sp_chinese_translation/") for name in names):
            OUT.unlink(missing_ok=True)
            raise RuntimeError("发布包错误地包含同名外层目录")
        if any("__pycache__" in name or name.endswith(".pyc") for name in names):
            OUT.unlink(missing_ok=True)
            raise RuntimeError("发布包包含 Python 缓存文件")

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"已生成 {OUT}  ({file_count} 个文件, {size_mb:.2f} MB)")


if __name__ == "__main__":
    main()

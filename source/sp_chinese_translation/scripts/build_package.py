#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile and package the Substance Painter translation plug-in.

Layout:
    source/sp_chinese_translation/    canonical plugin source (single source of truth)
    source/sp_chinese_translation/c++/  C++ translation delegate source
    source/sp_chinese_translation/scripts/  build/diagnostic/dictionary tools
    source/public/sdks                bundled Qt SDKs and extractor dependencies
    source/public/translations        shared SP/SD translation dictionaries
    dist/sp_chinese_translation.zip   generated release archive (zip root == plugin content)

One-click build (run from the repository root):
    python source/sp_chinese_translation/scripts/build_package.py

The command always compiles both ``sp_translation_delegate_qt6.dll`` and
``sp_translation_delegate_qt5.dll`` before creating the ZIP. A compile failure
stops packaging, so an old DLL can never be published accidentally.

Requirements and notes:
    * Windows x64 with CMake and MSVC Build Tools / Visual Studio C++ tools.
    * Keep both compact Qt5.12.5 and Qt6 SDKs under ``source/public/sdks/qt``.
    * Extractor dependencies are bundled under ``source/public/sdks/deps``; no vcpkg or
      network access is required to build.
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
import os
import tempfile
import zipfile
from pathlib import Path

# 发布包只包含运行所需文件；以下目录是开发/构建用，不进入 zip
EXCLUDED_TOP_DIRS = {"scripts", "cpp", "packages", "__pycache__"}

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "source" / "sp_chinese_translation"
PUBLIC = ROOT / "source" / "public"
TRANSLATIONS = PUBLIC / "translations"
DIST = ROOT / "dist"
OUT = DIST / "sp_chinese_translation.zip"
README = ROOT / "README.md"
CPP_SRC = ROOT / "source" / "sp_chinese_translation" / "cpp"
CPP_BUILD = CPP_SRC / "build"
DELEGATE_DLL = CPP_BUILD / "Release" / "sp_translation_delegate_qt6.dll"
DELEGATE_QT5_DLL = CPP_BUILD / "Release" / "sp_translation_delegate_qt5.dll"
PACKAGED_DELEGATE_DLL = SRC / "native" / "sp_translation_delegate_qt6.dll"
PACKAGED_DELEGATE_QT5_DLL = SRC / "native" / "sp_translation_delegate_qt5.dll"
LEGACY_NATIVE_DLL = SRC / "native" / "sp_native_asset_delegate.dll"
UNSUFFIXED_DELEGATE_DLL = SRC / "native" / "sp_translation_delegate.dll"
EXTRACTOR_EXE = CPP_BUILD / "Release" / "sp_translation_extractor.exe"
PACKAGED_EXTRACTOR_EXE = SRC / "native" / "sp_translation_extractor.exe"
DEPS_ROOT = PUBLIC / "sdks" / "deps"

def _check_required_files() -> None:
    required = [
        SRC / "__init__.py",
        TRANSLATIONS / "official_assets_zh.json",
        README,
        CPP_SRC / "CMakeLists.txt",
        CPP_SRC / "translation_ui_delegate.cpp",
        CPP_SRC / "extractor.cpp",
        CPP_SRC / "vcpkg.json",
        DEPS_ROOT / "include" / "archive.h",
        DEPS_ROOT / "lib" / "archive.lib",
        DEPS_ROOT / "lib" / "libhdf5.lib",
    PUBLIC / "sdks" / "qt" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Core.lib",
    PUBLIC / "sdks" / "qt" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Gui.lib",
    PUBLIC / "sdks" / "qt" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Widgets.lib",
    PUBLIC / "sdks" / "qt" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Core.lib",
    PUBLIC / "sdks" / "qt" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Gui.lib",
    PUBLIC / "sdks" / "qt" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Widgets.lib",
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

    dictionaries = sorted(TRANSLATIONS.glob("*_zh.json"))
    if not dictionaries:
        raise ValueError("translations 目录中没有 *_zh.json 翻译包")
    for dictionary_path in dictionaries:
        payload = json.loads(dictionary_path.read_text(encoding="utf-8-sig"))
        if payload.get("$schema") != "sp-translation-v1":
            raise ValueError(f"{dictionary_path.name} 的 $schema 无效")
        if payload.get("language") != "zh-CN":
            raise ValueError(
                f"{dictionary_path.name} 的 language 必须是 zh-CN"
            )
        translations = payload.get("translations", {})
        control_types = payload.get("control_types", {})
        if not isinstance(translations, dict):
            raise ValueError(
                f"{dictionary_path.name} 的 translations 必须是对象"
            )
        if not isinstance(control_types, dict):
            raise ValueError(
                f"{dictionary_path.name} 的 control_types 必须是对象"
            )
        sections = [("translations", translations)]
        for control_type, section in control_types.items():
            if not isinstance(control_type, str) or not control_type.strip():
                raise ValueError(
                    f"{dictionary_path.name} 含无效 control_type"
                )
            if not isinstance(section, dict) or not isinstance(
                    section.get("translations"), dict):
                raise ValueError(
                    f"{dictionary_path.name} 的 {control_type!r} 缺少 "
                    "translations 对象"
                )
            sections.append(
                (f"control_types.{control_type}", section["translations"])
            )
        if not translations and not control_types:
            raise ValueError(f"{dictionary_path.name} 不含任何翻译词条")
        for section_name, entries in sections:
            invalid = [
                key for key, value in entries.items()
                if not isinstance(key, str) or not key
                or not isinstance(value, str) or not value
            ]
            if invalid:
                raise ValueError(
                    f"{dictionary_path.name} 的 {section_name} 含无效词条: "
                    f"{invalid[:5]}"
                )


def _build_native() -> None:
    """Build the Qt delegate DLLs and the standalone extractor."""
    cmake = shutil.which("cmake")
    if cmake is None:
        raise RuntimeError("未找到 CMake，请先安装 CMake 并加入 PATH。")
    print("配置 C++ 原生模块……")
    subprocess.run(
        [cmake, "-S", str(CPP_SRC), "-B", str(CPP_BUILD)],
        check=True,
    )
    print("编译 C++ 原生模块（Release）……")
    subprocess.run(
        [cmake, "--build", str(CPP_BUILD), "--config", "Release"],
        check=True,
    )
    missing_outputs = [path for path in (DELEGATE_DLL, DELEGATE_QT5_DLL,
                                         EXTRACTOR_EXE)
                       if not path.is_file()]
    if missing_outputs:
        raise RuntimeError(f"编译完成但缺少产物：{missing_outputs}")

    PACKAGED_DELEGATE_DLL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DELEGATE_DLL, PACKAGED_DELEGATE_DLL)
    shutil.copy2(DELEGATE_QT5_DLL, PACKAGED_DELEGATE_QT5_DLL)
    LEGACY_NATIVE_DLL.unlink(missing_ok=True)
    UNSUFFIXED_DELEGATE_DLL.unlink(missing_ok=True)
    PACKAGED_EXTRACTOR_EXE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXTRACTOR_EXE, PACKAGED_EXTRACTOR_EXE)
    print("已更新 C++ 翻译模块:", PACKAGED_DELEGATE_DLL)
    print("已更新 Qt5 C++ 翻译模块:", PACKAGED_DELEGATE_QT5_DLL)
    print("已更新独立 C++ 词条提取器:", PACKAGED_EXTRACTOR_EXE)


def main() -> None:
    # A failed build must not leave an older archive that looks current.
    OUT.unlink(missing_ok=True)
    _check_required_files()
    _validate_sources()
    _build_native()
    DIST.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sp_pkg_") as tmp:
        pkg = Path(tmp) / "sp_chinese_translation"
        shutil.copytree(
            SRC,
            pkg,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(TRANSLATIONS, pkg / "translations")

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
                    "native/sp_translation_extractor.exe",
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

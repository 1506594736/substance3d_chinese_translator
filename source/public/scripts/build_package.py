#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile and package the unified SP/SD Chinese translation plug-in.

Layout (single source of truth for both hosts):
    source/substance3d_chinese_translator/ canonical plug-in source
      __init__.py                           Painter entry shim
      pluginInfo.json                       Designer metadata
      substance3d_chinese_translator/       Designer module (merged Python)
      cpp/                                  C++ translation engine
      native/                               built binaries
      translations/                         shared SP/SD dictionaries
    source/public/sdks                      bundled Qt SDKs and extractor deps
    source/public/scripts/                  build/diagnostic/dictionary tools
    dist/substance3d_chinese_translator.zip unified release archive

One-click build (run from the repository root):
    python source/public/scripts/build_package.py

The command always compiles ``translator_delegate_qt6.dll`` (shared by
Painter 10.1+ and Designer 15+), ``translator_delegate_qt5.dll`` (Painter
7.2-10.0) and ``translator_extractor.exe`` before creating the ZIP. A compile
failure stops packaging, so an old binary can never be published accidentally.

The ZIP root is the plug-in content. Install it by extracting into a folder
named ``substance3d_chinese_translator`` under either:
  * Painter:   Documents/Adobe/Adobe Substance 3D Painter/python/plugins
  * Designer:  Documents/Adobe/Adobe Substance 3D Designer/python/sduserplugins
"""

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "source" / "substance3d_chinese_translator"
MODULE_DIR = SRC / "substance3d_chinese_translator"
PUBLIC = ROOT / "source" / "public"
TRANSLATIONS = SRC / "translations"
DIST = ROOT / "dist"
OUT = DIST / "substance3d_chinese_translator.zip"
README = ROOT / "README.md"
CPP_SRC = SRC / "cpp"
CPP_BUILD = CPP_SRC / "build"
DELEGATE_QT6_DLL = CPP_BUILD / "Release" / "translator_delegate_qt6.dll"
DELEGATE_QT5_DLL = CPP_BUILD / "Release" / "translator_delegate_qt5.dll"
EXTRACTOR_EXE = CPP_BUILD / "Release" / "translator_extractor.exe"
NATIVE_DIR = SRC / "native"
DEPS_ROOT = PUBLIC / "sdks" / "deps"


def _check_required_files() -> None:
    required = [
        SRC / "__init__.py",
        SRC / "pluginInfo.json",
        MODULE_DIR / "__init__.py",
        TRANSLATIONS / "official_assets_zh.json",
        README,
        CPP_SRC / "CMakeLists.txt",
        CPP_SRC / "translation_ui_delegate.cpp",
        CPP_SRC / "extractor.cpp",
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
    merged_source = MODULE_DIR / "__init__.py"
    merged_text = merged_source.read_text(encoding="utf-8")
    compile(merged_text, str(merged_source), "exec")
    # Painter 7.2 ships Python 3.7; Designer 15+ ships newer Python. Reject
    # newer syntax at package time even when this script itself runs on a
    # newer toolchain.
    try:
        ast.parse(
            merged_text,
            filename=str(merged_source),
            feature_version=(3, 7),
        )
    except TypeError:
        # Python 3.7 本身没有 feature_version 参数；在旧解释器上退化为
        # 普通语法检查，避免构建脚本自身无法运行。
        ast.parse(merged_text, filename=str(merged_source))
    ast.parse(
        (SRC / "__init__.py").read_text(encoding="utf-8"),
        filename=str(SRC / "__init__.py"),
    )
    metadata = json.loads(
        (SRC / "pluginInfo.json").read_text(encoding="utf-8")
    )
    if metadata.get("name") != "substance3d_chinese_translator":
        raise ValueError(
            "pluginInfo.json 的 name 必须是 substance3d_chinese_translator"
        )

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
                or not isinstance(value, str)
            ]
            if invalid:
                raise ValueError(
                    f"{dictionary_path.name} 的 {section_name} 含无效词条: "
                    f"{invalid[:5]}"
                )


def _build_native() -> None:
    """Build the Qt5/Qt6 delegate DLLs and the standalone extractor."""
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
    missing_outputs = [path for path in (DELEGATE_QT6_DLL, DELEGATE_QT5_DLL,
                                         EXTRACTOR_EXE)
                       if not path.is_file()]
    if missing_outputs:
        raise RuntimeError(f"编译完成但缺少产物：{missing_outputs}")

    # Replace the packaged native set. Stale binaries from earlier separate
    # SP/SD packages (sd_translation_delegate_qt6.dll, sp_translation_* and
    # sd_translation_* extractor names) are removed so the unified package
    # never ships a file the code does not load.
    if NATIVE_DIR.is_dir():
        for stale in list(NATIVE_DIR.iterdir()):
            if stale.suffix.lower() in (".dll", ".exe", ".old"):
                stale.unlink(missing_ok=True)
    NATIVE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DELEGATE_QT6_DLL, NATIVE_DIR / "translator_delegate_qt6.dll")
    shutil.copy2(DELEGATE_QT5_DLL, NATIVE_DIR / "translator_delegate_qt5.dll")
    shutil.copy2(EXTRACTOR_EXE, NATIVE_DIR / "translator_extractor.exe")
    print("已更新 Qt6 翻译模块（Painter 10.1+ / Designer 15+ 共用）:",
          NATIVE_DIR / "translator_delegate_qt6.dll")
    print("已更新 Qt5 翻译模块（Painter 7.2-10.0）:",
          NATIVE_DIR / "translator_delegate_qt5.dll")
    print("已更新独立 C++ 词条提取器:", NATIVE_DIR / "translator_extractor.exe")


def _create_archive() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="sp_pkg_") as tmp:
        pkg = Path(tmp) / "substance3d_chinese_translator"
        pkg.mkdir()
        shutil.copy2(SRC / "__init__.py", pkg / "__init__.py")
        shutil.copy2(SRC / "pluginInfo.json", pkg / "pluginInfo.json")
        shutil.copy2(README, pkg / "README.md")
        shutil.copytree(TRANSLATIONS, pkg / "translations")
        shutil.copytree(NATIVE_DIR, pkg / "native")
        module_pkg = pkg / "substance3d_chinese_translator"
        module_pkg.mkdir()
        shutil.copy2(MODULE_DIR / "__init__.py", module_pkg / "__init__.py")

        file_count = 0
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(pkg.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(pkg).as_posix())
                    file_count += 1

    with zipfile.ZipFile(OUT, "r") as archive:
        names = archive.namelist()
        required = {
            "__init__.py",
            "pluginInfo.json",
            "README.md",
            "substance3d_chinese_translator/__init__.py",
            "native/translator_delegate_qt5.dll",
            "native/translator_delegate_qt6.dll",
            "native/translator_extractor.exe",
            "translations/official_assets_zh.json",
        }
        missing = required.difference(names)
        if missing:
            OUT.unlink(missing_ok=True)
            raise RuntimeError(f"发布包缺少必要文件: {sorted(missing)}")
        if any(name.startswith("substance3d_chinese_translator/")
               and name != "substance3d_chinese_translator/__init__.py"
               for name in names):
            OUT.unlink(missing_ok=True)
            raise RuntimeError("发布包错误地包含同名外层目录")
        if any("__pycache__" in name or name.endswith(".pyc")
               for name in names):
            OUT.unlink(missing_ok=True)
            raise RuntimeError("发布包包含 Python 缓存文件")
        if any(name.endswith((".dll.old", ".exe.old")) for name in names):
            OUT.unlink(missing_ok=True)
            raise RuntimeError("发布包包含更新残留文件")

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"已生成 {OUT}  ({file_count} 个文件, {size_mb:.2f} MB)")


def main() -> None:
    # A failed build must not leave an older archive that looks current.
    OUT.unlink(missing_ok=True)
    # The obsolete standalone Designer package is replaced by the unified one.
    for obsolete in (
        DIST / "sd_chinese_translation.zip",
        DIST / "sp_chinese_translation.zip",
    ):
        if obsolete.is_file():
            obsolete.unlink()
            print("已移除旧的发布包:", obsolete)
    _check_required_files()
    _validate_sources()
    _build_native()
    _create_archive()


if __name__ == "__main__":
    main()

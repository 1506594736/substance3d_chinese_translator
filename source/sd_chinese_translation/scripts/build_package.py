#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile and package the Substance 3D Designer translation plug-in.

The source layout mirrors ``source/sp_chinese_translation``. Designer's
required ``pluginInfo.json + package/module`` nesting is generated only in the
release archive and installation directory.

One-click build from the repository root::

    python source/sd_chinese_translation/scripts/build_package.py

Designer must be closed only when replacing the installed DLL. Building and
creating the archive do not require Designer to be closed.
"""

import ast
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "source" / "sd_chinese_translation"
PUBLIC = ROOT / "source" / "public"
TRANSLATIONS = PUBLIC / "translations"
CPP_DIR = SRC / "cpp"
BUILD_DIR = CPP_DIR / "build"
BUILT_DLL = BUILD_DIR / "Release" / "sd_translation_delegate_qt6.dll"
RUNTIME_DLL = SRC / "native" / "sd_translation_delegate_qt6.dll"
BUILT_EXTRACTOR = BUILD_DIR / "Release" / "sd_translation_extractor.exe"
RUNTIME_EXTRACTOR = SRC / "native" / "sd_translation_extractor.exe"
DIST = ROOT / "dist"
OUTPUT = DIST / "sd_chinese_translation.zip"
MODULE_NAME = "sd_chinese_translation"


def validate_sources():
    source = (SRC / "__init__.py").read_text(encoding="utf-8")
    ast.parse(source, filename=str(SRC / "__init__.py"))
    json.loads((SRC / "pluginInfo.json").read_text(encoding="utf-8"))

    dictionaries = sorted(TRANSLATIONS.glob("*_zh.json"))
    if not dictionaries:
        raise RuntimeError("translations 目录中没有 *_zh.json 词库")
    for path in dictionaries:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("$schema") != "sp-translation-v1":
            raise RuntimeError(f"{path.name}: 不支持的翻译格式")
        if payload.get("language") != "zh-CN":
            raise RuntimeError(f"{path.name}: language 必须是 zh-CN")


def build_native():
    cmake = shutil.which("cmake")
    if cmake is None:
        raise RuntimeError("未找到 CMake")
    subprocess.run([cmake, "-S", str(CPP_DIR), "-B", str(BUILD_DIR)], check=True)
    subprocess.run(
        [cmake, "--build", str(BUILD_DIR), "--config", "Release"],
        check=True,
    )
    missing = [path for path in (BUILT_DLL, BUILT_EXTRACTOR)
               if not path.is_file()]
    if missing:
        raise RuntimeError(f"编译完成但缺少产物: {missing}")
    RUNTIME_DLL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BUILT_DLL, RUNTIME_DLL)
    shutil.copy2(BUILT_EXTRACTOR, RUNTIME_EXTRACTOR)


def create_archive():
    DIST.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="sd_translation_") as temporary:
        package_root = Path(temporary) / MODULE_NAME
        module_root = package_root / MODULE_NAME
        module_root.mkdir(parents=True)

        shutil.copy2(SRC / "pluginInfo.json", package_root / "pluginInfo.json")
        shutil.copy2(SRC / "__init__.py", module_root / "__init__.py")
        shutil.copytree(SRC / "native", module_root / "native")
        shutil.copytree(TRANSLATIONS, module_root / "translations")
        if (SRC / "README.md").is_file():
            shutil.copy2(SRC / "README.md", package_root / "README.md")
        if (SRC / "THIRD_PARTY_LICENSES.txt").is_file():
            shutil.copy2(
                SRC / "THIRD_PARTY_LICENSES.txt",
                package_root / "THIRD_PARTY_LICENSES.txt",
            )

        with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(package_root).as_posix())

    with zipfile.ZipFile(OUTPUT) as archive:
        names = set(archive.namelist())
        required = {
            "pluginInfo.json",
            f"{MODULE_NAME}/__init__.py",
            f"{MODULE_NAME}/native/sd_translation_delegate_qt6.dll",
            f"{MODULE_NAME}/native/sd_translation_extractor.exe",
        }
        missing = required - names
        if missing:
            OUTPUT.unlink(missing_ok=True)
            raise RuntimeError(f"发布包缺少文件：{sorted(missing)}")


def main():
    validate_sources()
    build_native()
    create_archive()
    print(f"已生成 {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()

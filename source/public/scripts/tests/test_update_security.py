#!/usr/bin/env python3
"""Host-independent tests for updater archive and dictionary safeguards."""

import ast
import hashlib
import io
import json
import re
import tempfile
import unittest
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = (
    ROOT / "substance3d_chinese_translator" /
    "substance3d_chinese_translator" / "__init__.py"
)


def load_helpers():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    wanted_functions = {
        "_write_json_atomic",
        "_normalized_zip_name",
        "_validate_update_archive",
        "_merge_preserved_translation",
        "_download_update",
    }
    wanted_constants = {
        "MAX_UPDATE_FILES",
        "MAX_UPDATE_FILE_BYTES",
        "MAX_UPDATE_EXPANDED_BYTES",
        "MAX_UPDATE_COMPRESSION_RATIO",
        "REQUIRED_UPDATE_FILES",
        "MAX_UPDATE_DOWNLOAD_BYTES",
        "PLUGIN_REPO",
    }
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in wanted_functions:
                selected.append(node)
        elif isinstance(node, ast.Assign):
            names = {target.id for target in node.targets
                     if isinstance(target, ast.Name)}
            if names & wanted_constants:
                selected.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "_DownloadCancelled":
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        "json": json,
        "hashlib": hashlib,
        "re": re,
        "os": __import__("os"),
        "tempfile": tempfile,
        "zipfile": zipfile,
        "urllib": __import__("urllib"),
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


HELPERS = load_helpers()


class UpdateSecurityTests(unittest.TestCase):
    def make_package(self, path, version="9.8.7"):
        required = HELPERS["REQUIRED_UPDATE_FILES"]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in required:
                if name == "pluginInfo.json":
                    data = json.dumps({
                        "name": "substance3d_chinese_translator",
                        "version": version,
                    })
                else:
                    data = "placeholder"
                archive.writestr(name, data)

    def test_complete_package_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "update.zip"
            self.make_package(package)
            HELPERS["_validate_update_archive"](package, "9.8.7")

    def test_missing_runtime_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("__init__.py", "")
                archive.writestr("pluginInfo.json", json.dumps({
                    "name": "substance3d_chinese_translator",
                    "version": "9.8.7",
                }))
            with self.assertRaises(RuntimeError):
                HELPERS["_validate_update_archive"](package, "9.8.7")

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "update.zip"
            self.make_package(package)
            with zipfile.ZipFile(package, "a") as archive:
                archive.writestr("../outside.py", "bad")
            with self.assertRaises(RuntimeError):
                HELPERS["_validate_update_archive"](package, "9.8.7")

    def test_download_digest_mismatch_is_rejected(self):
        class Response(io.BytesIO):
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        original = urllib.request.urlopen
        urllib.request.urlopen = lambda *_args, **_kwargs: Response(b"not a zip")
        try:
            with tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "update.zip"
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    HELPERS["_download_update"](
                        "https://github.com/iillya/"
                        "substance3d_chinese_translator/releases/download/"
                        "v9.8.7/update.zip",
                        destination,
                        "0" * 64,
                        "9.8.7",
                    )
        finally:
            urllib.request.urlopen = original

    def test_preserved_entries_override_shipped_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path = Path(folder) / "old.json"
            new_path = Path(folder) / "new.json"
            common = {"$schema": "sp-translation-v1", "language": "zh-CN"}
            old_path.write_text(json.dumps({
                **common, "translations": {"Edited": "用户译文"},
            }), encoding="utf-8")
            new_path.write_text(json.dumps({
                **common,
                "translations": {"Edited": "新版译文", "New": "新词"},
            }), encoding="utf-8")
            HELPERS["_merge_preserved_translation"](old_path, new_path)
            merged = json.loads(new_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["translations"]["Edited"], "用户译文")
            self.assertEqual(merged["translations"]["New"], "新词")


if __name__ == "__main__":
    unittest.main()

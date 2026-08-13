import ast
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "source"
MODULE_SOURCE = SOURCE / "substance3d_chinese_translator" / "__init__.py"
CPP_SOURCE = SOURCE / "cpp" / "translation_ui_delegate.cpp"
EXTRACTOR_SOURCE = SOURCE / "cpp" / "extractor.cpp"
ARCHIVE = ROOT / "dist" / "substance3d_chinese_translator.zip"


def _load_build_module():
    path = SOURCE / "cpp" / "build_package.py"
    spec = importlib.util.spec_from_file_location("sp_build_package", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_update_validation_namespace():
    tree = ast.parse(MODULE_SOURCE.read_text(encoding="utf-8"))
    wanted_assignments = {
        "PLUGIN_VERSION", "MAX_UPDATE_FILES", "MAX_UPDATE_FILE_BYTES",
        "MAX_UPDATE_EXPANDED_BYTES", "MAX_UPDATE_COMPRESSION_RATIO",
        "RELEASE_FILE_ALLOWLIST", "REQUIRED_UPDATE_FILES",
    }
    wanted_functions = {"_normalized_zip_name", "_validate_update_archive"}
    selected = []
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name)
                        and target.id in wanted_assignments
                        for target in node.targets)):
            selected.append(node)
        elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name in wanted_functions):
            selected.append(node)
    namespace = {"json": json, "zipfile": zipfile}
    exec(compile(ast.Module(body=selected, type_ignores=[]),
                 str(MODULE_SOURCE), "exec"), namespace)
    return namespace


class SecurityRegressionTests(unittest.TestCase):
    def test_release_archive_matches_exact_allowlist(self):
        build = _load_build_module()
        with zipfile.ZipFile(ARCHIVE) as archive:
            names = {name for name in archive.namelist()
                     if not name.endswith("/")}
            self.assertIsNone(archive.testzip())
        self.assertEqual(names, build.RELEASE_FILE_ALLOWLIST)

    def test_runtime_update_validator_accepts_release_and_rejects_extra(self):
        namespace = _load_update_validation_namespace()
        validate = namespace["_validate_update_archive"]
        validate(ARCHIVE, namespace["PLUGIN_VERSION"])
        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / "tampered.zip"
            with zipfile.ZipFile(ARCHIVE) as source, zipfile.ZipFile(
                    tampered, "w", zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    target.writestr(info.filename, source.read(info.filename))
                target.writestr("foreign_plugin.py", "pass\n")
            with self.assertRaisesRegex(RuntimeError, "非白名单"):
                validate(tampered, namespace["PLUGIN_VERSION"])

    def test_release_version_is_consistent(self):
        metadata = json.loads(
            (SOURCE / "pluginInfo.json").read_text(encoding="utf-8")
        )
        tree = ast.parse(MODULE_SOURCE.read_text(encoding="utf-8"))
        version = None
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name)
                            and target.id == "PLUGIN_VERSION"
                            for target in node.targets)):
                version = ast.literal_eval(node.value)
                break
        self.assertEqual(metadata["version"], version)

    def test_no_zbrush_connector_code_in_plugin_sources(self):
        forbidden = [
            "z" + "brush_to_painter",
            "substance" + "connector",
            "pix" + "ologic",
        ]
        paths = [
            SOURCE / "__init__.py",
            MODULE_SOURCE,
            SOURCE / "cpp" / "build_package.py",
            CPP_SOURCE,
            EXTRACTOR_SOURCE,
        ]
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore").casefold()
            for path in paths
        )
        for marker in forbidden:
            self.assertNotIn(marker, combined)

    def test_experimental_asset_model_proxy_is_removed(self):
        combined = (
            MODULE_SOURCE.read_text(encoding="utf-8") +
            CPP_SOURCE.read_text(encoding="utf-8")
        )
        for marker in (
            "ChineseAssetSearch", "ForwardResourceModel",
            "sp_delegate_set_asset_catalog", "_start_asset_catalog_sync",
        ):
            self.assertNotIn(marker, combined)

    def test_native_global_hook_has_teardown(self):
        cpp = CPP_SOURCE.read_text(encoding="utf-8")
        python = MODULE_SOURCE.read_text(encoding="utf-8")
        self.assertIn("sp_delegate_uninstall_ui", cpp)
        self.assertIn("application->removeEventFilter(g_filter)", cpp)
        self.assertIn("restoreAssetDelegates()", cpp)
        self.assertNotIn("GET_MODULE_HANDLE_EX_FLAG_PIN", cpp)
        self.assertNotIn("QTimer::singleShot(0, qApp", cpp)
        self.assertIn("_uninstall_native_ui()", python)
        self.assertIn("_release_native_delegate()", python)
        self.assertIn("FreeLibrary", python)

    def test_extractor_rejects_links_and_special_files(self):
        source = EXTRACTOR_SOURCE.read_text(encoding="utf-8")
        self.assertIn("archive_entry_hardlink(entry)", source)
        self.assertIn("archive_entry_symlink(entry)", source)
        self.assertIn("type != AE_IFREG && type != AE_IFDIR", source)
        self.assertIn("kMaxSourceFiles", source)


if __name__ == "__main__":
    unittest.main()

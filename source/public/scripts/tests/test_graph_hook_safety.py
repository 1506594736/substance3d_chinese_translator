#!/usr/bin/env python3
"""Regression checks for the opt-in Designer graph hook safeguards."""

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PY_SOURCE = ROOT / "substance3d_chinese_translator" / \
    "substance3d_chinese_translator" / "__init__.py"
CPP_SOURCE = ROOT / "substance3d_chinese_translator" / "cpp" / \
    "translation_ui_delegate.cpp"


class GraphHookSafetyTests(unittest.TestCase):
    def test_python_default_is_disabled(self):
        tree = ast.parse(PY_SOURCE.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        try:
                            values[target.id] = ast.literal_eval(node.value)
                        except (TypeError, ValueError):
                            pass
        self.assertIs(values.get("TRANSLATE_DESIGNER_GRAPH"), False)

    def test_install_ui_does_not_install_graph_hook(self):
        source = CPP_SOURCE.read_text(encoding="utf-8")
        match = re.search(
            r"sp_delegate_install_ui\(.*?\n\}", source, re.DOTALL
        )
        self.assertIsNotNone(match)
        self.assertNotIn("installGraphPainterHooks()", match.group())

    def test_native_guards_and_rollback_are_present(self):
        source = CPP_SOURCE.read_text(encoding="utf-8")
        self.assertIn("sp_delegate_set_translate_designer_graph", source)
        self.assertIn("graphHookEnvironmentCompatible", source)
        self.assertIn("designerMajor == 15 || designerMajor == 16", source)
        self.assertIn("qtMinor < 5 || qtMinor > 9", source)
        self.assertIn("uninstallGraphPainterHooks", source)

    def test_edit_popup_has_press_and_graph_fallbacks(self):
        source = CPP_SOURCE.read_text(encoding="utf-8")
        self.assertIn("contextSourceAtHierarchy", source)
        self.assertIn("graphView->itemAt(position)", source)
        self.assertIn("EDIT mouse-right no-source", source)
        self.assertIn("effectiveMouseModifiers", source)
        self.assertIn("GetAsyncKeyState(VK_CONTROL)", source)

    def test_ctrl_mouse_trigger_does_not_round_trip_qkeysequence(self):
        source = CPP_SOURCE.read_text(encoding="utf-8")
        self.assertIn('QString g_editKey = QStringLiteral("Ctrl")', source)
        self.assertIn("pressed != g_editKey", source)
        self.assertNotIn(
            'QKeySequence g_editKey = QKeySequence(QStringLiteral("Ctrl"))',
            source,
        )


if __name__ == "__main__":
    unittest.main()

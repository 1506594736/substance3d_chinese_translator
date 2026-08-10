# -*- coding: utf-8 -*-
"""离屏回归测试：CaptureButton / EditTrigger / 面板快捷键区域。

运行：python source/public/scripts/tests/test_shortcuts.py
"""
import importlib.util
import os

MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "..",
    "substance3d_chinese_translator",
    "substance3d_chinese_translator",
    "__init__.py",
)

spec = importlib.util.spec_from_file_location("plugin_ut", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
app.setOrganizationName("CodexTestOrg")
app.setApplicationName("CodexTestApp")
app.setQuitOnLastWindowClosed(False)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, cond, detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


ctrl = mod._enum_int(mod.QtCore.Qt.KeyboardModifier.ControlModifier)
alt = mod._enum_int(mod.QtCore.Qt.KeyboardModifier.AltModifier)
check(
    "enable shortcut default is F10",
    mod.ENABLE_SHORTCUT_DEFAULT == "F10",
    mod.ENABLE_SHORTCUT_DEFAULT,
)

# ---------- CaptureButton：纯键盘模式 ----------
btn = mod.CaptureButton(capture_mouse=False)
keys, restores, cancels = [], [], []
btn.key_captured.connect(lambda v: keys.append(v))
btn.restore_default.connect(lambda: restores.append(1))
btn.cancelled.connect(lambda: cancels.append(1))
btn.set_value("F9")
btn.show()
app.processEvents()
check("key button default text", btn.text() == "F9", btn.text())
QTest.mouseClick(btn, QtCore.Qt.MouseButton.LeftButton)
app.processEvents()
check("key button enters capture", btn._capturing, btn.text())
QTest.keyClick(btn, QtCore.Qt.Key.Key_Escape)
app.processEvents()
check("key button esc cancels", not btn._capturing and cancels == [1], btn.text())
QTest.mouseClick(btn, QtCore.Qt.MouseButton.LeftButton)
QTest.keyClick(btn, QtCore.Qt.Key.Key_Backspace)
app.processEvents()
check("key button backspace restores default", not btn._capturing and restores == [1], btn.text())
QTest.mouseClick(btn, QtCore.Qt.MouseButton.LeftButton)
QTest.keyClick(btn, QtCore.Qt.Key.Key_F10)
app.processEvents()
check("key button captures F10", keys == ["F10"], str(keys))

# ---------- CaptureButton：键盘 + 鼠标模式 ----------
btn2 = mod.CaptureButton(capture_mouse=True)
mouse, keys2 = [], []
btn2.mouse_captured.connect(lambda m, b: mouse.append((m, b)))
btn2.key_captured.connect(lambda v: keys2.append(v))
btn2.set_value(mod.EditTrigger().display_text())
host = QtWidgets.QWidget()
host.show()
btn2.show()
app.processEvents()
check("mouse button default text", btn2.text() == "Ctrl+右键", btn2.text())

QTest.mouseClick(btn2, QtCore.Qt.MouseButton.LeftButton)
QTest.mouseClick(host, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.ControlModifier)
app.processEvents()
check("capture Ctrl+左键", mouse[-1:] == [("Ctrl", mod.MOUSE_LEFT)], str(mouse[-1:]))

QTest.mouseClick(btn2, QtCore.Qt.MouseButton.LeftButton)
before_mouse = len(mouse)
QTest.keyPress(btn2, QtCore.Qt.Key.Key_F10)
QTest.mouseClick(host, QtCore.Qt.MouseButton.LeftButton)
QTest.keyRelease(btn2, QtCore.Qt.Key.Key_F10)
app.processEvents()
check(
    "reject F10+左键 without modifier and restore button",
    not btn2._capturing and len(mouse) == before_mouse
    and btn2.text() == "Ctrl+右键",
    "capturing=" + str(btn2._capturing) + " text=" + btn2.text(),
)

QTest.mouseClick(btn2, QtCore.Qt.MouseButton.LeftButton)
QTest.keyPress(
    btn2,
    QtCore.Qt.Key.Key_F10,
    QtCore.Qt.KeyboardModifier.ControlModifier,
)
QTest.mouseClick(host, QtCore.Qt.MouseButton.MiddleButton, QtCore.Qt.KeyboardModifier.ControlModifier)
QTest.keyRelease(
    btn2,
    QtCore.Qt.Key.Key_F10,
    QtCore.Qt.KeyboardModifier.ControlModifier,
)
app.processEvents()
check("capture Ctrl+F10+中键", mouse[-1:] == [("Ctrl+F10", mod.MOUSE_MIDDLE)], str(mouse[-1:]))

QTest.mouseClick(btn2, QtCore.Qt.MouseButton.LeftButton)
QTest.mouseClick(host, QtCore.Qt.MouseButton.RightButton, QtCore.Qt.KeyboardModifier.AltModifier)
app.processEvents()
check("capture Alt+右键", mouse[-1:] == [("Alt", mod.MOUSE_RIGHT)], str(mouse[-1:]))

QTest.mouseClick(btn2, QtCore.Qt.MouseButton.LeftButton)
QTest.keyClick(btn2, QtCore.Qt.Key.Key_F11)
app.processEvents()
check(
    "mouse mode rejects single key (no change)",
    btn2._capturing and keys2 == [],
    "keys=" + str(keys2) + " capturing=" + str(btn2._capturing),
)
QTest.keyClick(btn2, QtCore.Qt.Key.Key_Escape)
app.processEvents()

# 纯鼠标按键（无修饰键）不修改当前快捷键
QTest.mouseClick(btn2, QtCore.Qt.MouseButton.LeftButton)
app.processEvents()
before = len(mouse)
QTest.mouseClick(host, QtCore.Qt.MouseButton.RightButton)
app.processEvents()
check(
    "plain mouse click does not modify shortcut",
    btn2._capturing and len(mouse) == before,
    "mouse=" + str(mouse) + " capturing=" + str(btn2._capturing),
)
QTest.keyClick(btn2, QtCore.Qt.Key.Key_Escape)
app.processEvents()

# ---------- EditTrigger ----------
t = mod.EditTrigger()
check("trigger default text", t.display_text() == "Ctrl+右键", t.display_text())
t.set_trigger("F10", mod.MOUSE_LEFT)
check("trigger set_trigger", t.display_text() == "F10+左键", t.display_text())
t.restore_default()
check("trigger restore_default", t.display_text() == "Ctrl+右键", t.display_text())
t.save()
t2 = mod.EditTrigger()
t2.load()
check("trigger save/load roundtrip", t2.display_text() == "Ctrl+右键", t2.display_text())

# ---------- 面板快捷键区域 ----------
mw = QtWidgets.QMainWindow()
dlg = mod.ChineseTranslationToolDialog(mw)
shortcut_labels = [
    label.text()
    for label in dlg.findChildren(QtWidgets.QLabel)
    if label.text() in ("启用/禁用插件翻译", "更改翻译弹窗")
]
check(
    "shortcut buttons merged into one row",
    shortcut_labels == ["启用/禁用插件翻译", "更改翻译弹窗"],
    str(shortcut_labels),
)

# ---------- 快捷键回调路由（识别在 C++，Python 只接收回调） ----------
toggles, edits = [], []
orig_toggle = mod._toggle_enable_shortcut
orig_edit = mod._show_edit_at_cursor
mod._toggle_enable_shortcut = lambda: toggles.append(1)
mod._show_edit_at_cursor = lambda: edits.append(1)

mod._on_shortcut(0)
check("callback 0 toggles translation", toggles == [1], str(toggles))
mod._on_shortcut(1)
check("callback 1 opens edit popup", edits == [1], str(edits))
mod._apply_shortcuts()
check("apply_shortcuts safe without native dll", True, "")

mod._toggle_enable_shortcut = orig_toggle
mod._show_edit_at_cursor = orig_edit

failed = [r for r in RESULTS if not r[1]]
print("SUMMARY:", len(RESULTS) - len(failed), "passed,", len(failed), "failed")
raise SystemExit(1 if failed else 0)

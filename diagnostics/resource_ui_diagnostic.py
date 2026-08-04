# -*- coding: utf-8 -*-
"""Substance Painter asset UI runtime inspector (read-only)."""

import os
import traceback

from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid

try:
    from PySide6 import QtQuickWidgets
except Exception:
    QtQuickWidgets = None


_timer = None


def _safe(obj):
    try:
        return obj is not None and isValid(obj)
    except Exception:
        return False


def _value(obj, name):
    try:
        value = obj.property(name)
        if value is not None:
            return repr(value)[:500]
    except Exception:
        pass
    return ""


def _parent_chain(obj):
    result = []
    current = obj
    for _ in range(10):
        try:
            current = current.parent()
        except Exception:
            break
        if not _safe(current):
            break
        try:
            meta = current.metaObject()
            result.append(f"{meta.className()}({current.objectName()!r})")
        except Exception:
            break
    return " <- ".join(result)


def _sample_model(view, lines):
    try:
        model = view.model()
        if not _safe(model):
            lines.append("    model: <none>")
            return
        meta = model.metaObject()
        lines.append(f"    model: {meta.className()} objectName={model.objectName()!r}")
        try:
            roles = {int(key): bytes(value).decode("utf-8", "replace") for key, value in model.roleNames().items()}
            lines.append(f"    roles: {roles}")
        except Exception as exc:
            lines.append(f"    roles error: {exc!r}")
        parent = QtCore.QModelIndex()
        rows = min(20, model.rowCount(parent))
        columns = min(3, model.columnCount(parent))
        for row in range(rows):
            values = []
            for column in range(columns):
                index = model.index(row, column, parent)
                values.append(repr(model.data(index, QtCore.Qt.ItemDataRole.DisplayRole))[:180])
            lines.append(f"    row {row}: {values}")
    except Exception:
        lines.append("    model inspection failed:\n" + traceback.format_exc())


def _walk_qml(obj, lines, depth=0, seen=None):
    if seen is None:
        seen = set()
    if not _safe(obj) or depth > 12 or id(obj) in seen:
        return
    seen.add(id(obj))
    try:
        meta = obj.metaObject()
        interesting = []
        for name in ("text", "title", "label", "display", "displayText", "model", "delegate", "contentItem", "currentText"):
            value = _value(obj, name)
            if value:
                interesting.append(f"{name}={value}")
        lines.append(f"{'  ' * depth}{meta.className()} name={obj.objectName()!r} {' '.join(interesting)}")
        for child in obj.children():
            _walk_qml(child, lines, depth + 1, seen)
    except Exception:
        pass


def capture_report():
    app = QtWidgets.QApplication.instance()
    if not _safe(app):
        return
    lines = ["Substance Painter 资源 UI 诊断报告", "=" * 80]
    widgets = list(app.allWidgets())
    lines.append(f"allWidgets count: {len(widgets)}")

    for widget in widgets:
        if not _safe(widget) or not widget.isVisible():
            continue
        try:
            meta = widget.metaObject()
            class_name = meta.className()
            object_name = widget.objectName() or ""
            title = widget.windowTitle() if hasattr(widget, "windowTitle") else ""
            global_pos = widget.mapToGlobal(QtCore.QPoint(0, 0))
            geometry = (global_pos.x(), global_pos.y(), widget.width(), widget.height())
            chain = _parent_chain(widget)
            searchable = " ".join((class_name, object_name, title, chain)).lower()
            relevant = (
                isinstance(widget, QtWidgets.QAbstractItemView)
                or "asset" in searchable
                or "resource" in searchable
                or "shelf" in searchable
                or "project" in searchable
                or "quick" in searchable
            )
            if not relevant:
                continue
            lines.append("-" * 80)
            lines.append(f"widget: {class_name} objectName={object_name!r} title={title!r} geometry={geometry}")
            lines.append(f"  python type: {type(widget)!r}")
            lines.append(f"  parents: {chain}")
            if isinstance(widget, QtWidgets.QAbstractItemView):
                try:
                    delegate = widget.itemDelegate()
                    lines.append(f"  delegate: {type(delegate)!r} / {delegate.metaObject().className()}")
                except Exception as exc:
                    lines.append(f"  delegate error: {exc!r}")
                _sample_model(widget, lines)
            if QtQuickWidgets and isinstance(widget, QtQuickWidgets.QQuickWidget):
                lines.append("  QML TREE:")
                _walk_qml(widget.rootObject(), lines)
        except Exception:
            lines.append(traceback.format_exc())

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "资源UI诊断报告.txt")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    print(f">>> 资源 UI 诊断完成: {path}")


def start_plugin():
    global _timer
    close_plugin()
    app = QtWidgets.QApplication.instance()
    if not _safe(app):
        return
    _timer = QtCore.QTimer()
    _timer.setSingleShot(True)
    _timer.setInterval(8000)
    _timer.timeout.connect(capture_report)
    _timer.start()


def close_plugin():
    global _timer
    if _safe(_timer):
        try:
            _timer.stop()
            delete(_timer)
        except Exception:
            pass
    _timer = None

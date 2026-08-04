# -*- coding: utf-8 -*-
"""Temporary native-widget type sniffer for Substance 3D Painter."""

import os
import time

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, isValid


_timer = None
_last_signature = None
_report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "widget_type_sniffer_report.txt")


def _safe(obj):
    try:
        return obj is not None and isValid(obj)
    except Exception:
        return False


def _value(obj, getter):
    try:
        value = getattr(obj, getter)()
        return str(value).replace("\r", " ").replace("\n", " ")[:160]
    except Exception:
        return ""


def _describe(widget):
    rows = []
    current = widget
    depth = 0
    while _safe(current) and depth < 10:
        try:
            meta = current.metaObject()
            cpp_class = meta.className() if meta else ""
            bases = []
            parent_meta = meta.superClass() if meta else None
            while parent_meta is not None and len(bases) < 8:
                bases.append(parent_meta.className())
                parent_meta = parent_meta.superClass()

            attrs = []
            for getter in ("text", "title", "currentText", "placeholderText", "toolTip"):
                value = _value(current, getter)
                if value:
                    attrs.append(f"{getter}={value!r}")

            rows.append(
                f"  [{depth}] cpp={cpp_class!r} python={type(current).__name__!r} "
                f"object={_value(current, 'objectName')!r} "
                f"bases={bases!r} attrs={attrs!r}"
            )
            current = current.parentWidget()
            depth += 1
        except Exception as exc:
            rows.append(f"  [{depth}] <读取失败: {exc!r}>")
            break
    return rows


def _sample():
    global _last_signature
    app = QtWidgets.QApplication.instance()
    if not _safe(app) or app.closingDown():
        return
    try:
        pos = QtGui.QCursor.pos()
        widget = app.widgetAt(pos)
        if not _safe(widget):
            return
        meta = widget.metaObject()
        signature = (int(widget.winId()), meta.className() if meta else "",
                     widget.objectName())
        if signature == _last_signature:
            return
        _last_signature = signature
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        block = [f"\n=== {stamp} cursor=({pos.x()},{pos.y()}) ==="]
        block.extend(_describe(widget))
        with open(_report_path, "a", encoding="utf-8") as stream:
            stream.write("\n".join(block) + "\n")
    except Exception:
        pass


def start_plugin():
    global _timer, _last_signature
    close_plugin()
    _last_signature = None
    try:
        with open(_report_path, "w", encoding="utf-8") as stream:
            stream.write("Substance Painter 控件类型嗅探报告\n")
    except Exception:
        pass
    app = QtWidgets.QApplication.instance()
    if not _safe(app):
        return
    _timer = QtCore.QTimer(app)
    _timer.setInterval(150)
    _timer.timeout.connect(_sample)
    _timer.start()
    print(">>> 控件类型嗅探已启动:", _report_path)


def close_plugin():
    global _timer
    if _safe(_timer):
        try:
            _timer.stop()
            _timer.timeout.disconnect(_sample)
            delete(_timer)
        except Exception:
            pass
    _timer = None

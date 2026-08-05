# -*- coding: utf-8 -*-
"""Temporary Substance Painter Layers-panel control sniffer.

Install this file in Painter's ``python/plugins`` directory and enable it from
the Python menu. It continuously records unique controls below the cursor,
all visible Layers-panel widgets, and open QMenu/QAction geometry. The report
is written to the user's Desktop as ``sp_layers_panel_controls_report.json``.
"""

import json
import os
import time

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid


_timer = None
_records = {}
_report_path = os.path.join(
    os.path.expanduser("~/Desktop"), "sp_layers_panel_controls_report.json"
)


def _safe(obj):
    try:
        return obj is not None and isValid(obj)
    except Exception:
        return False


def _cpp_class(obj):
    try:
        meta = obj.metaObject()
        return meta.className() if meta else ""
    except Exception:
        return ""


def _text(obj, getter):
    try:
        value = getattr(obj, getter)()
        return str(value).replace("\r", " ").replace("\n", " ")[:500]
    except Exception:
        return ""


def _rect(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def _enum_value(value):
    """Return the numeric value of PySide6 scoped and legacy enums."""
    try:
        return int(value.value)
    except (AttributeError, TypeError, ValueError):
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value)


def _is_layers_widget(widget):
    current = widget
    depth = 0
    while _safe(current) and depth < 20:
        class_name = _cpp_class(current)
        object_name = _text(current, "objectName")
        if (
            "LayerStack" in class_name
            or "LayerTree" in class_name
            or "DockLayers" in object_name
        ):
            return True
        if isinstance(current, QtWidgets.QDockWidget):
            if _text(current, "windowTitle").strip() in ("Layers", "图层"):
                return True
        try:
            current = current.parentWidget()
        except Exception:
            break
        depth += 1
    return False


def _parent_chain(widget):
    chain = []
    current = widget
    depth = 0
    while _safe(current) and depth < 16:
        entry = {
            "depth": depth,
            "cpp_class": _cpp_class(current),
            "python_type": type(current).__name__,
            "object_name": _text(current, "objectName"),
        }
        for getter in ("text", "title", "currentText", "windowTitle"):
            value = _text(current, getter)
            if value:
                entry[getter] = value
        chain.append(entry)
        try:
            current = current.parentWidget()
        except Exception:
            break
        depth += 1
    return chain


def _describe_action(action, menu):
    data = {
        "text": _text(action, "text"),
        "object_name": _text(action, "objectName"),
        "separator": bool(action.isSeparator()),
        "checkable": bool(action.isCheckable()),
        "enabled": bool(action.isEnabled()),
        "visible": bool(action.isVisible()),
    }
    try:
        data["geometry"] = _rect(menu.actionGeometry(action))
    except Exception:
        pass
    try:
        data["font_point_size"] = action.font().pointSizeF()
    except Exception:
        pass
    return data


def _describe(widget, reason):
    size_policy = widget.sizePolicy()
    data = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "cpp_class": _cpp_class(widget),
        "python_type": type(widget).__name__,
        "object_name": _text(widget, "objectName"),
        "layers_descendant": _is_layers_widget(widget),
        "visible": bool(widget.isVisible()),
        "enabled": bool(widget.isEnabled()),
        "geometry": _rect(widget.geometry()),
        "frame_geometry": _rect(widget.frameGeometry()),
        "size_hint": [widget.sizeHint().width(), widget.sizeHint().height()],
        "minimum_size_hint": [
            widget.minimumSizeHint().width(),
            widget.minimumSizeHint().height(),
        ],
        "minimum_size": [widget.minimumWidth(), widget.minimumHeight()],
        "maximum_size": [widget.maximumWidth(), widget.maximumHeight()],
        "size_policy": {
            "horizontal": _enum_value(size_policy.horizontalPolicy()),
            "vertical": _enum_value(size_policy.verticalPolicy()),
            "horizontal_stretch": size_policy.horizontalStretch(),
            "vertical_stretch": size_policy.verticalStretch(),
        },
        "font": {
            "family": widget.font().family(),
            "point_size": widget.font().pointSizeF(),
            "pixel_size": widget.font().pixelSize(),
        },
        "parent_chain": _parent_chain(widget),
    }
    for getter in (
        "text",
        "title",
        "currentText",
        "windowTitle",
        "toolTip",
        "statusTip",
    ):
        value = _text(widget, getter)
        if value:
            data[getter] = value

    if isinstance(widget, QtWidgets.QComboBox):
        view = widget.view()
        data["combo"] = {
            "count": widget.count(),
            "current_index": widget.currentIndex(),
            "items": [widget.itemText(i) for i in range(widget.count())],
            "view_cpp_class": _cpp_class(view),
            "view_python_type": type(view).__name__ if _safe(view) else "",
            "size_adjust_policy": _enum_value(widget.sizeAdjustPolicy()),
            "minimum_contents_length": widget.minimumContentsLength(),
        }
    if isinstance(widget, QtWidgets.QAbstractItemView):
        data["item_view"] = {
            "model_cpp_class": _cpp_class(widget.model()),
            "delegate_cpp_class": _cpp_class(widget.itemDelegate()),
            "text_elide_mode": _enum_value(widget.textElideMode()),
        }
    if isinstance(widget, QtWidgets.QMenu):
        data["menu"] = {
            "column_count": widget.columnCount(),
            "actions": [_describe_action(action, widget) for action in widget.actions()],
        }
    return data


def _key(widget, reason):
    try:
        pointer = int(widget.winId())
    except Exception:
        pointer = id(widget)
    current = _text(widget, "currentText") or _text(widget, "text")
    return "|".join((reason, str(pointer), _cpp_class(widget), current))


def _record(widget, reason):
    if not _safe(widget):
        return
    try:
        _records[_key(widget, reason)] = _describe(widget, reason)
    except Exception as exc:
        _records[f"error-{time.time_ns()}"] = {
            "reason": reason,
            "error": repr(exc),
        }


def _write_report():
    payload = {
        "schema": "sp-layers-widget-sniffer-v1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "instructions": (
            "展开图层通道与混合模式菜单，并把鼠标移到相关控件上。"
            "完成后关闭 Painter 或在 Python 菜单中停用此脚本。"
        ),
        "records": list(_records.values()),
    }
    temporary = _report_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary, _report_path)


def _sample():
    app = QtWidgets.QApplication.instance()
    if not _safe(app) or app.closingDown():
        return
    try:
        cursor_widget = app.widgetAt(QtGui.QCursor.pos())
        if _safe(cursor_widget) and (
            _is_layers_widget(cursor_widget)
            or isinstance(cursor_widget.window(), QtWidgets.QMenu)
        ):
            _record(cursor_widget, "cursor")
            if _safe(cursor_widget.window()) and isinstance(
                cursor_widget.window(), QtWidgets.QMenu
            ):
                _record(cursor_widget.window(), "open_menu")

        for widget in app.allWidgets():
            if not _safe(widget) or not widget.isVisible():
                continue
            if _is_layers_widget(widget):
                _record(widget, "layers_snapshot")
            elif isinstance(widget, QtWidgets.QMenu):
                texts = {_text(action, "text") for action in widget.actions()}
                if texts.intersection(
                    {"Normal", "Passthrough", "正常", "穿透", "Pthr"}
                ):
                    _record(widget, "blend_menu")
        _write_report()
    except Exception as exc:
        print(">>> 图层控件嗅探采样失败:", exc)


def start_plugin():
    global _timer, _records
    close_plugin()
    _records = {}
    app = QtWidgets.QApplication.instance()
    if not _safe(app):
        return
    _timer = QtCore.QTimer(app)
    _timer.setInterval(250)
    _timer.timeout.connect(_sample)
    _timer.start()
    _sample()
    print(">>> 图层面板控件嗅探已启动:", _report_path)


def close_plugin():
    global _timer
    if _safe(_timer):
        try:
            _timer.stop()
            _timer.timeout.disconnect(_sample)
        except Exception:
            pass
    _timer = None
    if _records:
        try:
            _write_report()
        except Exception:
            pass

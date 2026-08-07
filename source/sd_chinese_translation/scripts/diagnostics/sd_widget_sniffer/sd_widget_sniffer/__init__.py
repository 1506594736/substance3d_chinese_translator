# -*- coding: utf-8 -*-
"""Read-only Qt control type sniffer for Substance 3D Designer."""

import json
import os
import time
import traceback
from collections import Counter

import sd
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid

try:
    from PySide6 import QtQuickWidgets
except ImportError:
    QtQuickWidgets = None


REPORT_DIR = os.path.join(
    os.path.expanduser("~"), "Desktop", "sd_widget_sniffer_reports"
)
TEXT_PROPERTIES = (
    "text",
    "title",
    "windowTitle",
    "currentText",
    "placeholderText",
    "toolTip",
    "statusTip",
    "whatsThis",
    "accessibleName",
    "accessibleDescription",
)
MODEL_ROLES = (
    QtCore.Qt.ItemDataRole.DisplayRole,
    QtCore.Qt.ItemDataRole.EditRole,
    QtCore.Qt.ItemDataRole.ToolTipRole,
    QtCore.Qt.ItemDataRole.AccessibleTextRole,
    QtCore.Qt.ItemDataRole.UserRole,
)
GRAPHICS_DATA_ROLES = range(0, 65)
MAX_GRAPHICS_ITEMS = 5000

_menu = None
_timer = None
_running = False
_samples = {}
_last_hover_key = None
_last_report_paths = ()


def _valid(obj):
    try:
        return obj is not None and isValid(obj)
    except Exception:
        return False


def _clean(value, limit=500):
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _meta_class(obj):
    try:
        meta = obj.metaObject()
        return meta.className() if meta else type(obj).__name__
    except Exception:
        return type(obj).__name__


def _inheritance(obj):
    result = []
    try:
        meta = obj.metaObject()
        while meta is not None and len(result) < 24:
            result.append(meta.className())
            meta = meta.superClass()
    except Exception:
        pass
    return result


def _property_value(obj, name):
    try:
        meta = obj.metaObject()
        index = meta.indexOfProperty(name)
        if index >= 0:
            value = meta.property(index).read(obj)
        else:
            value = obj.property(name)
        return _clean(value)
    except Exception:
        return ""


def _dynamic_properties(obj):
    result = {}
    try:
        for raw_name in obj.dynamicPropertyNames():
            name = bytes(raw_name).decode("utf-8", "replace")
            if name.startswith("_q_"):
                continue
            result[name] = _clean(obj.property(name))
    except Exception:
        pass
    return result


def _parent_chain(widget, limit=16):
    result = []
    current = widget
    for _ in range(limit):
        try:
            current = current.parentWidget()
        except Exception:
            break
        if not _valid(current):
            break
        result.append(
            {
                "cpp_class": _meta_class(current),
                "object_name": _clean(current.objectName()),
            }
        )
    return result


def _geometry(widget):
    try:
        top_left = widget.mapToGlobal(QtCore.QPoint(0, 0))
        return {
            "x": top_left.x(),
            "y": top_left.y(),
            "width": widget.width(),
            "height": widget.height(),
            "visible": widget.isVisible(),
            "enabled": widget.isEnabled(),
        }
    except Exception:
        return {}


def _action_details(action):
    return {
        "cpp_class": _meta_class(action),
        "object_name": _clean(action.objectName()),
        "text": _clean(action.text()),
        "tool_tip": _clean(action.toolTip()),
        "checkable": bool(action.isCheckable()),
        "separator": bool(action.isSeparator()),
    }


def _model_details(view, cursor_pos=None):
    details = {}
    try:
        model = view.model()
        if not _valid(model):
            return details
        details["model_cpp_class"] = _meta_class(model)
        details["model_python_class"] = type(model).__name__
        details["model_object_name"] = _clean(model.objectName())
        details["model_inheritance"] = _inheritance(model)
        try:
            details["role_names"] = {
                str(int(role)): bytes(name).decode("utf-8", "replace")
                for role, name in model.roleNames().items()
            }
        except Exception:
            details["role_names"] = {}

        delegate = view.itemDelegate()
        if _valid(delegate):
            details["delegate_cpp_class"] = _meta_class(delegate)
            details["delegate_python_class"] = type(delegate).__name__
            details["delegate_inheritance"] = _inheritance(delegate)

        if cursor_pos is not None:
            local = view.viewport().mapFromGlobal(cursor_pos)
            index = view.indexAt(local)
            if index.isValid():
                details["index_at_cursor"] = {
                    "row": index.row(),
                    "column": index.column(),
                    "roles": {
                        str(int(role)): _clean(model.data(index, role))
                        for role in MODEL_ROLES
                        if model.data(index, role) is not None
                    },
                }
    except Exception as exc:
        details["inspection_error"] = repr(exc)
    return details


def _graphics_item_text(item):
    result = {}
    for getter in ("toPlainText", "text", "toolTip"):
        try:
            value = _clean(getattr(item, getter)())
            if value:
                result[getter] = value
        except Exception:
            pass
    return result


def _graphics_item_parent_chain(item, limit=12):
    result = []
    current = item
    for _ in range(limit):
        try:
            current = current.parentItem()
        except Exception:
            break
        if current is None:
            break
        result.append(
            {
                "python_class": type(current).__name__,
                "item_type": int(current.type()),
                "text": _graphics_item_text(current),
            }
        )
    return result


def _graphics_item_record(item):
    record = {
        "python_class": type(item).__name__,
        "item_type": int(item.type()),
        "text": _graphics_item_text(item),
        "data_roles": {},
        "child_count": 0,
        "parent_items": _graphics_item_parent_chain(item),
    }
    try:
        record["child_count"] = len(item.childItems())
        record["visible"] = bool(item.isVisible())
        record["enabled"] = bool(item.isEnabled())
        record["selected"] = bool(item.isSelected())
        record["z_value"] = float(item.zValue())
        rect = item.sceneBoundingRect()
        record["scene_rect"] = {
            "x": rect.x(),
            "y": rect.y(),
            "width": rect.width(),
            "height": rect.height(),
        }
    except Exception:
        pass
    for role in GRAPHICS_DATA_ROLES:
        try:
            value = item.data(role)
            if value is not None:
                cleaned = _clean(value)
                if cleaned:
                    record["data_roles"][str(role)] = cleaned
        except Exception:
            pass
    try:
        meta = item.metaObject()
        if meta:
            record["cpp_class"] = meta.className()
            record["inheritance"] = _inheritance(item)
            record["object_name"] = _clean(item.objectName())
            record["dynamic_properties"] = _dynamic_properties(item)
    except Exception:
        pass
    return record


def _graphics_scene_details(view, cursor_pos=None):
    details = {}
    try:
        scene = view.scene()
        if scene is None:
            return details
        details["scene_cpp_class"] = _meta_class(scene)
        details["scene_python_class"] = type(scene).__name__
        details["scene_object_name"] = _clean(scene.objectName())
        all_items = list(scene.items())
        items = all_items[:MAX_GRAPHICS_ITEMS]
        details["item_count"] = len(all_items)
        groups = Counter((type(item).__name__, int(item.type())) for item in items)
        details["item_types"] = [
            {
                "python_class": python_class,
                "item_type": item_type,
                "count": count,
            }
            for (python_class, item_type), count in sorted(groups.items())
        ]
        examples = {}
        for item in items:
            key = f"{type(item).__name__}:{int(item.type())}"
            if key not in examples:
                examples[key] = _graphics_item_record(item)
        details["type_examples"] = list(examples.values())
        details["text_items"] = [
            record
            for record in (_graphics_item_record(item) for item in items)
            if record.get("text") or record.get("data_roles")
        ][:1000]

        if cursor_pos is not None:
            viewport_pos = view.viewport().mapFromGlobal(cursor_pos)
            scene_pos = view.mapToScene(viewport_pos)
            details["cursor_scene_position"] = {
                "x": scene_pos.x(),
                "y": scene_pos.y(),
            }
            details["items_at_cursor"] = [
                _graphics_item_record(item)
                for item in scene.items(scene_pos)[:100]
            ]
    except Exception as exc:
        details["inspection_error"] = repr(exc)
        details["traceback"] = traceback.format_exc()
    return details


def _widget_record(widget, origin, cursor_pos=None):
    record = {
        "origin": origin,
        "cpp_class": _meta_class(widget),
        "python_class": type(widget).__name__,
        "inheritance": _inheritance(widget),
        "object_name": _clean(widget.objectName()),
        "geometry": _geometry(widget),
        "properties": {},
        "dynamic_properties": _dynamic_properties(widget),
        "parents": _parent_chain(widget),
    }
    for name in TEXT_PROPERTIES:
        value = _property_value(widget, name)
        if value:
            record["properties"][name] = value

    if isinstance(widget, QtWidgets.QAbstractItemView):
        record["item_view"] = _model_details(widget, cursor_pos)
    if isinstance(widget, QtWidgets.QGraphicsView):
        record["graphics_scene"] = _graphics_scene_details(widget, cursor_pos)
    if isinstance(widget, QtWidgets.QMenu):
        record["actions"] = [_action_details(action) for action in widget.actions()]
    if isinstance(widget, QtWidgets.QComboBox):
        record["combo"] = {
            "count": widget.count(),
            "items": [_clean(widget.itemText(i)) for i in range(min(widget.count(), 100))],
            "view": _meta_class(widget.view()) if _valid(widget.view()) else "",
            "model": _meta_class(widget.model()) if _valid(widget.model()) else "",
            "delegate": _meta_class(widget.itemDelegate())
            if _valid(widget.itemDelegate())
            else "",
        }
    if isinstance(widget, QtWidgets.QTabBar):
        record["tabs"] = [_clean(widget.tabText(i)) for i in range(widget.count())]
    if QtQuickWidgets and isinstance(widget, QtQuickWidgets.QQuickWidget):
        root = widget.rootObject()
        record["qml_root_class"] = _meta_class(root) if _valid(root) else ""
    return record


def _record_key(record):
    parents = tuple(
        (item["cpp_class"], item["object_name"])
        for item in record.get("parents", ())[:6]
    )
    properties = record.get("properties", {})
    return (
        record.get("cpp_class", ""),
        record.get("object_name", ""),
        properties.get("text", ""),
        properties.get("title", ""),
        properties.get("currentText", ""),
        parents,
    )


def _capture_widget(widget, origin, cursor_pos=None):
    if not _valid(widget):
        return
    try:
        record = _widget_record(widget, origin, cursor_pos)
        key = repr(_record_key(record))
        previous = _samples.get(key, {})
        previous_view = previous.get("item_view", {})
        current_view = record.get("item_view", {})
        if "index_at_cursor" in previous_view and "index_at_cursor" not in current_view:
            current_view["index_at_cursor"] = previous_view["index_at_cursor"]
            record["item_view"] = current_view
        if previous.get("origin") == "cursor" and origin == "full_scan":
            record["origin"] = "cursor+full_scan"
        record["sample_count"] = previous.get("sample_count", 0) + 1
        _samples[key] = record
    except Exception:
        pass


def _sample_cursor():
    global _last_hover_key
    try:
        if not _running:
            return
        app = QtWidgets.QApplication.instance()
        if not _valid(app) or app.closingDown():
            return
        position = QtGui.QCursor.pos()
        widget = app.widgetAt(position)
        if not _valid(widget):
            return
        hover_key = (id(widget), position.x(), position.y())
        if _last_hover_key and hover_key[0] == _last_hover_key[0]:
            return
        _last_hover_key = hover_key
        _capture_widget(widget, "cursor", position)
        if not _valid(widget):
            return
        current = widget.parentWidget()
        for _ in range(12):
            if not _valid(current):
                break
            if isinstance(
                current,
                (QtWidgets.QAbstractItemView, QtWidgets.QGraphicsView),
            ):
                _capture_widget(current, "cursor_ancestor", position)
            if not _valid(current):
                break
            current = current.parentWidget()
    except RuntimeError:
        # Designer creates and destroys transient menu/tooltip/viewport widgets
        # between timer ticks. A stale PySide wrapper is expected and harmless.
        return
    except Exception:
        return


def _capture_all():
    app = QtWidgets.QApplication.instance()
    if not _valid(app):
        return
    cursor = QtGui.QCursor.pos()
    for widget in list(app.allWidgets()):
        if _valid(widget):
            _capture_widget(widget, "full_scan", cursor)


def _summary(records):
    cpp_types = Counter(record.get("cpp_class", "") for record in records)
    python_types = Counter(record.get("python_class", "") for record in records)
    models = Counter()
    delegates = Counter()
    for record in records:
        view = record.get("item_view", {})
        if view.get("model_cpp_class"):
            models[view["model_cpp_class"]] += 1
        if view.get("delegate_cpp_class"):
            delegates[view["delegate_cpp_class"]] += 1
    return {
        "cpp_widget_types": dict(sorted(cpp_types.items())),
        "python_widget_types": dict(sorted(python_types.items())),
        "model_types": dict(sorted(models.items())),
        "delegate_types": dict(sorted(delegates.items())),
    }


def _write_reports():
    global _last_report_paths
    _capture_all()
    os.makedirs(REPORT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(REPORT_DIR, f"sd_widget_types_{timestamp}.json")
    text_path = os.path.join(REPORT_DIR, f"sd_widget_types_{timestamp}.txt")
    records = sorted(
        _samples.values(),
        key=lambda item: (
            item.get("cpp_class", ""),
            item.get("object_name", ""),
            repr(item.get("properties", {})),
        ),
    )
    payload = {
        "application": "Adobe Substance 3D Designer",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "record_count": len(records),
        "summary": _summary(records),
        "records": records,
    }
    with open(json_path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)

    lines = [
        "Substance 3D Designer 控件类型嗅探报告",
        "=" * 88,
        f"记录数：{len(records)}",
        "",
    ]
    for group, values in payload["summary"].items():
        lines.append(f"[{group}]")
        lines.extend(f"  {name}: {count}" for name, count in values.items())
        lines.append("")
    lines.append("[records]")
    for record in records:
        lines.append("-" * 88)
        lines.append(
            f"cpp={record['cpp_class']!r} python={record['python_class']!r} "
            f"object={record['object_name']!r} origin={record['origin']!r}"
        )
        lines.append(f"  inheritance={record['inheritance']!r}")
        lines.append(f"  properties={record['properties']!r}")
        lines.append(f"  dynamic={record['dynamic_properties']!r}")
        lines.append(f"  geometry={record['geometry']!r}")
        lines.append(f"  parents={record['parents']!r}")
        if "item_view" in record:
            lines.append(f"  item_view={record['item_view']!r}")
        if "graphics_scene" in record:
            lines.append(f"  graphics_scene={record['graphics_scene']!r}")
        if "combo" in record:
            lines.append(f"  combo={record['combo']!r}")
        if "actions" in record:
            lines.append(f"  actions={record['actions']!r}")
    with open(text_path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    _last_report_paths = (json_path, text_path)
    print("[SD 控件嗅探器] 报告已生成：", json_path)
    return json_path, text_path


def _start():
    global _running, _timer, _last_hover_key
    _samples.clear()
    _last_hover_key = None
    _running = True
    if not _valid(_timer):
        app = QtWidgets.QApplication.instance()
        _timer = QtCore.QTimer(app)
        _timer.setInterval(120)
        _timer.timeout.connect(_sample_cursor)
    _timer.start()
    print("[SD 控件嗅探器] 已开始；请依次悬停、展开和点击需要分析的控件。")


def _stop_and_export():
    global _running
    _running = False
    if _valid(_timer):
        _timer.stop()
    paths = _write_reports()
    QtWidgets.QMessageBox.information(
        None,
        "SD 控件嗅探器",
        "嗅探完成，已生成：\n" + "\n".join(paths),
    )


def _snapshot():
    _capture_all()
    paths = _write_reports()
    QtWidgets.QMessageBox.information(
        None,
        "SD 控件嗅探器",
        "全量快照已生成：\n" + "\n".join(paths),
    )


def _open_report_directory():
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.startfile(REPORT_DIR)


def initializeSDPlugin():
    global _menu
    application = sd.getContext().getSDApplication()
    ui_manager = application.getQtForPythonUIMgr()
    main_window = ui_manager.getMainWindow()
    _menu = ui_manager.newMenu("SD 控件嗅探器", "sd_widget_type_sniffer_menu")

    start_action = QtGui.QAction("开始嗅探", main_window)
    start_action.triggered.connect(_start)
    _menu.addAction(start_action)

    stop_action = QtGui.QAction("停止并导出报告", main_window)
    stop_action.triggered.connect(_stop_and_export)
    _menu.addAction(stop_action)

    snapshot_action = QtGui.QAction("立即生成全量快照", main_window)
    snapshot_action.triggered.connect(_snapshot)
    _menu.addAction(snapshot_action)

    open_action = QtGui.QAction("打开报告目录", main_window)
    open_action.triggered.connect(_open_report_directory)
    _menu.addAction(open_action)


def uninitializeSDPlugin():
    global _menu, _timer, _running
    _running = False
    if _valid(_timer):
        _timer.stop()
        _timer.deleteLater()
    _timer = None
    if _valid(_menu):
        _menu.deleteLater()
    _menu = None

import json
import os
from datetime import datetime

import substance_painter as sp
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import getCppPointer, isValid


PLUGIN_NAME = "sp_resource_tree_sniffer"
ANCHORS = {
    "alphas", "colorluts", "effects", "emitters", "environments",
    "fonts", "generators", "materials", "presets", "procedurals",
    "receivers", "shaders", "smart-masks", "smart-materials", "textures",
}
_action = None


def _safe(obj):
    try:
        return obj is not None and isValid(obj)
    except Exception:
        return False


def _pointer(obj):
    try:
        return hex(int(getCppPointer(obj)[0])) if _safe(obj) else None
    except Exception:
        return None


def _class_name(obj):
    try:
        return obj.metaObject().className()
    except Exception:
        return type(obj).__name__ if obj is not None else None


def _parent_chain(obj, limit=12):
    result = []
    current = obj
    for _ in range(limit):
        try:
            current = current.parent()
        except Exception:
            break
        if current is None:
            break
        result.append({
            "class": _class_name(current),
            "object_name": current.objectName() if isinstance(current, QtCore.QObject) else "",
            "pointer": _pointer(current),
        })
    return result


def _role_value(model, index, role):
    try:
        value = model.data(index, role)
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        return {"type": type(value).__name__, "repr": repr(value)[:500]}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _index_record(view, model, index, depth):
    display = _role_value(model, index, QtCore.Qt.ItemDataRole.DisplayRole)
    roles = {}
    for role in range(0, 32):
        value = _role_value(model, index, role)
        if value is not None:
            roles[str(role)] = value
    try:
        flags = str(model.flags(index))
    except Exception as exc:
        flags = f"error: {exc}"
    try:
        rect = view.visualRect(index)
        visual_rect = [rect.x(), rect.y(), rect.width(), rect.height()]
    except Exception:
        visual_rect = None
    return {
        "depth": depth,
        "row": index.row(),
        "column": index.column(),
        "display": display,
        "roles_0_31": roles,
        "flags": flags,
        "has_children": bool(model.hasChildren(index)),
        "expanded": bool(view.isExpanded(index)) if isinstance(view, QtWidgets.QTreeView) else None,
        "visual_rect": visual_rect,
        "internal_id": str(index.internalId()),
    }


def _scan_model(view, limit=400):
    model = view.model()
    records = []
    anchors = set()
    pending = [(QtCore.QModelIndex(), 0)]
    visited = 0
    errors = []
    while pending and visited < limit:
        parent, depth = pending.pop(0)
        try:
            rows = min(int(model.rowCount(parent)), 100)
        except Exception as exc:
            errors.append(f"rowCount depth {depth}: {type(exc).__name__}: {exc}")
            break
        for row in range(rows):
            try:
                index = model.index(row, 0, parent)
                if not index.isValid():
                    continue
                visited += 1
                record = _index_record(view, model, index, depth)
                records.append(record)
                display = record["display"]
                if isinstance(display, str) and display.strip().casefold() in ANCHORS:
                    anchors.add(display.strip().casefold())
                if depth < 5 and model.hasChildren(index):
                    pending.append((index, depth + 1))
                if visited >= limit:
                    break
            except Exception as exc:
                errors.append(f"index {row} depth {depth}: {type(exc).__name__}: {exc}")
    return records, sorted(anchors), errors


def _view_record(view):
    model = view.model()
    delegate = view.itemDelegate()
    records, anchors, errors = _scan_model(view)
    geometry = view.geometry()
    viewport = view.viewport()
    return {
        "class": _class_name(view),
        "object_name": view.objectName(),
        "pointer": _pointer(view),
        "visible": view.isVisible(),
        "enabled": view.isEnabled(),
        "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
        "viewport_class": _class_name(viewport),
        "viewport_object_name": viewport.objectName(),
        "viewport_pointer": _pointer(viewport),
        "model_class": _class_name(model),
        "model_object_name": model.objectName() if isinstance(model, QtCore.QObject) else "",
        "model_pointer": _pointer(model),
        "delegate_class": _class_name(delegate),
        "delegate_object_name": delegate.objectName() if isinstance(delegate, QtCore.QObject) else "",
        "delegate_pointer": _pointer(delegate),
        "selection_model_class": _class_name(view.selectionModel()),
        "root_index_valid": view.rootIndex().isValid(),
        "uniform_row_heights": view.uniformRowHeights() if isinstance(view, QtWidgets.QTreeView) else None,
        "anchors": anchors,
        "likely_resource_tree": len(anchors) >= 3,
        "parents": _parent_chain(view),
        "model_errors": errors,
        "nodes": records,
    }


def run_sniff():
    app = QtWidgets.QApplication.instance()
    main = sp.ui.get_main_window()
    views = []
    for widget in app.allWidgets():
        if not _safe(widget) or not isinstance(widget, QtWidgets.QAbstractItemView):
            continue
        try:
            record = _view_record(widget)
            if record["visible"] or record["anchors"]:
                views.append(record)
        except Exception as exc:
            views.append({
                "class": _class_name(widget),
                "object_name": widget.objectName(),
                "pointer": _pointer(widget),
                "fatal_error": f"{type(exc).__name__}: {exc}",
            })
    views.sort(key=lambda item: (not item.get("likely_resource_tree", False), item.get("class", "")))
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "qt_version": QtCore.qVersion(),
        "view_count": len(views),
        "views": views,
    }
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource_tree_sniff.json")
    with open(output, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    likely = sum(bool(item.get("likely_resource_tree")) for item in views)
    QtWidgets.QMessageBox.information(
        main,
        "资源目录嗅探完成",
        f"已检查 {len(views)} 个可见 ItemView，识别到 {likely} 个候选资源树。\n\n报告：\n{output}",
    )
    print(f">>> 资源目录嗅探完成: {output}")


def start_plugin():
    global _action
    if _safe(_action):
        return
    _action = QtGui.QAction("资源目录控件嗅探", sp.ui.get_main_window())
    _action.setObjectName("sp_resource_tree_sniffer_action")
    _action.triggered.connect(run_sniff)
    sp.ui.add_action(sp.ui.ApplicationMenu.Window, _action)


def close_plugin():
    global _action
    if _safe(_action):
        try:
            sp.ui.delete_ui_element(_action)
        except Exception:
            pass
    _action = None


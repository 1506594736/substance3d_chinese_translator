# -*- coding: utf-8 -*-
"""
Substance Painter 全控件通用 + 资源库汉化插件 (资源分类树 + 资产全覆盖版)
支持：Substance 3D Painter 11.x (PySide6 / Qt6)
"""

import ctypes
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

import substance_painter as sp
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, getCppPointer, isValid

IS_APP_QUITTING = False
IS_CLEANING = False
IS_TRANSLATION_ENABLED = True
TRANSLATE_LAYERS_PANEL = True
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSLATIONS_DIR = os.path.join(PLUGIN_DIR, "translations")
PACKAGES_DIR = os.path.join(PLUGIN_DIR, "packages")
DELEGATE_DLL_PATH = os.path.join(PACKAGES_DIR, "sp_translation_delegate.dll")
PLUGIN_DISPLAY_NAME = "中文翻译补全插件"
MAX_ARCHIVE_MEMBERS = 50_000
MAX_NESTED_ARCHIVES = 128


# ==========================================
# 1. C++ 指针安全校验与图层面板排他判定
# ==========================================
def is_safe(obj):
    """防崩溃核心检查：确保 Python 对象非空且底层 C++ 指针未被销毁"""
    if obj is None:
        return False
    try:
        return isValid(obj)
    except Exception:
        return False


def is_inside_layers_panel(w):
    """检查控件及其父层级是否属于图层 (Layers) 面板内部"""
    if not is_safe(w):
        return False

    curr = w
    while curr is not None and is_safe(curr):
        if isinstance(curr, QtWidgets.QDockWidget):
            title = curr.windowTitle().strip()
            if title in ("Layers", "图层"):
                return True

        try:
            meta = curr.metaObject()
            c_name = meta.className() if meta else ""
            obj_name = curr.objectName() or ""
            if "LayerStack" in c_name or "LayerTree" in c_name or "DockLayers" in obj_name:
                return True
        except Exception:
            pass

        curr = curr.parent()
    return False


# ==========================================
# 2. JSON translation packages
# ==========================================
TRANSLATE_DICT = {}
TRANSLATE_SOURCE_FILES = {}


def load_translation_packages():
    """Merge every UTF-8 ``*_zh.json`` package beside this plugin.

    Every package must use schema ``sp-translation-v1`` and contain a
    ``translations`` object. Files load alphabetically; a later package
    intentionally overrides duplicate source strings.
    """
    TRANSLATE_DICT.clear()
    TRANSLATE_SOURCE_FILES.clear()
    plugin_dir = TRANSLATIONS_DIR
    if not os.path.isdir(plugin_dir):
        print(f">>> 翻译包目录不存在: {plugin_dir}")
        return
    package_names = sorted(
        (name for name in os.listdir(plugin_dir)
         if name.lower().endswith("_zh.json")),
        key=str.casefold,
    )

    for name in package_names:
        path = os.path.join(plugin_dir, name)
        try:
            with open(path, "r", encoding="utf-8-sig") as stream:
                payload = json.load(stream)
            if not isinstance(payload, dict):
                raise ValueError("package root must be a JSON object")
            if payload.get("$schema") != "sp-translation-v1":
                raise ValueError("unsupported or missing $schema")
            if payload.get("language") != "zh-CN":
                raise ValueError("language must be zh-CN")
            entries = payload.get("translations")
            if not isinstance(entries, dict):
                raise ValueError("translations must be a JSON object")
            loaded = 0
            for source, target in entries.items():
                if isinstance(source, str) and isinstance(target, str) and source and target:
                    TRANSLATE_DICT[source] = target
                    TRANSLATE_SOURCE_FILES[source] = path
                    loaded += 1
            print(f">>> 已加载翻译包 {name}: {loaded} 条")
        except Exception as exc:
            print(f">>> 跳过无效翻译包 {name}: {exc}")


# Native C++ delegate: Painter never calls back into Python while painting or
# destroying the resource view. The DLL pins itself in memory until process
# exit, so its C++ vtable remains valid throughout Qt shutdown.
_native_delegate = None


def _load_native_delegate():
    global _native_delegate
    if _native_delegate is not None:
        return _native_delegate

    path = DELEGATE_DLL_PATH
    try:
        dll = ctypes.CDLL(path)
        dll.sp_delegate_api_version.restype = ctypes.c_int
        dll.sp_delegate_clear_translations.argtypes = []
        dll.sp_delegate_clear_translations.restype = None
        dll.sp_delegate_reserve_translations.argtypes = [ctypes.c_int]
        dll.sp_delegate_reserve_translations.restype = None
        dll.sp_delegate_add_translation.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        dll.sp_delegate_add_translation.restype = None
        dll.sp_delegate_set_translation_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        dll.sp_delegate_set_translation_path.restype = None
        dll.sp_delegate_set_fallback_path.argtypes = [ctypes.c_wchar_p]
        dll.sp_delegate_set_fallback_path.restype = None
        dll.sp_delegate_set_enabled.argtypes = [ctypes.c_int]
        dll.sp_delegate_set_enabled.restype = None
        dll.sp_delegate_set_translate_layers.argtypes = [ctypes.c_int]
        dll.sp_delegate_set_translate_layers.restype = None
        dll.sp_delegate_install.argtypes = [ctypes.c_void_p]
        dll.sp_delegate_install.restype = ctypes.c_int
        dll.sp_delegate_install_ui.argtypes = [ctypes.c_void_p]
        dll.sp_delegate_install_ui.restype = ctypes.c_int
        api_version = dll.sp_delegate_api_version()
        if api_version != 7:
            print(f">>> 原生翻译模块 API 不兼容: 需要 7，实际 {api_version}")
            return None
        _native_delegate = dll
    except Exception as exc:
        print(">>> 原生资源翻译 delegate 加载失败:", exc)
        _native_delegate = None
    return _native_delegate


def _sync_native_dictionary():
    dll = _load_native_delegate()
    if dll is None:
        return False
    try:
        dll.sp_delegate_clear_translations()
        dll.sp_delegate_set_fallback_path(
            os.path.join(TRANSLATIONS_DIR, "user_added_zh.json")
        )
        dll.sp_delegate_set_translate_layers(int(TRANSLATE_LAYERS_PANEL))
        dll.sp_delegate_reserve_translations(len(TRANSLATE_DICT))
        for source, target in TRANSLATE_DICT.items():
            if isinstance(source, str) and isinstance(target, str):
                dll.sp_delegate_add_translation(source, target)
                source_path = TRANSLATE_SOURCE_FILES.get(source)
                if source_path:
                    dll.sp_delegate_set_translation_path(source, source_path)
        dll.sp_delegate_set_enabled(1)
        return True
    except Exception as exc:
        print(">>> 原生资源翻译字典同步失败:", exc)
        return False


def _install_native_delegate(view):
    dll = _load_native_delegate()
    if dll is None or not is_safe(view):
        return False
    try:
        pointer = getCppPointer(view)[0]
        if not pointer:
            return False
        result = dll.sp_delegate_install(ctypes.c_void_p(pointer))
        return result in (1, 2)
    except Exception as exc:
        print(">>> C++ 资源翻译 delegate 安装失败:", exc)
        return False


def _install_native_ui(app):
    dll = _load_native_delegate()
    if dll is None or not is_safe(app):
        return False
    try:
        pointer = getCppPointer(app)[0]
        if not pointer:
            return False
        return dll.sp_delegate_install_ui(ctypes.c_void_p(pointer)) == 1
    except Exception as exc:
        print(">>> C++ 界面翻译引擎安装失败:", exc)
        return False


# ==========================================
# 3. 资源库 纯文本渲染委托
# ==========================================
class AssetTranslateDelegate(QtWidgets.QStyledItemDelegate):

    def displayText(self, value, locale):
        if not IS_TRANSLATION_ENABLED or IS_APP_QUITTING:
            return super().displayText(value, locale)
        try:
            if isinstance(value, str):
                raw = value.strip()
                if raw in TRANSLATE_DICT:
                    return TRANSLATE_DICT[raw]
        except Exception:
            pass
        return super().displayText(value, locale)


# ==========================================
# 4. 单体控件安全汉化处理
# ==========================================
def translate_widget(w):
    if IS_APP_QUITTING or not is_safe(w):
        return

    # 剔除图层面板内部的普通控件
    if is_inside_layers_panel(w):
        return

    try:
        # 标签类 (QLabel 等)
        if hasattr(w, "text") and hasattr(w, "setText") and not isinstance(w, (QtWidgets.QLineEdit, QtWidgets.QComboBox)):
            raw_text = w.text()
            clean_text = raw_text.replace("&", "").strip()

            if clean_text in TRANSLATE_DICT:
                target_text = TRANSLATE_DICT[clean_text]
                if raw_text == target_text:
                    return

                if w.property("_cn_orig_text") is None:
                    w.setProperty("_cn_orig_text", raw_text)
                w.setText(target_text)

        # 按钮类
        elif isinstance(w, QtWidgets.QAbstractButton):
            raw_text = w.text()
            clean_text = raw_text.replace("&", "").strip()

            if clean_text in TRANSLATE_DICT:
                target_text = TRANSLATE_DICT[clean_text]
                if raw_text == target_text:
                    return

                if w.property("_cn_orig_text") is None:
                    w.setProperty("_cn_orig_text", raw_text)
                w.setText(target_text)

        # 下拉组合框 (QComboBox)
        elif isinstance(w, QtWidgets.QComboBox):
            for idx in range(w.count()):
                raw_item = w.itemText(idx)
                clean_item = raw_item.strip()
                if clean_item in TRANSLATE_DICT:
                    target_item = TRANSLATE_DICT[clean_item]
                    if raw_item != target_item:
                        w.setItemText(idx, target_item)

        # 折叠框 Title
        elif isinstance(w, QtWidgets.QGroupBox):
            raw_title = w.title()
            clean_title = raw_title.strip()

            if clean_title in TRANSLATE_DICT:
                target_title = TRANSLATE_DICT[clean_title]
                if raw_title == target_title:
                    return

                if w.property("_cn_orig_title") is None:
                    w.setProperty("_cn_orig_title", raw_title)
                w.setTitle(target_title)

        # Tab 页标签
        elif isinstance(w, QtWidgets.QTabBar):
            for idx in range(w.count()):
                raw_tab = w.tabText(idx)
                clean_tab = raw_tab.strip()

                if clean_tab in TRANSLATE_DICT:
                    target_tab = TRANSLATE_DICT[clean_tab]
                    if raw_tab == target_tab:
                        continue

                    if w.property(f"_cn_orig_tab_{idx}") is None:
                        w.setProperty(f"_cn_orig_tab_{idx}", raw_tab)
                    w.setTabText(idx, target_tab)

        # Dock 悬浮框标题
        elif isinstance(w, QtWidgets.QDockWidget):
            raw_title = w.windowTitle()
            clean_title = raw_title.strip()

            if clean_title in TRANSLATE_DICT:
                target_title = TRANSLATE_DICT[clean_title]
                if raw_title == target_title:
                    return

                if w.property("_cn_orig_win_title") is None:
                    w.setProperty("_cn_orig_win_title", raw_title)
                w.setWindowTitle(target_title)

        # 输入框 Placeholder
        elif hasattr(w, "placeholderText") and hasattr(w, "setPlaceholderText"):
            raw_ph = w.placeholderText()
            clean_ph = raw_ph.strip()

            if clean_ph in TRANSLATE_DICT:
                target_ph = TRANSLATE_DICT[clean_ph]
                if raw_ph == target_ph:
                    return

                if w.property("_cn_orig_ph") is None:
                    w.setProperty("_cn_orig_ph", raw_ph)
                w.setPlaceholderText(target_ph)

    except Exception:
        pass


# ==========================================
# 5. 全局 UI 事件拦截引擎
# ==========================================
class SPUniversalInterceptor(QtCore.QObject):

    def eventFilter(self, obj, event):
        event_type = event.type()

        # Main-window Close arrives before Painter unloads Python plugins and
        # before child views begin native destruction. Detach Python delegates
        # here; doing the same work later in close_plugin() is already too late.
        if event_type == QtCore.QEvent.Type.Close and is_safe(obj):
            try:
                if obj.metaObject().className() == "Alg::S4MainWindow":
                    _prepare_for_window_close()
            except Exception:
                pass
            return False

        if event_type in (QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Polish):
            if IS_APP_QUITTING or QtWidgets.QApplication.closingDown():
                return False

            if not is_safe(obj):
                return False

            try:
                if isinstance(obj, QtWidgets.QMenu) and event_type == QtCore.QEvent.Type.Show:
                    for act in obj.actions():
                        if is_safe(act):
                            raw_text = act.text()
                            clean_text = raw_text.replace("&", "").strip()
                            if clean_text in TRANSLATE_DICT:
                                target_text = TRANSLATE_DICT[clean_text]
                                if raw_text != target_text:
                                    if act.property("_cn_orig_text") is None:
                                        act.setProperty("_cn_orig_text", raw_text)
                                    act.setText(target_text)
                    return False

                translate_widget(obj)

            except Exception:
                pass

        return False


# ==========================================
# 6. 静默全界面扫描与还原
# ==========================================
def force_refresh_ui():
    if IS_APP_QUITTING or QtWidgets.QApplication.closingDown():
        return

    app = QtWidgets.QApplication.instance()
    if not is_safe(app):
        return

    try:
        for w in app.allWidgets():
            if IS_APP_QUITTING:
                break
            if is_safe(w) and w.isVisible():
                translate_widget(w)
    except Exception:
        pass


def restore_ui_translations():
    app = QtWidgets.QApplication.instance()
    if not is_safe(app):
        return

    try:
        for w in app.allWidgets():
            if not is_safe(w):
                continue

            orig_text = w.property("_cn_orig_text")
            if orig_text is not None:
                try:
                    w.setText(orig_text)
                except Exception:
                    pass
                w.setProperty("_cn_orig_text", None)

            orig_title = w.property("_cn_orig_title")
            if orig_title is not None:
                try:
                    w.setTitle(orig_title)
                except Exception:
                    pass
                w.setProperty("_cn_orig_title", None)

            orig_win_title = w.property("_cn_orig_win_title")
            if orig_win_title is not None:
                try:
                    w.setWindowTitle(orig_win_title)
                except Exception:
                    pass
                w.setProperty("_cn_orig_win_title", None)

            orig_ph = w.property("_cn_orig_ph")
            if orig_ph is not None:
                try:
                    w.setPlaceholderText(orig_ph)
                except Exception:
                    pass
                w.setProperty("_cn_orig_ph", None)

            if isinstance(w, QtWidgets.QTabBar):
                try:
                    for idx in range(w.count()):
                        orig_tab = w.property(f"_cn_orig_tab_{idx}")
                        if orig_tab is not None:
                            w.setTabText(idx, orig_tab)
                            w.setProperty(f"_cn_orig_tab_{idx}", None)
                except Exception:
                    pass

            if isinstance(w, QtWidgets.QMenu):
                try:
                    for act in w.actions():
                        if is_safe(act):
                            orig_act = act.property("_cn_orig_text")
                            if orig_act is not None:
                                act.setText(orig_act)
                                act.setProperty("_cn_orig_text", None)
                except Exception:
                    pass

    except Exception:
        pass


# ==========================================
# 7. 资源库全 View 控件 Delegate 通用挂载
# ==========================================
def _apply_asset_delegates():
    if IS_APP_QUITTING or QtWidgets.QApplication.closingDown():
        return

    app = QtWidgets.QApplication.instance()
    if not is_safe(app):
        return

    try:
        for w in app.allWidgets():
            if IS_APP_QUITTING:
                break
            if is_safe(w):
                # 排除图层面板，保护图层名称
                if is_inside_layers_panel(w):
                    continue

                if isinstance(w, QtWidgets.QAbstractItemView):
                    try:
                        meta_name = w.metaObject().className()
                    except Exception:
                        meta_name = ""

                    # Runtime diagnostics identify the right-hand asset list as
                    # Alg::ResourceListView / objectName "resources". Its model
                    # exposes core index methods as private through PySide, so
                    # install directly without probing the model.
                    if meta_name == "Alg::ResourceListView" and w.objectName() == "resources":
                        if not w.property("_cn_translation_delegate_installed"):
                            if _install_native_delegate(w):
                                w.setProperty("_cn_translation_delegate_installed", True)
                                print(">>> 已安装原生资源列表翻译 delegate: Alg::ResourceListView")
                        continue

                    # Painter's resource path tree sometimes reports a
                    # successful setData() and immediately restores its source
                    # text on the next model refresh. Identify that tree by its
                    # stable root folder names and always paint it through the
                    # native dictionary delegate.
                    if (isinstance(w, QtWidgets.QTreeView)
                            and _is_resource_folder_tree(w)):
                        if not w.property("_cn_translation_delegate_installed"):
                            if _install_native_delegate(w):
                                w.setProperty("_cn_translation_delegate_installed", True)
                                print(">>> 已安装原生资源目录树翻译 delegate")
                        continue

                    needs_delegate = _translate_view_model(w)
                    # Read-only resource folder models reject setData(). Use
                    # the crash-safe native delegate for trees that actually
                    # contain dictionary matches, while leaving unrelated
                    # Painter views and their custom delegates untouched.
                    if (needs_delegate and isinstance(w, QtWidgets.QTreeView)
                            and not w.property("_cn_translation_delegate_installed")):
                        if _install_native_delegate(w):
                            w.setProperty("_cn_translation_delegate_installed", True)
    except Exception:
        pass


def _is_resource_folder_tree(view):
    """Recognize Painter's library path tree without relying on class names."""
    # Verified in Painter 11.1.2: both the normal and filtered resource path
    # trees live below path_filter_panel and use these stable object names.
    # Structural detection avoids an expensive model walk and also works while
    # the tree is collapsed or contains hundreds of nodes before starter_assets.
    try:
        if view.objectName() in {"tree_view", "filtered_tree_view"}:
            current = view.parent()
            saw_path_panel = False
            saw_resources_view = False
            for _ in range(10):
                if current is None:
                    break
                if current.objectName() == "path_filter_panel":
                    saw_path_panel = True
                if current.metaObject().className() == "Alg::NewResourcesView":
                    saw_resources_view = True
                current = current.parent()
            if saw_path_panel and saw_resources_view:
                return True
    except Exception:
        pass

    # Fallback for future Painter versions whose object names may change.
    anchors = {
        "alphas", "colorluts", "effects", "emitters", "environments",
        "fonts", "generators", "materials", "presets", "procedurals",
        "receivers", "shaders", "smart-masks", "smart-materials", "textures",
    }
    try:
        model = view.model()
        if not is_safe(model):
            return False
        pending = [QtCore.QModelIndex()]
        found = set()
        visited = 0
        while pending and visited < 120 and len(found) < 3:
            parent = pending.pop()
            rows = min(model.rowCount(parent), 50)
            for row in range(rows):
                index = model.index(row, 0, parent)
                if not index.isValid():
                    continue
                visited += 1
                value = model.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
                if isinstance(value, str):
                    normalized = value.strip().casefold()
                    if normalized in anchors:
                        found.add(normalized)
                if model.hasChildren(index):
                    pending.append(index)
                if len(found) >= 3 or visited >= 120:
                    break
        return len(found) >= 3
    except Exception:
        return False


def _prepare_for_window_close():
    """Detach Python delegates before Painter starts destroying child widgets."""
    global IS_APP_QUITTING
    IS_APP_QUITTING = True
    try:
        if is_safe(_sp_live_timer):
            _sp_live_timer.stop()
    except Exception:
        pass

    for view, original_delegate in list(_sp_original_delegates.items()):
        try:
            if is_safe(view) and is_safe(original_delegate):
                view.setItemDelegate(original_delegate)
        except Exception:
            pass


def _translate_view_model(view):
    """Translate model display data without installing a Python delegate."""
    try:
        model = view.model()
        if not is_safe(model):
            return False

        needs_delegate = False
        pending = [QtCore.QModelIndex()]
        visited = 0
        while pending and visited < 160:
            parent = pending.pop()
            rows = min(model.rowCount(parent), 80)
            # Alg::NewResourceListModel exposes columnCount() as a private
            # method through PySide. ResourceListView is a one-column QListView,
            # so avoid calling the inaccessible virtual method.
            if isinstance(view, QtWidgets.QListView):
                columns = 1
            else:
                try:
                    columns = min(model.columnCount(parent), 3)
                except (TypeError, RuntimeError):
                    columns = 1
            for row in range(rows):
                for column in range(columns):
                    index = model.index(row, column, parent)
                    if not index.isValid():
                        continue
                    visited += 1
                    value = model.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
                    if isinstance(value, str):
                        source = value.strip()
                        target = TRANSLATE_DICT.get(source)
                        if target and target != value:
                            changed = model.setData(index, target, QtCore.Qt.ItemDataRole.DisplayRole)
                            if not changed:
                                needs_delegate = True
                    if column == 0 and model.hasChildren(index):
                        pending.append(index)
                    if visited >= 160:
                        break
                if visited >= 160:
                    break
        return needs_delegate
    except Exception:
        return False


# ==========================================
# 8. Translation label extractor UI
# ==========================================
def _load_archive_modules():
    packages_dir = os.path.join(PLUGIN_DIR, "packages")
    if packages_dir not in sys.path:
        sys.path.insert(0, packages_dir)
    pure_python_zip = os.path.join(packages_dir, "python.zip")
    if os.path.isfile(pure_python_zip) and pure_python_zip not in sys.path:
        sys.path.insert(0, pure_python_zip)
    import py7zr
    import h5py
    return py7zr, h5py


def _safe_archive_names(names):
    names = list(names)
    if len(names) > MAX_ARCHIVE_MEMBERS:
        raise ValueError(f"容器条目过多: {len(names)}")
    for name in names:
        path = pathlib.PurePosixPath(str(name).replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"资产包含不安全路径: {name}")


def _archive_entry_is_link(entry):
    value = getattr(entry, "is_symlink", False)
    return bool(value() if callable(value) else value)


def _write_json_atomic(path, payload):
    """Write UTF-8 JSON without leaving a partial destination on failure."""
    destination = os.path.abspath(path)
    directory = os.path.dirname(destination) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".sp_translation_", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _parse_asset_xml(path, attributes):
    items = set()
    selected = set(attributes)
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        content = re.sub(r"<!DOCTYPE[^>]*>", "", content)
        root = ET.fromstring(content)
        for element in root.iter():
            for attribute, raw_value in element.attrib.items():
                # One "label" option covers label, label0, label1, label2, ...
                is_selected_label = "label" in selected and re.fullmatch(r"label\d*", attribute)
                if attribute not in selected and not is_selected_label:
                    continue
                value = raw_value.strip()
                if value and not _contains_han(value):
                    items.add(value)
    except Exception:
        raise
    return items


def _contains_han(text):
    return any("\u3400" <= char <= "\u9fff" for char in str(text))


def _parse_glsl_metadata(path, attributes):
    """Extract user-facing strings from Painter GLSL JSON annotations."""
    selected = set(attributes)
    items = set()
    content = path.read_text(encoding="utf-8-sig", errors="ignore")

    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                key = str(key)
                is_label = "label" in selected and re.fullmatch(r"label\d*", key)
                if isinstance(child, str) and (key in selected or is_label):
                    clean = child.strip()
                    if clean and not _contains_han(clean):
                        items.add(clean)
                elif key == "values" and "values" in selected and isinstance(child, dict):
                    # Combobox captions are the keys; their values are shader constants.
                    items.update(
                        clean for caption in child
                        if (clean := str(caption).strip()) and not _contains_han(clean)
                    )
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    # Join the //: payloads first: Painter commonly formats one JSON annotation
    # over several comment lines. raw_decode also handles top-level arrays used
    # by the `materials` directive.
    annotation = "\n".join(
        line[line.find("//:") + 3:].strip()
        for line in content.splitlines() if "//:" in line
    )
    decoder = json.JSONDecoder()
    cursor = 0
    while cursor < len(annotation):
        starts = [position for position in (
            annotation.find("{", cursor), annotation.find("[", cursor)
        ) if position >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            value, end = decoder.raw_decode(annotation, start)
            collect(value)
            cursor = end
        except ValueError:
            cursor = start + 1

    # Also support common display-name annotations used by imported GLSL.
    if "label" in selected:
        for match in re.finditer(
            r"(?:DisplayName|displayName|ui_name)\s*\(\s*[\"']([^\"']+)[\"']\s*\)",
            content,
        ):
            clean = match.group(1).strip()
            if clean and not _contains_han(clean):
                items.add(clean)
    return items


class ChineseTranslationToolDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("中文翻译工具")
        self.setObjectName("sp_chinese_translation_tool")
        self.setMinimumSize(720, 570)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._files = []
        self._index = 0
        self._items = set()
        self._failed = []
        self._cancelled = False
        self._step_timer = QtCore.QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._process_next)
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "递归扫描所有资源文件，提取资源内部的词条。"
            "普通文件名和文件夹名可按需提取，"
            "生成可直接编辑的 *_zh.json 翻译包。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        translation_group = QtWidgets.QGroupBox("界面翻译", self)
        translation_layout = QtWidgets.QVBoxLayout(translation_group)
        self.layers_translation_check = QtWidgets.QCheckBox(
            "翻译图层面板（包括用户创建的图层名称）",
            translation_group,
        )
        self.layers_translation_check.setChecked(TRANSLATE_LAYERS_PANEL)
        self.layers_translation_check.setToolTip(
            "开启后使用图层面板专用规则翻译全部控件和图层名称；仅改变显示，不修改项目数据。"
        )
        self.layers_translation_check.toggled.connect(
            _set_layers_panel_translation
        )
        translation_layout.addWidget(self.layers_translation_check)
        layout.addWidget(translation_group)

        form = QtWidgets.QFormLayout()
        self.folder_edit = QtWidgets.QLineEdit()
        folder_row = QtWidgets.QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        self.folder_button = QtWidgets.QPushButton("浏览…", self)
        self.folder_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_button)
        form.addRow("资产目录", folder_row)

        self.output_edit = QtWidgets.QLineEdit()
        output_row = QtWidgets.QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        self.output_button = QtWidgets.QPushButton("选择…", self)
        self.output_button.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_button)
        form.addRow("输出 JSON", output_row)

        self.package_id_edit = QtWidgets.QLineEdit("extracted-assets")
        form.addRow("翻译包 ID", self.package_id_edit)
        self.description_edit = QtWidgets.QLineEdit("Extracted Substance asset labels")
        form.addRow("说明", self.description_edit)

        filename_row = QtWidgets.QHBoxLayout()
        self.filename_check = QtWidgets.QCheckBox("提取普通文件名")
        self.filename_check.setChecked(True)
        self.foldername_check = QtWidgets.QCheckBox("提取文件夹名")
        self.foldername_check.setChecked(False)
        filename_row.addWidget(self.filename_check)
        filename_row.addWidget(self.foldername_check)
        filename_row.addStretch(1)
        form.addRow("名称", filename_row)

        attribute_row = QtWidgets.QHBoxLayout()
        self.label_check = QtWidgets.QCheckBox("提取 label")
        self.label_check.setChecked(True)
        self.text_check = QtWidgets.QCheckBox("提取 text")
        self.text_check.setChecked(True)
        self.group_check = QtWidgets.QCheckBox("提取 group")
        self.group_check.setChecked(True)
        self.description_check = QtWidgets.QCheckBox("提取 description")
        self.description_check.setChecked(True)
        self.category_check = QtWidgets.QCheckBox("提取 category")
        self.category_check.setChecked(True)
        self.keywords_check = QtWidgets.QCheckBox("提取 keywords（可能影响搜索）")
        self.keywords_check.setChecked(False)
        self.values_check = QtWidgets.QCheckBox("提取下拉选项 values")
        self.values_check.setChecked(True)
        self.disabled_description_check = QtWidgets.QCheckBox(
            "提取禁用说明 description_disabled"
        )
        self.disabled_description_check.setChecked(True)
        attribute_row.addWidget(self.label_check)
        attribute_row.addWidget(self.text_check)
        attribute_row.addWidget(self.group_check)
        attribute_row.addWidget(self.description_check)
        attribute_row.addWidget(self.category_check)
        attribute_row.addWidget(self.keywords_check)
        attribute_row.addWidget(self.values_check)
        attribute_row.addWidget(self.disabled_description_check)
        attribute_row.addStretch(1)
        attribute_row.setSpacing(12)
        attribute_widget = QtWidgets.QWidget(self)
        attribute_grid = QtWidgets.QGridLayout(attribute_widget)
        attribute_grid.setContentsMargins(0, 0, 0, 0)
        while attribute_row.count():
            item = attribute_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                index = attribute_grid.count()
                attribute_grid.addWidget(widget, index // 3, index % 3)
        form.addRow("词条属性", attribute_widget)
        layout.addLayout(form)

        note = QtWidgets.QLabel(
            "新词条的译文为空字符串时插件会自动忽略空译文。若输出文件已存在，将保留其中已有译文。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status_label = QtWidgets.QLabel("就绪")
        layout.addWidget(self.status_label)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

        self.button_container = QtWidgets.QWidget(self)
        button_layout = QtWidgets.QHBoxLayout(self.button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.open_translations_button = QtWidgets.QPushButton(
            "打开插件词条目录", self.button_container
        )
        self.open_translations_button.clicked.connect(
            self._open_translations_directory
        )
        button_layout.addWidget(self.open_translations_button)
        self.export_library_button = QtWidgets.QPushButton(
            "导出资产库未翻译名称", self.button_container
        )
        self.export_library_button.setToolTip(
            "导出当前所有资产架中尚无有效中文译文的资产名称"
        )
        self.export_library_button.clicked.connect(self._export_asset_library_names)
        button_layout.addWidget(self.export_library_button)
        button_layout.addStretch(1)
        self.extract_button = QtWidgets.QPushButton("开始提取", self.button_container)
        self.cancel_button = QtWidgets.QPushButton("取消", self.button_container)
        self.close_button = QtWidgets.QPushButton("关闭", self.button_container)
        button_layout.addWidget(self.extract_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.close_button)
        self.cancel_button.setEnabled(False)
        self.extract_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.button_container)

    def _open_translations_directory(self):
        os.makedirs(TRANSLATIONS_DIR, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(os.path.normpath(TRANSLATIONS_DIR))
        )

    def _export_asset_library_names(self):
        initial = os.path.join(TRANSLATIONS_DIR, "untranslated_assets_zh.json")
        output, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出 Painter 资产库未翻译名称", initial,
            "Chinese translation package (*_zh.json)"
        )
        if not output:
            return
        if not output.lower().endswith("_zh.json"):
            output = os.path.splitext(output)[0] + "_zh.json"

        names = set()
        failures = []
        seen = set()

        def visit(resource):
            try:
                identifier = resource.identifier()
                identity = identifier.url() if hasattr(identifier, "url") else repr(identifier)
            except Exception:
                identity = repr(resource)
            if identity in seen:
                return
            seen.add(identity)
            try:
                name = resource.gui_name().strip()
                translated_name = TRANSLATE_DICT.get(name, "").strip()
                if name and not _contains_han(name) and not translated_name:
                    names.add(name)
            except Exception as exc:
                failures.append(str(exc))
            try:
                for child in resource.children():
                    visit(child)
            except Exception:
                pass

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            shelves = list(sp.resource.Shelves.all())
            for shelf_index, shelf in enumerate(shelves, 1):
                try:
                    for resource in shelf.resources():
                        visit(resource)
                except Exception as exc:
                    failures.append(f"{shelf.name()}: {exc}")
                self.status_label.setText(
                    f"正在读取资产库 {shelf_index}/{len(shelves)}，已发现 {len(names)} 个名称"
                )
                QtWidgets.QApplication.processEvents()

            existing = {}
            if os.path.isfile(output):
                try:
                    with open(output, "r", encoding="utf-8-sig") as stream:
                        old = json.load(stream)
                    if old.get("$schema") == "sp-translation-v1":
                        existing = old.get("translations", {})
                except Exception:
                    existing = {}
            translations = {
                name: existing.get(name, "") if isinstance(existing.get(name, ""), str) else ""
                for name in names
            }
            payload = {
                "$schema": "sp-translation-v1",
                "id": "painter-untranslated-assets",
                "language": "zh-CN",
                "description": "Untranslated asset names exported through the Substance 3D Painter resource API",
                "extraction": {
                    "shelf_count": len(shelves),
                    "resource_count": len(seen),
                    "term_count": len(names),
                    "failed_count": len(failures),
                },
                "translations": dict(sorted(translations.items(), key=lambda item: item[0].casefold())),
            }
            _write_json_atomic(output, payload)
            self.output_edit.setText(output)
            self.status_label.setText(f"资产库导出完成：{len(names)} 条词条")
            self.log.appendPlainText(
                f"资产库导出  {output}  [资产 {len(seen)}，词条 {len(names)}，失败 {len(failures)}]"
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "资产库导出失败", str(exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _browse_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 Substance 资产目录", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            if not self.output_edit.text().strip():
                self.output_edit.setText(os.path.join(folder, "extracted_assets_zh.json"))

    def _browse_output(self):
        initial = self.output_edit.text().strip() or "extracted_assets_zh.json"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存翻译包", initial, "Chinese translation package (*_zh.json)"
        )
        if path:
            if not path.lower().endswith("_zh.json"):
                path = os.path.splitext(path)[0] + "_zh.json"
            self.output_edit.setText(path)

    def _set_running(self, running):
        self.extract_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.folder_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        self.package_id_edit.setEnabled(not running)
        self.description_edit.setEnabled(not running)
        self.filename_check.setEnabled(not running)
        self.foldername_check.setEnabled(not running)
        self.label_check.setEnabled(not running)
        self.text_check.setEnabled(not running)
        self.group_check.setEnabled(not running)
        self.description_check.setEnabled(not running)
        self.category_check.setEnabled(not running)
        self.keywords_check.setEnabled(not running)
        self.values_check.setEnabled(not running)
        self.disabled_description_check.setEnabled(not running)
        self.folder_button.setEnabled(not running)
        self.output_button.setEnabled(not running)
        self.export_library_button.setEnabled(not running)

    def _start(self):
        folder = os.path.abspath(self.folder_edit.text().strip())
        output = os.path.abspath(self.output_edit.text().strip())
        attributes = []
        if self.label_check.isChecked():
            attributes.append("label")
        if self.text_check.isChecked():
            attributes.append("text")
        if self.group_check.isChecked():
            attributes.append("group")
        if self.description_check.isChecked():
            attributes.append("description")
        if self.category_check.isChecked():
            attributes.append("category")
        if self.keywords_check.isChecked():
            attributes.append("keywords")
        if self.values_check.isChecked():
            attributes.append("values")
        if self.disabled_description_check.isChecked():
            attributes.append("description_disabled")
        if not os.path.isdir(folder):
            QtWidgets.QMessageBox.warning(self, "无法开始", "请选择有效的资产目录。")
            return
        if not output.lower().endswith("_zh.json"):
            QtWidgets.QMessageBox.warning(self, "无法开始", "输出文件名必须以 _zh.json 结尾。")
            return
        if not self.package_id_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "无法开始", "翻译包 ID 不能为空。")
            return
        self._attributes = tuple(attributes)
        self._include_file_names = self.filename_check.isChecked()
        self._include_folder_names = self.foldername_check.isChecked()
        self._output = output
        self._source_folder = folder
        self._files = []
        output_normalized = os.path.normcase(os.path.abspath(output))
        for root, dirs, files in os.walk(folder):
            dirs[:] = [name for name in dirs if name not in {
                "_unpacked_assets", "__pycache__", ".alg_meta"
            }]
            for name in files:
                path = os.path.join(root, name)
                if os.path.normcase(os.path.abspath(path)) != output_normalized:
                    self._files.append(path)
        self._files.sort(key=str.casefold)
        if not self._files:
            QtWidgets.QMessageBox.information(
                self, "没有资源", "所选目录中没有可扫描的文件。"
            )
            return

        self._index = 0
        self._items = set()
        if self._include_folder_names:
            for root, dirs, _files in os.walk(folder):
                dirs[:] = [name for name in dirs if name not in {
                    "_unpacked_assets", "__pycache__", ".alg_meta"
                }]
                for name in dirs:
                    clean_name = name.strip()
                    if clean_name and not _contains_han(clean_name):
                        self._items.add(clean_name)
        self._failed = []
        self._cancelled = False
        self.log.clear()
        self.progress.setRange(0, len(self._files))
        self.progress.setValue(0)
        self._set_running(True)
        self.status_label.setText(f"发现 {len(self._files)} 个资产")
        self._step_timer.start(0)

    def _extract_archive(self, asset_path, destination):
        py7zr, h5py = _load_archive_modules()
        if py7zr.is_7zfile(asset_path):
            with py7zr.SevenZipFile(asset_path, mode="r") as archive:
                entries = archive.list()
                _safe_archive_names(entry.filename for entry in entries)
                if any(_archive_entry_is_link(entry) for entry in entries):
                    raise ValueError("容器包含不允许的符号链接")
                archive.extractall(path=destination)
            return "7z"
        if zipfile.is_zipfile(asset_path):
            with zipfile.ZipFile(asset_path, mode="r") as archive:
                entries = archive.infolist()
                _safe_archive_names(entry.filename for entry in entries)
                if any((entry.external_attr >> 16) & 0o170000 == 0o120000
                       for entry in entries):
                    raise ValueError("容器包含不允许的符号链接")
                archive.extractall(path=destination)
            return "zip"
        if h5py.is_hdf5(asset_path):
            with h5py.File(asset_path, mode="r") as archive:
                dataset_names = []
                archive.visititems(
                    lambda name, obj: dataset_names.append(name)
                    if isinstance(obj, h5py.Dataset) else None
                )
                _safe_archive_names(dataset_names)
                for name in dataset_names:
                    dataset = archive[name]
                    value = dataset[()]
                    if isinstance(value, bytes):
                        data = value
                    elif hasattr(value, "tobytes"):
                        data = value.tobytes()
                    else:
                        data = bytes(value)
                    output_path = pathlib.Path(destination, *pathlib.PurePosixPath(name).parts)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(data)
            return "hdf5"
        raise ValueError("不是受支持的 7z/ZIP/HDF5 容器")

    def _expand_nested_archives(self, root):
        queue = [(path, 1) for path in pathlib.Path(root).rglob("*") if path.is_file()]
        expanded = 0
        serial = 0
        while queue:
            path, depth = queue.pop(0)
            if depth > 3 or path.suffix.lower() == ".xml":
                continue
            if expanded >= MAX_NESTED_ARCHIVES:
                raise ValueError("嵌套容器超过 128 个安全上限")
            try:
                py7zr, h5py = _load_archive_modules()
                is_container = (py7zr.is_7zfile(path) or zipfile.is_zipfile(path)
                                or h5py.is_hdf5(path))
                if not is_container:
                    continue
                serial += 1
                destination = pathlib.Path(root) / f"_nested_{serial}"
                destination.mkdir(parents=True, exist_ok=True)
                self._extract_archive(path, destination)
                expanded += 1
                queue.extend((child, depth + 1) for child in destination.rglob("*")
                             if child.is_file())
            except Exception:
                continue
        return expanded

    def _process_next(self):
        if self._cancelled:
            self._finish(cancelled=True)
            return
        if self._index >= len(self._files):
            self._finish(cancelled=False)
            return

        asset_path = self._files[self._index]
        relative = os.path.relpath(asset_path, self._source_folder)
        before = len(self._items)
        self.status_label.setText(f"[{self._index + 1}/{len(self._files)}] {relative}")
        try:
            py7zr, h5py = _load_archive_modules()
            is_container = (py7zr.is_7zfile(asset_path) or zipfile.is_zipfile(asset_path)
                            or h5py.is_hdf5(asset_path))
            # Container names are always visible asset names and are therefore
            # mandatory. The option only controls ordinary file names.
            file_name = pathlib.Path(asset_path).stem.strip()
            if (file_name and not _contains_han(file_name)
                    and (is_container or self._include_file_names)):
                self._items.add(file_name)
            if is_container:
                with tempfile.TemporaryDirectory(prefix="sp_label_extract_") as temporary:
                    archive_type = self._extract_archive(asset_path, temporary)
                    nested_count = self._expand_nested_archives(temporary)
                    xml_count = 0
                    for xml_path in pathlib.Path(temporary).rglob("*.xml"):
                        xml_count += 1
                        self._items.update(_parse_asset_xml(xml_path, self._attributes))
                detail = f"{archive_type}, 嵌套包 {nested_count}, XML {xml_count}"
            else:
                suffix = pathlib.Path(asset_path).suffix.lower()
                glsl_extensions = {
                    ".glsl", ".glslfx", ".vert", ".frag", ".geom",
                    ".tesc", ".tese", ".comp",
                }
                if suffix in glsl_extensions:
                    glsl_items = _parse_glsl_metadata(
                        pathlib.Path(asset_path), self._attributes
                    )
                    self._items.update(glsl_items)
                    detail = f"GLSL 元数据 {len(glsl_items)} 条"
                else:
                    detail = f"普通文件 {suffix or '[无扩展名]'}"
            added = len(self._items) - before
            self.log.appendPlainText(
                f"成功  {relative}  [{detail}, 新增 {added}]"
            )
        except Exception as exc:
            self._failed.append((relative, str(exc)))
            self.log.appendPlainText(f"失败  {relative}  [{exc}]")

        self._index += 1
        self.progress.setValue(self._index)
        self._step_timer.start(0)

    def _load_existing_translations(self):
        if not os.path.isfile(self._output):
            return {}
        try:
            with open(self._output, "r", encoding="utf-8-sig") as stream:
                payload = json.load(stream)
            if payload.get("$schema") == "sp-translation-v1" and isinstance(payload.get("translations"), dict):
                return {key: value for key, value in payload["translations"].items()
                        if isinstance(key, str) and isinstance(value, str)}
        except Exception:
            pass
        return {}

    def _finish(self, cancelled):
        self._set_running(False)
        if cancelled:
            self.status_label.setText("已取消；没有写入输出文件")
            return

        # Chinese source strings are already localized and must never become
        # translation keys. Filtering existing output as well keeps repeated
        # extraction runs consistent with this rule.
        translations = {
            source: target
            for source, target in self._load_existing_translations().items()
            if not _contains_han(source)
        }
        self._items = {
            source for source in self._items
            if source and not _contains_han(source)
        }
        for source in self._items:
            translations.setdefault(source, "")
        payload = {
            "$schema": "sp-translation-v1",
            "id": self.package_id_edit.text().strip(),
            "language": "zh-CN",
            "description": self.description_edit.text().strip(),
            "extraction": {
                "asset_count": len(self._files),
                "failed_count": len(self._failed),
                "term_count": len(self._items),
                "attributes": list(self._attributes),
                "ordinary_filenames": self._include_file_names,
                "container_filenames": True,
                "folder_names": self._include_folder_names,
                "glsl_metadata": True,
            },
            "translations": dict(sorted(translations.items(), key=lambda item: item[0].casefold())),
        }
        try:
            _write_json_atomic(self._output, payload)
            self.status_label.setText(
                f"完成：{len(self._items)} 条词条，{len(self._failed)} 个失败"
            )
            self.log.appendPlainText(f"\n已写入: {self._output}")
        except Exception as exc:
            self.status_label.setText("写入失败")
            QtWidgets.QMessageBox.critical(self, "写入失败", str(exc))

    def _cancel(self):
        self._cancelled = True
        self.cancel_button.setEnabled(False)
        self.status_label.setText("正在取消…")

    def shutdown(self):
        self._cancelled = True
        self._step_timer.stop()


_label_extractor_dialog = None
_label_extractor_action = None
_label_extractor_menu_bar = None


def _set_layers_panel_translation(enabled):
    """Toggle C++ translation of UI controls inside Painter's Layers panel."""
    global TRANSLATE_LAYERS_PANEL
    TRANSLATE_LAYERS_PANEL = bool(enabled)
    QtCore.QSettings().setValue(
        "sp_chinese_translation/translate_layers_panel",
        TRANSLATE_LAYERS_PANEL,
    )
    dll = _load_native_delegate()
    if dll is not None:
        try:
            dll.sp_delegate_set_translate_layers(int(TRANSLATE_LAYERS_PANEL))
        except Exception as exc:
            print(">>> 切换图层面板翻译失败:", exc)


def show_translation_tool():
    global _label_extractor_dialog
    if not is_safe(_label_extractor_dialog):
        _label_extractor_dialog = ChineseTranslationToolDialog(
            sp.ui.get_main_window()
        )
    _label_extractor_dialog.show()
    _label_extractor_dialog.raise_()
    _label_extractor_dialog.activateWindow()


# ==========================================
# 9. 生命周期的启动与清理
# ==========================================
_sp_original_delegates = {}


def close_plugin():
    global _sp_original_delegates
    global IS_APP_QUITTING, IS_CLEANING, IS_TRANSLATION_ENABLED
    global _label_extractor_dialog, _label_extractor_action, _label_extractor_menu_bar

    if IS_CLEANING:
        return

    IS_CLEANING = True
    IS_APP_QUITTING = True
    IS_TRANSLATION_ENABLED = False

    if is_safe(_label_extractor_dialog):
        try:
            _label_extractor_dialog.shutdown()
            _label_extractor_dialog.close()
            delete(_label_extractor_dialog)
        except Exception:
            pass
    _label_extractor_dialog = None

    if is_safe(_label_extractor_action):
        try:
            if is_safe(_label_extractor_menu_bar):
                _label_extractor_menu_bar.removeAction(_label_extractor_action)
            delete(_label_extractor_action)
        except Exception:
            pass
    _label_extractor_action = None

    _label_extractor_menu_bar = None

    if _native_delegate is not None:
        try:
            _native_delegate.sp_delegate_set_enabled(0)
        except Exception:
            pass

    # Asset delegates intentionally remain installed and strongly referenced.
    # Painter can continue painting views after close_plugin() returns; releasing
    # them here causes the python311.dll use-after-free seen in the minidump.
    # Do not traverse or mutate Painter widgets during close_plugin(). Painter
    # can call this while native widgets are already being destroyed even when
    # QApplication.closingDown() still reports False.
    _sp_original_delegates.clear()


def _set_registered_plugin_display_name(main_window):
    """Rename this plugin's existing Painter Python-menu registration."""
    if not is_safe(main_window):
        return False
    module_name = __name__.split(".")[-1]
    menu_bar = main_window.menuBar()
    if not is_safe(menu_bar):
        return False
    for top_action in menu_bar.actions():
        menu = top_action.menu()
        if not is_safe(menu):
            continue
        for action in menu.actions():
            if action.text().replace("&", "") == module_name:
                action.setText(PLUGIN_DISPLAY_NAME)
                action.setObjectName("sp_chinese_translation_plugin_registration")
                return True
    return False


def start_plugin():
    global IS_APP_QUITTING, IS_CLEANING, IS_TRANSLATION_ENABLED
    global TRANSLATE_LAYERS_PANEL
    global _label_extractor_action, _label_extractor_menu_bar

    app = QtWidgets.QApplication.instance()
    if not is_safe(app):
        return

    startup_started = time.perf_counter()
    close_plugin()

    IS_APP_QUITTING = False
    IS_CLEANING = False
    IS_TRANSLATION_ENABLED = True
    TRANSLATE_LAYERS_PANEL = QtCore.QSettings().value(
        "sp_chinese_translation/translate_layers_panel", True, type=bool
    )

    phase_started = time.perf_counter()
    load_translation_packages()
    json_load_ms = (time.perf_counter() - phase_started) * 1000.0

    phase_started = time.perf_counter()
    native_dictionary_ok = _sync_native_dictionary()
    native_sync_ms = (time.perf_counter() - phase_started) * 1000.0

    phase_started = time.perf_counter()
    native_ui_ok = _install_native_ui(app)
    native_ui_ms = (time.perf_counter() - phase_started) * 1000.0
    if not native_dictionary_ok or not native_ui_ok:
        print(
            ">>> 原生翻译引擎未完全启用: "
            f"dictionary={native_dictionary_ok}, ui={native_ui_ok}"
        )

    main_window = sp.ui.get_main_window()
    # Painter starts this plugin while it is still populating the Python menu.
    # Renaming synchronously re-enters that construction and can invalidate
    # Painter's insertion separator, so wait until the menu build returns.
    QtCore.QTimer.singleShot(
        0, lambda window=main_window: _set_registered_plugin_display_name(window)
    )
    _label_extractor_action = QtGui.QAction("中文翻译工具", main_window)
    _label_extractor_action.setObjectName("sp_chinese_translation_tool_action")
    _label_extractor_action.triggered.connect(show_translation_tool)
    _label_extractor_menu_bar = main_window.menuBar()
    _label_extractor_menu_bar.addAction(_label_extractor_action)

    total_ms = (time.perf_counter() - startup_started) * 1000.0
    print(
        ">>> Translation plugin startup: "
        f"entries={len(TRANSLATE_DICT)}, "
        f"json={json_load_ms:.1f} ms, "
        f"native_sync={native_sync_ms:.1f} ms, "
        f"native_ui={native_ui_ms:.1f} ms, "
        f"total={total_ms:.1f} ms"
    )

    # Do not attach a module-level Python callback to aboutToQuit. Painter may
    # unload plugin modules before QApplication emits/destroys all Qt objects,
    # leaving a stale callback behind. The timer and filter are parented to the
    # application and close_plugin() is Painter's supported unload hook.

    # From this point on Python never reads, writes, or paints Painter-owned
    # controls. The native engine owns widget events, item
    # delegates, hover originals, dynamic refresh, and resource-tree painting.

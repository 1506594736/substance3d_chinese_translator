# -*- coding: utf-8 -*-
"""
Substance Painter 全控件通用 + 资源库汉化插件 (资源分类树 + 资产全覆盖版)
支持：Adobe Substance 3D Painter 7.2 至官方最新版。
新版使用 PySide6 / Qt6 C++ 显示引擎，旧版自动使用
PySide2 / Qt5 C++ 显示引擎。
"""

import collections
import ctypes
import json
import os
import pathlib
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

import substance_painter as sp
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import delete, getCppPointer, isValid
    QT_MAJOR = 6
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import delete, getCppPointer, isValid
    QT_MAJOR = 5

WA_DELETE_ON_CLOSE = (QtCore.Qt.WA_DeleteOnClose if QT_MAJOR == 5
                      else QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
WAIT_CURSOR = (QtCore.Qt.WaitCursor if QT_MAJOR == 5
               else QtCore.Qt.CursorShape.WaitCursor)
FRAME_STYLED_PANEL = (QtWidgets.QFrame.Shape.StyledPanel if QT_MAJOR >= 6
                      else QtWidgets.QFrame.StyledPanel)
WINDOW_MODAL = (QtCore.Qt.WindowModal if QT_MAJOR == 5
                else QtCore.Qt.WindowModality.WindowModal)
QAction = QtWidgets.QAction if QT_MAJOR == 5 else QtGui.QAction

IS_APP_QUITTING = False
IS_CLEANING = False
IS_TRANSLATION_ENABLED = True
TRANSLATE_LAYERS_PANEL = True
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSLATIONS_DIR = os.path.join(PLUGIN_DIR, "translations")
PACKAGES_DIR = os.path.join(PLUGIN_DIR, "packages")
NATIVE_DIR = os.path.join(PLUGIN_DIR, "native")
DELEGATE_DLL_PATH = os.path.join(
    NATIVE_DIR,
    "sp_translation_delegate_qt5.dll" if QT_MAJOR == 5
    else "sp_translation_delegate_qt6.dll",
)
PLUGIN_DISPLAY_NAME = "中文翻译补全插件"
PLUGIN_VERSION = "2.0.1"
PLUGIN_REPO = "iillya/sp_chinese_translation"
PLUGIN_RELEASE_URL = (
    f"https://api.github.com/repos/{PLUGIN_REPO}/releases/latest"
)
PLUGIN_ASSET_NAME = "sp_chinese_translation.zip"
MAX_ARCHIVE_MEMBERS = 50_000
MAX_NESTED_ARCHIVES = 128
MAX_EXTRACT_BYTES = 8 * 1024 * 1024 * 1024  # 8 GiB per container

def _read_bool_setting(key, default):
    """Read a boolean without PySide2's unreliable ``type=bool`` overload."""
    try:
        value = QtCore.QSettings().value(key, default)
    except (Exception, SystemError):
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    return bool(default)


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


# ==========================================
# 2. JSON translation packages
# ==========================================
TRANSLATE_DICT = {}
TRANSLATE_SOURCE_FILES = {}
CONTROL_TRANSLATE_DICTS = {}


def load_translation_packages():
    """Merge every UTF-8 ``*_zh.json`` package beside this plugin.

    A package can contain root-level ``translations`` and/or a
    ``control_types`` object whose entries each own a ``translations`` object.
    Files load alphabetically; a later package intentionally overrides
    duplicate strings within the same scope.
    """
    TRANSLATE_DICT.clear()
    TRANSLATE_SOURCE_FILES.clear()
    CONTROL_TRANSLATE_DICTS.clear()
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
            control_types = payload.get("control_types", {})
            if not isinstance(control_types, dict):
                raise ValueError("control_types must be a JSON object")
            entries = payload.get("translations", {})
            if not isinstance(entries, dict):
                raise ValueError("translations must be a JSON object")
            if not entries and not control_types:
                raise ValueError("package must contain translations or control_types")
            loaded = 0
            for source, target in entries.items():
                if isinstance(source, str) and isinstance(target, str) and source and target:
                    TRANSLATE_DICT[source] = target
                    TRANSLATE_SOURCE_FILES[source] = path
                    loaded += 1
            for control_type, section in control_types.items():
                if not isinstance(control_type, str) or not control_type.strip():
                    raise ValueError("control type names must be non-empty strings")
                if not isinstance(section, dict):
                    raise ValueError(f"control type {control_type!r} must be an object")
                scoped_entries = section.get("translations")
                if not isinstance(scoped_entries, dict):
                    raise ValueError(
                        f"control type {control_type!r} translations must be an object"
                    )
                destination = CONTROL_TRANSLATE_DICTS.setdefault(
                    control_type.strip(), {}
                )
                for source, target in scoped_entries.items():
                    if (isinstance(source, str) and isinstance(target, str)
                            and source and target):
                        destination[source] = target
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
        dll.sp_delegate_add_control_translation.argtypes = [
            ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p
        ]
        dll.sp_delegate_add_control_translation.restype = None
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
        if api_version != 9:
            print(f">>> 原生翻译模块 API 不兼容: 需要 9，实际 {api_version}")
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
        for control_type, entries in CONTROL_TRANSLATE_DICTS.items():
            for source, target in entries.items():
                dll.sp_delegate_add_control_translation(
                    control_type, source, target
                )
                source_path = TRANSLATE_SOURCE_FILES.get(source)
                if source_path:
                    dll.sp_delegate_set_translation_path(source, source_path)
        dll.sp_delegate_set_enabled(int(IS_TRANSLATION_ENABLED))
        return True
    except Exception as exc:
        print(">>> 原生资源翻译字典同步失败:", exc)
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
# 3. Translation label extractor UI
# ==========================================
_ARCHIVE_MODULES = None


def _load_archive_modules():
    global _ARCHIVE_MODULES
    if _ARCHIVE_MODULES is not None:
        return _ARCHIVE_MODULES
    packages_dir = os.path.join(PLUGIN_DIR, "packages")
    if packages_dir not in sys.path:
        sys.path.insert(0, packages_dir)
    pure_python_zip = os.path.join(packages_dir, "python.zip")
    if os.path.isfile(pure_python_zip) and pure_python_zip not in sys.path:
        sys.path.insert(0, pure_python_zip)
    try:
        import py7zr
    except Exception:
        py7zr = None
    if py7zr is not None:
        try:
            # 路径安全已由 _safe_archive_names 把关。py7zr 的 resolve() 路径
            # 校验在 Painter 运行时会对个别文件误判（Bad7zFile:
            # "Specified path is bad"），这里放行 resolve 比较、保留 .. 检查。
            import py7zr.helpers as _py7zr_helpers
            if not getattr(_py7zr_helpers, "_sp_lenient_path_check", False):
                _py7zr_helpers.is_relative_to = (
                    lambda *args, **kwargs: True
                )
                _py7zr_helpers._sp_lenient_path_check = True
        except Exception:
            pass
    try:
        import h5py
    except Exception:
        h5py = None
    _ARCHIVE_MODULES = (py7zr, h5py)
    return _ARCHIVE_MODULES


def _is_supported_container(path, py7zr, h5py):
    """Probe formats without requiring version-specific binary modules."""
    return ((py7zr is not None and py7zr.is_7zfile(path))
            or zipfile.is_zipfile(path)
            or (h5py is not None and h5py.is_hdf5(path)))


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


def _parse_len_prefixed_strings(data):
    """解析 Alg 序列化中常见的“4 字节长度 + UTF-8”字符串序列。"""
    items = []
    index = 0
    size = len(data)
    while index + 4 <= size:
        length = struct.unpack_from("<I", data, index)[0]
        if 0 < length < 500 and index + 4 + length <= size:
            try:
                text = data[index + 4:index + 4 + length].decode("utf-8")
                if text and all(char.isprintable() or char in "\r\n\t"
                                for char in text):
                    items.append(text)
                    index += 4 + length
                    continue
            except Exception:
                pass
        index += 1
    return items


def _parse_spsm_layer_names(path):
    """从 .spsm（HDF5 智能材质）的 preset.bin 中解析需要翻译的图层名。

    Painter 把智能材质的图层结构序列化在 preset.bin 里，图层名以
    “4 字节长度 + UTF-8”字符串存放。字段名通常重复出现。图层名一般唯一，
    且多为“含空格”或“标题式单词”。已含中文的图层名无需翻译，跳过。
    """
    items = set()
    try:
        _py7zr, h5py = _load_archive_modules()
        if h5py is None or not h5py.is_hdf5(path):
            return items
        with h5py.File(path, "r") as archive:
            if "preset.bin" not in archive:
                return items
            try:
                raw = bytes(archive["preset.bin"][()])
            except Exception:
                return items
        strings = _parse_len_prefixed_strings(raw)
        counts = collections.Counter(strings)
        for text in strings:
            if counts[text] != 1:
                continue  # 字段名通常重复出现，排除
            text = text.strip()
            if len(text) < 2 or len(text) > 80:
                continue
            if text.startswith(("Data", "GUI")) or "://" in text:
                continue
            if _contains_han(text):
                continue  # 已是中文，无需翻译
            if " " in text or re.fullmatch(r"[A-Z][A-Za-z]+", text):
                items.add(text)
    except Exception:
        pass
    return items


def _parse_glsl_metadata(path, attributes):
    """Extract user-facing strings from Painter GLSL JSON annotations."""
    selected = set(attributes)
    items = set()
    content = path.read_text(encoding="utf-8-sig", errors="ignore")

    def collect(value, depth=0):
        if depth > 64:
            return
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
                    for caption in child:
                        clean = str(caption).strip()
                        if clean and not _contains_han(clean):
                            items.add(clean)
                else:
                    collect(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                collect(child, depth + 1)

    # Join the //: payloads first: Painter commonly formats one JSON annotation
    # over several comment lines. raw_decode also handles top-level arrays used
    # by the `materials` directive.
    annotation = "\n".join(
        line[line.find("//:") + 3:].strip()
        for line in content.splitlines() if "//:" in line
    )
    # Bound the amount of annotation text parsed in one pass; a malformed or
    # oversized GLSL file must not stall extraction for minutes.
    if len(annotation) <= 4 * 1024 * 1024:
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
        self.setWindowTitle(f"中文翻译工具 v{PLUGIN_VERSION}")
        self.setObjectName("sp_chinese_translation_tool")
        self.setMinimumSize(780, 640)
        self.setSizeGripEnabled(True)
        self.setAttribute(WA_DELETE_ON_CLOSE, False)
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

        translation_group = QtWidgets.QFrame(self)
        translation_group.setFrameShape(FRAME_STYLED_PANEL)
        translation_layout = QtWidgets.QVBoxLayout(translation_group)
        translation_header = QtWidgets.QHBoxLayout()
        translation_title = QtWidgets.QLabel(
            "界面翻译（即时生效）", translation_group
        )
        title_font = translation_title.font()
        title_font.setBold(True)
        translation_title.setFont(title_font)
        translation_header.addWidget(translation_title)
        translation_header.addStretch(1)
        self.update_button = QtWidgets.QPushButton(
            "检查插件更新", translation_group
        )
        self.update_button.setToolTip(
            "从 GitHub 检查最新版本。发现新版本时可下载安装包。"
        )
        self.update_button.clicked.connect(
            lambda: _check_updates(self)
        )
        translation_header.addWidget(self.update_button)
        translation_layout.addLayout(translation_header)
        self.translation_enabled_check = QtWidgets.QCheckBox(
            "启用插件翻译（翻译 SP 界面）",
            translation_group,
        )
        self.translation_enabled_check.setChecked(IS_TRANSLATION_ENABLED)
        self.translation_enabled_check.setToolTip(
            "勾选时插件翻译生效，自动翻译 Substance 3D Painter 的界面控件。"
            "取消勾选时停止翻译并立即恢复所有界面原文显示。"
            "仅影响显示，不修改项目数据。"
        )
        self.translation_enabled_check.toggled.connect(
            _set_translation_enabled
        )
        translation_layout.addWidget(self.translation_enabled_check)

        self.layers_translation_check = QtWidgets.QCheckBox(
            "翻译图层面板（包括用户创建的图层名称）",
            translation_group,
        )
        self.layers_translation_check.setChecked(TRANSLATE_LAYERS_PANEL)
        self.layers_translation_check.setToolTip(
            "开启后使用图层面板专用规则翻译全部控件和图层名称。仅改变显示，不修改项目数据。"
        )
        self.layers_translation_check.toggled.connect(
            _set_layers_panel_translation
        )
        translation_layout.addWidget(self.layers_translation_check)
        translation_hint = QtWidgets.QLabel(
            "提示：取消勾选“启用插件翻译”后，整个界面立即恢复英文原文。"
            "仅关闭“翻译图层面板”则只恢复图层面板中的原文。",
            translation_group,
        )
        translation_hint.setWordWrap(True)
        translation_hint.setStyleSheet("color: gray;")
        translation_layout.addWidget(translation_hint)
        layout.addWidget(translation_group)
        self._update_translation_controls()

        extract_group = QtWidgets.QGroupBox("提取设置", self)
        form = QtWidgets.QFormLayout(extract_group)
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
        layout.addWidget(extract_group)

        options_group = QtWidgets.QGroupBox("提取选项", self)
        options_form = QtWidgets.QFormLayout(options_group)
        filename_row = QtWidgets.QHBoxLayout()
        self.filename_check = QtWidgets.QCheckBox("提取普通文件名")
        self.filename_check.setChecked(True)
        self.foldername_check = QtWidgets.QCheckBox("提取文件夹名")
        self.foldername_check.setChecked(False)
        filename_row.addWidget(self.filename_check)
        filename_row.addWidget(self.foldername_check)
        filename_row.addStretch(1)
        options_form.addRow("名称", filename_row)

        attribute_row = QtWidgets.QHBoxLayout()
        self.label_check = QtWidgets.QCheckBox("提取 label")
        self.label_check.setChecked(True)
        self.text_check = QtWidgets.QCheckBox("提取 text")
        self.text_check.setChecked(True)
        self.group_check = QtWidgets.QCheckBox("提取 group")
        self.group_check.setChecked(True)
        self.description_check = QtWidgets.QCheckBox("提取 description")
        self.description_check.setChecked(False)
        self.category_check = QtWidgets.QCheckBox("提取 category")
        self.category_check.setChecked(True)
        self.keywords_check = QtWidgets.QCheckBox("提取 keywords（可能影响搜索）")
        self.keywords_check.setChecked(False)
        self.values_check = QtWidgets.QCheckBox("提取下拉选项 values")
        self.values_check.setChecked(True)
        self.disabled_description_check = QtWidgets.QCheckBox(
            "提取禁用说明 description_disabled"
        )
        self.disabled_description_check.setChecked(False)
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
        options_form.addRow("词条属性", attribute_widget)
        layout.addWidget(options_group)

        note = QtWidgets.QLabel(
            "递归扫描所有资源文件，提取资源内部的词条，普通文件名和文件夹名可按需提取。\n"
            "自动生成可直接编辑的 *_zh.json 字典，"
            "若输出的字典文件已存在，将保留其中已有译文。"
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
        self.log.setMaximumBlockCount(5000)
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

    def _update_translation_controls(self):
        """按总开关状态联动图层翻译子控件是否可用。"""
        master_on = self.translation_enabled_check.isChecked()
        self.layers_translation_check.setEnabled(master_on)

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

        def resource_name(resource, identifier):
            """Read the display name across Painter's old and new APIs."""
            gui_name = getattr(resource, "gui_name", None)
            if callable(gui_name):
                value = gui_name()
                if isinstance(value, str) and value.strip():
                    return value.strip()
            # Painter 7.x Resource only exposes ResourceID.name. In that API
            # Shelf.resources() is already flat, so this is the asset caption
            # used by the Assets window.
            value = getattr(identifier, "name", "")
            if callable(value):
                value = value()
            return value.strip() if isinstance(value, str) else ""

        def visit(resource):
            identifier = None
            try:
                identifier = resource.identifier()
                identity = identifier.url() if hasattr(identifier, "url") else repr(identifier)
            except Exception:
                identity = repr(resource)
            if identity in seen:
                return
            seen.add(identity)
            try:
                name = resource_name(resource, identifier)
                translated_name = TRANSLATE_DICT.get(name, "").strip()
                if name and not _contains_han(name) and not translated_name:
                    names.add(name)
            except Exception as exc:
                failures.append(str(exc))
            children = getattr(resource, "children", None)
            if callable(children):
                try:
                    for child in children():
                        visit(child)
                except Exception as exc:
                    failures.append(str(exc))

        QtWidgets.QApplication.setOverrideCursor(WAIT_CURSOR)
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
        if py7zr is not None and py7zr.is_7zfile(asset_path):
            with py7zr.SevenZipFile(asset_path, mode="r") as archive:
                entries = archive.list()
                _safe_archive_names(entry.filename for entry in entries)
                if any(_archive_entry_is_link(entry) for entry in entries):
                    raise ValueError("容器包含不允许的符号链接")
                total_bytes = sum(
                    int(getattr(entry, "uncompressed", 0) or 0)
                    for entry in entries
                )
                if total_bytes > MAX_EXTRACT_BYTES:
                    raise ValueError(
                        f"容器解压后体积过大（{total_bytes / 2**30:.1f} GiB）"
                    )
                archive.extractall(path=destination)
            return "7z"
        if zipfile.is_zipfile(asset_path):
            with zipfile.ZipFile(asset_path, mode="r") as archive:
                entries = archive.infolist()
                _safe_archive_names(entry.filename for entry in entries)
                if any((entry.external_attr >> 16) & 0o170000 == 0o120000
                       for entry in entries):
                    raise ValueError("容器包含不允许的符号链接")
                total_bytes = sum(entry.file_size for entry in entries)
                if total_bytes > MAX_EXTRACT_BYTES:
                    raise ValueError(
                        f"容器解压后体积过大（{total_bytes / 2**30:.1f} GiB）"
                    )
                archive.extractall(path=destination)
            return "zip"
        if h5py is not None and h5py.is_hdf5(asset_path):
            with h5py.File(asset_path, mode="r") as archive:
                dataset_names = []
                total_bytes = 0

                def _record_dataset(name, obj):
                    nonlocal total_bytes
                    if isinstance(obj, h5py.Dataset):
                        dataset_names.append(name)
                        try:
                            total_bytes += int(obj.size) * int(obj.dtype.itemsize)
                        except Exception:
                            pass

                archive.visititems(
                    _record_dataset
                )
                _safe_archive_names(dataset_names)
                if total_bytes > MAX_EXTRACT_BYTES:
                    raise ValueError(
                        f"容器解压后体积过大（{total_bytes / 2**30:.1f} GiB）"
                    )
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
        queue = []
        for path in pathlib.Path(root).rglob("*"):
            try:
                if path.is_file():
                    queue.append((path, 1))
            except Exception:
                continue
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
                is_container = _is_supported_container(path, py7zr, h5py)
                if not is_container:
                    continue
                serial += 1
                destination = pathlib.Path(root) / f"_nested_{serial}"
                destination.mkdir(parents=True, exist_ok=True)
                self._extract_archive(path, destination)
                expanded += 1
                try:
                    children = [child for child in destination.rglob("*")
                                if child.is_file()]
                except Exception:
                    children = []
                queue.extend((child, depth + 1) for child in children)
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
            is_container = _is_supported_container(asset_path, py7zr, h5py)
            # Container names are always visible asset names and are therefore
            # mandatory. The option only controls ordinary file names.
            suffix = pathlib.Path(asset_path).suffix.lower()
            known_container_name = suffix in {
                ".sbsar", ".spsm", ".spp", ".sbsprs", ".sbsasm",
                ".zip", ".7z",
            }
            file_name = pathlib.Path(asset_path).stem.strip()
            if (file_name and not _contains_han(file_name)
                    and (is_container or known_container_name
                         or self._include_file_names)):
                self._items.add(file_name)
            if is_container:
                layer_names = set()
                with tempfile.TemporaryDirectory(prefix="sp_label_extract_") as temporary:
                    archive_type = self._extract_archive(asset_path, temporary)
                    nested_count = self._expand_nested_archives(temporary)
                    xml_count = 0
                    for xml_path in pathlib.Path(temporary).rglob("*.xml"):
                        xml_count += 1
                        try:
                            self._items.update(
                                _parse_asset_xml(xml_path, self._attributes)
                            )
                        except Exception as sub_exc:
                            try:
                                sub = str(xml_path.relative_to(temporary))
                            except Exception:
                                sub = str(xml_path)
                            self._failed.append(
                                (f"{relative} :: {sub}", str(sub_exc),
                                 traceback.format_exc())
                            )
                    if archive_type == "hdf5":
                        layer_names = _parse_spsm_layer_names(asset_path)
                        self._items.update(layer_names)
                detail = (f"{archive_type}, 嵌套包 {nested_count}, "
                          f"XML {xml_count}, 图层名 {len(layer_names)}")
            else:
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
            self._failed.append(
                (relative, str(exc), traceback.format_exc())
            )
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
            self.status_label.setText("已取消，没有写入输出文件。")
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
            failure_log = ""
            if self._failed:
                failure_log = os.path.splitext(self._output)[0] + "_failures.txt"
                try:
                    with open(failure_log, "w", encoding="utf-8") as stream:
                        for item in self._failed:
                            if len(item) >= 3:
                                relative, error, trace = item
                                stream.write(
                                    f"{relative}\t{error}\n{trace}\n\n"
                                )
                            else:
                                relative, error = item
                                stream.write(f"{relative}\t{error}\n")
                except Exception as exc:
                    failure_log = ""
                    print(">>> 写失败日志出错:", exc)
            self.status_label.setText(
                f"完成：{len(self._items)} 条词条，{len(self._failed)} 个失败"
            )
            self.log.appendPlainText(f"\n已写入: {self._output}")
            if failure_log:
                self.log.appendPlainText(f"失败日志: {failure_log}")
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


def _set_translation_enabled(enabled):
    """Toggle the whole translation engine on/off.

    Unchecking the master switch stops translation and restores every
    translated widget in the interface back to its original text.
    """
    global IS_TRANSLATION_ENABLED
    IS_TRANSLATION_ENABLED = bool(enabled)
    QtCore.QSettings().setValue(
        "sp_chinese_translation/enabled", IS_TRANSLATION_ENABLED
    )
    dll = _load_native_delegate()
    if dll is not None:
        try:
            dll.sp_delegate_set_enabled(int(IS_TRANSLATION_ENABLED))
        except Exception as exc:
            print(">>> 切换插件翻译总开关失败:", exc)
    if is_safe(_label_extractor_dialog):
        try:
            _label_extractor_dialog._update_translation_controls()
        except Exception:
            pass


def _version_tuple(version):
    """Normalize ``v2.0.0`` / ``2.0`` / ``2.0.0-rc1`` to (major, minor, patch)."""
    text = str(version).strip().lstrip("vV")
    parts = []
    for part in re.split(r"[._-]", text):
        digits = re.match(r"\d+", part)
        if not digits:
            break
        parts.append(int(digits.group()))
        if len(parts) >= 3:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _http_get_json(url, timeout=15):
    request = urllib.request.Request(
        url, headers={"User-Agent": "sp_chinese_translation-updater"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _latest_release_info():
    """Query the GitHub Releases API for the newest official release."""
    data = _http_get_json(PLUGIN_RELEASE_URL)
    tag = (data.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("GitHub 返回的发布信息缺少版本号。")
    version = tag.lstrip("vV")
    download_url = ""
    for asset in data.get("assets") or []:
        if asset.get("name") == PLUGIN_ASSET_NAME:
            download_url = asset.get("browser_download_url") or ""
            break
    if not download_url:
        # Accept versioned names such as sp_chinese_translation_2.0.1.zip.
        for asset in data.get("assets") or []:
            name = (asset.get("name") or "").strip()
            lowered = name.casefold()
            if lowered.startswith("sp_chinese_translation") and lowered.endswith(
                ".zip"
            ):
                download_url = asset.get("browser_download_url") or ""
                break
    if not download_url:
        raise RuntimeError(
            f"最新发布 {tag} 中没有找到 {PLUGIN_ASSET_NAME} 安装包"
            "（支持 sp_chinese_translation.zip 或 sp_chinese_translation_版本.zip）。"
        )
    notes = data.get("body") or ""
    return version, download_url, notes

class _DownloadCancelled(Exception):
    pass


class _DownloadProgressDialog(QtWidgets.QDialog):
    """Modal download progress dialog with a cancel button.

    Built from plain widgets instead of QProgressDialog so the label, the
    progress bar and the cancel button always render inside Painter's dark
    theme.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载更新")
        self.setWindowModality(WINDOW_MODAL)
        self.setMinimumWidth(420)
        self.setMinimumHeight(140)
        layout = QtWidgets.QVBoxLayout(self)
        self._label = QtWidgets.QLabel("正在下载更新…", self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        self._bar = QtWidgets.QProgressBar(self)
        self._bar.setRange(0, 0)
        layout.addWidget(self._bar)
        self._cancel_button = QtWidgets.QPushButton("取消", self)
        self._cancel_button.setAutoDefault(False)
        align_right = (
            QtCore.Qt.AlignmentFlag.AlignRight
            if QT_MAJOR >= 6
            else QtCore.Qt.AlignRight
        )
        layout.addWidget(self._cancel_button, alignment=align_right)
        self._cancelled = False
        self._cancel_button.clicked.connect(self._request_cancel)

    def _request_cancel(self):
        self._cancelled = True
        self._cancel_button.setEnabled(False)
        self._label.setText("正在取消…")

    def reject(self):
        self._cancelled = True
        super().reject()

    def set_progress(self, downloaded, total):
        if total > 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(int(downloaded * 100.0 / total))
            self._label.setText(
                f"正在下载更新… "
                f"{downloaded // (1024 * 1024)} MB / "
                f"{total // (1024 * 1024)} MB"
            )
        else:
            self._bar.setRange(0, 0)

    def set_finished(self):
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._label.setText("下载完成")

    def is_cancelled(self):
        return self._cancelled


def _download_update(url, destination, progress=None, is_cancelled=None):
    """Download the release ZIP and verify it is a complete plug-in package.

    ``progress(downloaded_bytes, total_bytes)`` is invoked as data arrives;
    ``is_cancelled()`` is polled between chunks and may raise a
    ``_DownloadCancelled`` error through the download loop.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": "sp_chinese_translation-updater"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        try:
            total_bytes = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total_bytes = 0
        with open(destination, "wb") as stream:
            downloaded = 0
            while True:
                if is_cancelled is not None and is_cancelled():
                    raise _DownloadCancelled("下载已取消")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total_bytes)
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        required = {
            "__init__.py",
            "translations/official_assets_zh.json",
        }
        missing = required.difference(names)
        if missing:
            raise RuntimeError(
                f"下载的发布包缺少必要文件: {sorted(missing)}"
            )
    return destination


def _check_updates(parent=None):
    """Check GitHub for a newer release and download it when available."""
    if parent is None:
        parent = QtWidgets.QApplication.activeWindow()
    try:
        QtWidgets.QApplication.setOverrideCursor(WAIT_CURSOR)
        try:
            version, download_url, notes = _latest_release_info()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if _version_tuple(version) <= _version_tuple(PLUGIN_VERSION):
            QtWidgets.QMessageBox.information(
                parent,
                "检查更新",
                f"当前已是最新版本（{PLUGIN_VERSION}）。",
            )
            return
        preview = "\n".join(
            line for line in notes.splitlines() if line.strip()
        )[:300]
        message = (
            f"发现新版本 {version}（当前 {PLUGIN_VERSION}）。"
            + (f"\n\n更新说明：\n{preview}" if preview else "")
            + "\n\n是否下载安装包？"
        )
        result = QtWidgets.QMessageBox.question(
            parent,
            "发现新版本",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if result != QtWidgets.QMessageBox.Yes:
            return

        destination = os.path.join(
            os.path.dirname(PLUGIN_DIR),
            f"sp_chinese_translation_{version}.zip",
        )
        progress_dialog = _DownloadProgressDialog(parent)
        cancel_event = threading.Event()
        state = {"downloaded": 0, "total": 0, "done": False, "error": None}

        def _download_worker():
            try:
                _download_update(
                    download_url,
                    destination,
                    lambda downloaded, total: state.update(
                        downloaded=downloaded, total=total
                    ),
                    cancel_event.is_set,
                )
                state["done"] = True
            except _DownloadCancelled:
                state["done"] = True
                state["error"] = "cancelled"
            except Exception as exc:
                state["done"] = True
                state["error"] = str(exc)

        def _on_cancel():
            cancel_event.set()

        progress_dialog._cancel_button.clicked.connect(_on_cancel)

        worker = threading.Thread(target=_download_worker, daemon=True)
        worker.start()

        def _tick():
            if cancel_event.is_set() or progress_dialog.is_cancelled():
                progress_dialog.reject()
                return
            if state["done"]:
                progress_dialog.set_finished()
                progress_dialog.accept()
                return
            progress_dialog.set_progress(
                state["downloaded"], state["total"]
            )
            QtCore.QTimer.singleShot(100, _tick)

        # The modal event loop renders the dialog (layout is activated before
        # the first paint) while the timer keeps the bar in sync with the
        # background download thread.
        QtCore.QTimer.singleShot(0, _tick)
        progress_dialog.exec_()

        cancelled = (
            cancel_event.is_set() or progress_dialog.is_cancelled()
        )
        if cancelled:
            cancel_event.set()
            worker.join(timeout=5)
            try:
                os.remove(destination)
            except OSError:
                pass
            return
        worker.join(timeout=5)
        error = state.get("error")
        if error:
            raise RuntimeError(error)
        # Apply the package in place without closing Painter, then ask the
        # user to restart so the new files (and native DLL) are loaded.
        _apply_update_now(destination, parent)
    except Exception as exc:
        QtWidgets.QMessageBox.warning(
            parent,
            "检查更新失败",
            f"无法获取最新版本：\n{exc}\n\n"
            "请确认网络可访问 GitHub，稍后再试。",
        )


def _copy_file_safely(source, target):
    """Copy ``source`` to ``target``, working around a locked native DLL.

    A DLL mapped into Painter cannot be overwritten, but Windows allows it to
    be renamed, so the old file is moved aside and the new one is written
    under the original name. The running session keeps using the old image in
    memory; the new file is loaded at the next start.
    """
    try:
        shutil.copy2(source, target)
        return
    except PermissionError:
        if not target.lower().endswith(".dll"):
            raise
        moved = target + ".old"
        if os.path.isfile(moved):
            try:
                os.remove(moved)
            except OSError:
                pass
        os.rename(target, moved)
        shutil.copy2(source, target)


def _copytree_merge(source, target):
    """Copy a directory tree into a possibly existing target directory."""
    if not os.path.isdir(target):
        shutil.copytree(source, target)
        return
    for name in os.listdir(source):
        src = os.path.join(source, name)
        dst = os.path.join(target, name)
        if os.path.isdir(src) and not os.path.islink(src):
            _copytree_merge(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _copy_file_safely(src, dst)


def _cleanup_pending_dll_files():
    """Remove native DLLs renamed aside by a previous live update."""
    try:
        if not os.path.isdir(NATIVE_DIR):
            return
        for name in os.listdir(NATIVE_DIR):
            if name.lower().endswith(".dll.old"):
                try:
                    os.remove(os.path.join(NATIVE_DIR, name))
                except OSError:
                    pass
    except Exception:
        pass


def _apply_update_now(zip_path, parent=None):
    """Apply a downloaded release package in place, without closing Painter.

    The old plug-in directory is backed up, every file shipped by the new
    package is copied over it (a loaded native DLL is renamed aside first),
    and the user's own translation JSON files are preserved. Painter is left
    running; the new code and DLL only take effect after a restart.
    """
    if not os.path.isfile(zip_path):
        QtWidgets.QMessageBox.warning(
            parent,
            "无法自动更新",
            f"找不到已下载的更新包：\n{zip_path}\n请重新下载。",
        )
        return False

    backup_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
        "SPChineseTranslationBackup",
    )
    stage_dir = None
    preserve_dir = None
    QtWidgets.QApplication.setOverrideCursor(WAIT_CURSOR)
    try:
        stage_dir = tempfile.mkdtemp(prefix="sp_update_stage_")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(stage_dir)
        if not os.path.isfile(os.path.join(stage_dir, "__init__.py")):
            raise RuntimeError("更新包缺少 __init__.py，已中止更新。")

        if os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.copytree(PLUGIN_DIR, backup_dir)

        # Preserve the user's own translation JSON files.
        preserve_dir = tempfile.mkdtemp(prefix="sp_update_preserve_")
        old_translations = os.path.join(PLUGIN_DIR, "translations")
        if os.path.isdir(old_translations):
            for name in os.listdir(old_translations):
                if name.lower().endswith(".json"):
                    shutil.copy2(
                        os.path.join(old_translations, name),
                        os.path.join(preserve_dir, name),
                    )

        # Collect the file list shipped by the new package.
        new_files = set()
        for root, _dirs, files in os.walk(stage_dir):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), stage_dir)
                new_files.add(rel.replace(os.sep, "/"))

        # Replace every shipped file, tolerating the loaded native DLL.
        for rel in sorted(new_files):
            src = os.path.join(stage_dir, rel.replace("/", os.sep))
            target = os.path.join(PLUGIN_DIR, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _copy_file_safely(src, target)

        # Remove stale files that no longer exist in the package, except for
        # the user's translation JSON files that are restored below.
        stale = []
        for root, _dirs, files in os.walk(PLUGIN_DIR):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), PLUGIN_DIR)
                rel_norm = rel.replace(os.sep, "/")
                if rel_norm in new_files:
                    continue
                if (
                    rel_norm.startswith("translations/")
                    and name.lower().endswith(".json")
                ):
                    continue
                stale.append((root, name))
        for root, name in stale:
            try:
                os.remove(os.path.join(root, name))
            except PermissionError:
                if not name.lower().endswith(".dll.old"):
                    raise
            except OSError:
                pass

        # Restore user JSON files that the new package does not ship itself.
        new_translations = os.path.join(PLUGIN_DIR, "translations")
        os.makedirs(new_translations, exist_ok=True)
        for name in os.listdir(preserve_dir):
            target = os.path.join(new_translations, name)
            if not os.path.isfile(target):
                shutil.copy2(os.path.join(preserve_dir, name), target)

        if not os.path.isfile(os.path.join(PLUGIN_DIR, "__init__.py")):
            raise RuntimeError("替换后插件目录缺少 __init__.py。")

        result_file = os.path.join(tempfile.gettempdir(), "sp_update_result.txt")
        try:
            with open(result_file, "w", encoding="utf-8") as stream:
                stream.write("true\n更新已应用，本次启动已加载新版本。")
        except OSError:
            pass

        # The package has been applied; do not leave the downloaded ZIP
        # behind in the plug-ins folder. On failure it is kept for retry.
        try:
            os.remove(zip_path)
        except OSError:
            pass

        # Restore the normal cursor before showing the dialog so the mouse
        # does not keep spinning while the message is on screen.
        QtWidgets.QApplication.restoreOverrideCursor()
        QtWidgets.QMessageBox.information(
            parent,
            "更新已应用",
            "新版本文件已写入插件目录。\n\n"
            "请重启 Substance 3D Painter 以启用新版本。\n"
            "当前会话继续使用旧版本，不会自动关闭。",
        )
        return True
    except Exception as exc:
        # Roll back to the backup so a failed update never leaves a broken
        # plug-in directory.
        try:
            if os.path.isdir(backup_dir) and os.path.isfile(
                os.path.join(backup_dir, "__init__.py")
            ):
                for name in os.listdir(PLUGIN_DIR):
                    path = os.path.join(PLUGIN_DIR, name)
                    try:
                        if os.path.isdir(path) and not os.path.islink(path):
                            shutil.rmtree(path, ignore_errors=True)
                        else:
                            os.remove(path)
                    except OSError:
                        pass
                _copytree_merge(backup_dir, PLUGIN_DIR)
        except Exception:
            pass
        QtWidgets.QApplication.restoreOverrideCursor()
        QtWidgets.QMessageBox.warning(
            parent,
            "更新失败",
            f"应用更新失败：\n{exc}\n\n插件目录已保持/恢复为原版本。",
        )
        return False
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
        for path in (stage_dir, preserve_dir):
            if path and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)


def _cleanup_update_remnants():
    """Remove backups and temporary leftovers of a completed update."""
    local_app_data = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    for name in ("SPChineseTranslationBackup", "SPChineseTranslationUpdate"):
        path = os.path.join(local_app_data, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    temp_dir = tempfile.gettempdir()
    for name in ("sp_apply_update.ps1", "sp_update_result.txt"):
        try:
            os.remove(os.path.join(temp_dir, name))
        except OSError:
            pass
    try:
        for name in os.listdir(temp_dir):
            if name.startswith("sp_update_stage") or name.startswith(
                "sp_update_preserve"
            ):
                path = os.path.join(temp_dir, name)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def _notify_update_result(main_window):
    """Show the outcome of a background auto-update on the next start."""
    result_file = os.path.join(tempfile.gettempdir(), "sp_update_result.txt")
    if not os.path.isfile(result_file):
        return
    message = None
    warning = False
    update_ok = False
    try:
        with open(result_file, encoding="utf-8-sig") as stream:
            lines = stream.read().splitlines()
        if lines and lines[0].strip() == "true":
            message = "插件已更新成功。\n\n" + "\n".join(lines[1:])
            update_ok = True
        elif lines:
            message = "自动更新未完成：\n" + "\n".join(lines[1:])
            warning = True
    except Exception:
        message = None
    try:
        os.remove(result_file)
    except OSError:
        pass
    if update_ok:
        # The new version is running, so the backup and temporary leftovers
        # are removed before the success prompt is displayed.
        _cleanup_update_remnants()
    if message and is_safe(main_window):
        if warning:
            QtCore.QTimer.singleShot(
                1500,
                lambda: QtWidgets.QMessageBox.warning(
                    main_window, "更新未完成", message
                ),
            )
        else:
            QtCore.QTimer.singleShot(
                1500,
                lambda: QtWidgets.QMessageBox.information(
                    main_window, "插件已更新", message
                ),
            )


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
def close_plugin():
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
    IS_TRANSLATION_ENABLED = _read_bool_setting(
        "sp_chinese_translation/enabled", True
    )
    TRANSLATE_LAYERS_PANEL = _read_bool_setting(
        "sp_chinese_translation/translate_layers_panel", True
    )

    # Remove native DLLs renamed aside by a previous in-place update.
    _cleanup_pending_dll_files()

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
    if not IS_TRANSLATION_ENABLED:
        _set_translation_enabled(False)

    main_window = sp.ui.get_main_window()
    # Painter starts this plugin while it is still populating the Python menu.
    # Renaming synchronously re-enters that construction and can invalidate
    # Painter's insertion separator, so wait until the menu build returns.
    QtCore.QTimer.singleShot(
        0, lambda window=main_window: _set_registered_plugin_display_name(window)
    )
    QtCore.QTimer.singleShot(
        2000, lambda window=main_window: _notify_update_result(window)
    )
    _label_extractor_action = QAction("中文翻译工具", main_window)
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
        f"total={total_ms:.1f} ms, "
        f"runtime={'Qt6/C++' if QT_MAJOR >= 6 else 'Qt5/C++'}"
    )

    # Do not attach a module-level Python callback to aboutToQuit. Painter may
    # unload plugin modules before QApplication emits/destroys all Qt objects,
    # leaving a stale callback behind. The timer and filter are parented to the
    # application and close_plugin() is Painter's supported unload hook.

    # From this point on Python never reads, writes, or paints Painter-owned
    # controls. The native engine owns widget events, item
    # delegates, hover originals, dynamic refresh, and resource-tree painting.

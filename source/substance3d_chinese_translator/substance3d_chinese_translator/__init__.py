# -*- coding: utf-8 -*-
"""
Substance 3D Painter / Designer 通用中文翻译补全插件
（资源分类树 + 资产全覆盖版）
支持：Adobe Substance 3D Painter 7.2 至官方最新版、
      Adobe Substance 3D Designer 15 及以上。
Painter 新版使用 PySide6 / Qt6 C++ 显示引擎，旧版自动使用
PySide2 / Qt5 C++ 显示引擎；Designer 固定使用 Qt6 显示引擎。
"""

import ctypes
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile

# 宿主识别：Designer 提供 ``sd`` 模块，Painter 提供 ``substance_painter``，
# 两个软件中只有一个可导入。合并后的插件在两种宿主中都可安装使用。
try:
    import sd  # noqa: F401  Substance 3D Designer host
    HOST = "designer"
    sp = None
except Exception:
    HOST = "painter"
    try:
        import substance_painter as sp
    except Exception:
        sp = None

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

HOST_DISPLAY_NAME = (
    "Substance 3D Designer" if HOST == "designer"
    else "Substance 3D Painter"
)

IS_APP_QUITTING = False
IS_CLEANING = False
IS_TRANSLATION_ENABLED = True
TRANSLATE_LAYERS_PANEL = True
FUZZY_MATCH_ENABLED = True
FALLBACK_SCAN_ENABLED = False
# 统一插件包中本模块位于 <包>/substance3d_chinese_translator/，包根目录是上一层。
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(MODULE_DIR)
# 词库统一放在插件包根目录的 translations/ 下，源码与安装包结构一致。
TRANSLATIONS_DIR = os.path.join(PLUGIN_DIR, "translations")
NATIVE_DIR = os.path.join(PLUGIN_DIR, "native")
EXTRACTOR_PATH = os.path.join(NATIVE_DIR, "translator_extractor.exe")
# 统一的 Qt6 翻译引擎同时服务 Painter 10.1+ 与 Designer 15+，
# C++ 侧在运行时自动识别宿主；Qt5 仅用于旧版 Painter。
DELEGATE_DLL_PATH = os.path.join(
    NATIVE_DIR,
    "translator_delegate_qt5.dll" if QT_MAJOR == 5
    else "translator_delegate_qt6.dll",
)
PLUGIN_DISPLAY_NAME = "中文翻译补全插件"
PLUGIN_VERSION = "1.3.1"
PLUGIN_REPO = "iillya/substance3d_chinese_translator"
PLUGIN_RELEASE_URL = (
    f"https://api.github.com/repos/{PLUGIN_REPO}/releases/latest"
)
PLUGIN_ASSET_NAME = "substance3d_chinese_translator.zip"

# Designer 没有图层面板，图层面板翻译开关仅对 Painter 生效。
if HOST == "designer":
    TRANSLATE_LAYERS_PANEL = False

# Designer 生命周期状态（Painter 复用原有的 _label_extractor_* 全局变量）。
_enabled_action = None
_tool_action = None
_startup_timer = None

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
ID_TRANSLATE_DICTS = {}


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
    ID_TRANSLATE_DICTS.clear()
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
            if name.lower() == "control_ids_zh.json":
                # ID 专属词库：与全局词库同格式（根级 translations），
# 键为完整控件 ID（上级类名||自身类名||自身 objectName||原文）。
                for source, target in entries.items():
                    if (isinstance(source, str) and isinstance(target, str)
                            and source and target):
                        ID_TRANSLATE_DICTS[source] = target
                        TRANSLATE_SOURCE_FILES[source] = path
                        loaded += 1
            else:
                for source, target in entries.items():
                    if (isinstance(source, str) and isinstance(target, str)
                            and source and target):
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
        dll.sp_delegate_add_id_translation.argtypes = [
            ctypes.c_wchar_p, ctypes.c_wchar_p
        ]
        dll.sp_delegate_add_id_translation.restype = None
        dll.sp_delegate_set_translation_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        dll.sp_delegate_set_translation_path.restype = None
        dll.sp_delegate_set_fallback_path.argtypes = [ctypes.c_wchar_p]
        dll.sp_delegate_set_fallback_path.restype = None
        dll.sp_delegate_set_id_path.argtypes = [ctypes.c_wchar_p]
        dll.sp_delegate_set_id_path.restype = None
        dll.sp_delegate_set_enabled.argtypes = [ctypes.c_int]
        dll.sp_delegate_set_enabled.restype = None
        dll.sp_delegate_set_fuzzy_match.argtypes = [ctypes.c_int]
        dll.sp_delegate_set_fuzzy_match.restype = None
        dll.sp_delegate_set_fallback_scan.argtypes = [ctypes.c_int]
        dll.sp_delegate_set_fallback_scan.restype = None
        dll.sp_delegate_set_translate_layers.argtypes = [ctypes.c_int]
        dll.sp_delegate_set_translate_layers.restype = None
        dll.sp_delegate_install.argtypes = [ctypes.c_void_p]
        dll.sp_delegate_install.restype = ctypes.c_int
        dll.sp_delegate_install_ui.argtypes = [ctypes.c_void_p]
        dll.sp_delegate_install_ui.restype = ctypes.c_int
        api_version = dll.sp_delegate_api_version()
        if api_version != 10:
            print(f">>> 原生翻译模块 API 不兼容: 需要 10，实际 {api_version}")
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
        dll.sp_delegate_set_id_path(
            os.path.join(TRANSLATIONS_DIR, "control_ids_zh.json")
        )
        dll.sp_delegate_set_translate_layers(int(TRANSLATE_LAYERS_PANEL))
        dll.sp_delegate_set_fuzzy_match(int(FUZZY_MATCH_ENABLED))
        dll.sp_delegate_set_fallback_scan(int(FALLBACK_SCAN_ENABLED))
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
        for id_string, target in ID_TRANSLATE_DICTS.items():
            if isinstance(id_string, str) and isinstance(target, str):
                dll.sp_delegate_add_id_translation(id_string, target)
                source_path = TRANSLATE_SOURCE_FILES.get(id_string)
                if source_path:
                    dll.sp_delegate_set_translation_path(id_string, source_path)
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


def _contains_han(text):
    return any("\u3400" <= char <= "\u9fff" for char in str(text))


def _is_valid_translation_source(text):
    """Return whether text can be retained as a translation source."""
    value = str(text).strip()
    if not value or _contains_han(value):
        return False
    if re.fullmatch(
        r"[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][+-]?\d+)?%?",
        value,
    ) is not None:
        return False
    return True


def _is_extractable_source(text):
    """Return whether text is a new source worth adding to an extraction."""
    value = str(text).strip()
    if not _is_valid_translation_source(value):
        return False
    if value in TRANSLATE_DICT:
        return False
    if value in ID_TRANSLATE_DICTS:
        return False
    return not any(
        value in translations
        for translations in CONTROL_TRANSLATE_DICTS.values()
    )


# ---------------------------------------------------------------
# Designer 资源库控件识别（与 C++ 引擎同一套规则）
# ---------------------------------------------------------------
def _class_name(obj):
    try:
        name = obj.metaObject().className()
    except Exception:
        return ""
    if isinstance(name, bytes):
        return name.decode("utf-8", errors="replace")
    return str(name)


def _is_resource_list(view):
    try:
        if _class_name(view) != (
                "Pfx::DataBase::ResourceTableWidget::CustomListView"):
            return False
        model = view.model()
        return model is not None and _class_name(model) == (
            "Pfx::DataBase::ResourcesListModel")
    except Exception:
        return False


def _is_library_tree(view):
    try:
        if view.objectName() != "mTreeWidget":
            return False
        model = view.model()
        if model is None or _class_name(model) != "QTreeModel":
            return False
        parent = view.parent()
        while parent is not None:
            if _class_name(parent) == (
                    "Pfx::Editor::Components::Shelf::QueryExplorerWidget"):
                return True
            parent = parent.parent()
    except Exception:
        pass
    return False


# ---------------------------------------------------------------
# 资源库搜索框的中文→英文反向翻译
# ---------------------------------------------------------------
class ChineseTranslationToolDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"中文翻译工具 v{PLUGIN_VERSION}")
        self.setObjectName("substance3d_chinese_translator_tool")
        self.setMinimumSize(780, 640)
        self.setSizeGripEnabled(True)
        self.setAttribute(WA_DELETE_ON_CLOSE, False)
        self._cancelled = False
        self._extractor_process = None
        self._extractor_request = ""
        self._extractor_stdout = ""
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        credit = QtWidgets.QLabel(
            '<a href="https://space.bilibili.com/281243426" '
            'style="color: #66aaff;">'
            "本插件由 bilibili 神说要凑数 制作，"
            "点击可查看作者主页</a>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            '<a href="https://github.com/iillya/'
            'substance3d_chinese_translator" '
            'style="color: #66aaff;">'
            "插件GitHub 仓库</a>",
            self,
        )
        credit.setOpenExternalLinks(True)
        credit.setToolTip(
            "打开 bilibili 作者主页 / GitHub 仓库"
        )
        layout.addWidget(credit)

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
            f"启用插件翻译（翻译 {HOST_DISPLAY_NAME} 界面）",
            translation_group,
        )
        self.translation_enabled_check.setChecked(IS_TRANSLATION_ENABLED)
        self.translation_enabled_check.setToolTip(
            f"勾选时插件翻译生效，自动翻译 {HOST_DISPLAY_NAME} 的界面控件。"
            "取消勾选时停止翻译并立即恢复所有界面原文显示。"
            "仅影响显示，不修改项目数据。"
        )
        self.translation_enabled_check.toggled.connect(
            _set_translation_enabled
        )
        translation_layout.addWidget(self.translation_enabled_check)

        if HOST == "painter":
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
        self.fuzzy_match_check = QtWidgets.QCheckBox(
            "启用模糊匹配（精准匹配优先，兼容大小写、全半角、下划线等差异）",
            translation_group,
        )
        self.fuzzy_match_check.setChecked(FUZZY_MATCH_ENABLED)
        self.fuzzy_match_check.setToolTip(
            "勾选后，当词库中找不到完全相同的原文时，"
            "会忽略大小写、全角/半角、下划线、多余空格、省略号等差异进行匹配。"
            "词库中的精准词条始终优先。"
        )
        self.fuzzy_match_check.toggled.connect(_set_fuzzy_match)
        translation_layout.addWidget(self.fuzzy_match_check)
        self.fallback_scan_check = QtWidgets.QCheckBox(
            "启用全量扫描兜底（每 10 秒一次，翻译有漏网时启用）",
            translation_group,
        )
        self.fallback_scan_check.setChecked(FALLBACK_SCAN_ENABLED)
        self.fallback_scan_check.setToolTip(
            "勾选后插件每 10 秒扫描一次全部可见控件补翻译。"
            "正常情况下界面事件已能覆盖所有翻译，一般无需开启。"
        )
        self.fallback_scan_check.toggled.connect(_set_fallback_scan)
        translation_layout.addWidget(self.fallback_scan_check)
        hint_text = (
            "提示：取消勾选“启用插件翻译”后，整个界面立即恢复英文原文。"
            "仅关闭“翻译图层面板”则只恢复图层面板中的原文。"
            if HOST == "painter"
            else "提示：取消勾选“启用插件翻译”后，整个界面立即恢复英文原文。"
        )
        translation_hint = QtWidgets.QLabel(hint_text, translation_group)
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
            "递归扫描 Substance 资源文件，并解析 SBS、SBSAR、SPSM、SPPR、"
            "GLSL 等受支持格式。只提取不含中文且不在当前插件词库中的原文。\n"
            "若输出字典已经存在，将保留其中已有译文并追加新词条。",
            self,
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
            "导出资源库中尚无有效中文译文的资产名称"
        )
        self.export_library_button.clicked.connect(
            self._export_asset_library_names
        )
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
        if (hasattr(self, "layers_translation_check")
                and is_safe(self.layers_translation_check)):
            self.layers_translation_check.setEnabled(master_on)

    def _open_translations_directory(self):
        os.makedirs(TRANSLATIONS_DIR, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(os.path.normpath(TRANSLATIONS_DIR))
        )

    def _export_asset_library_names(self):
        """导出资源库中尚无中文译文的资产名称，按宿主分发。"""
        if HOST == "designer":
            self._export_designer_asset_library_names()
        else:
            self._export_painter_asset_library_names()

    def _export_painter_asset_library_names(self):
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
                if _is_extractable_source(name) and not translated_name:
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

    def _export_designer_asset_library_names(self):
        """导出 Designer 界面资源库（资源库树与资源列表）中尚无中文译文的名称。"""
        initial = os.path.join(TRANSLATIONS_DIR, "untranslated_assets_zh.json")
        output, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出 Designer 资源库未翻译名称", initial,
            "Chinese translation package (*_zh.json)"
        )
        if not output:
            return
        if not output.lower().endswith("_zh.json"):
            output = os.path.splitext(output)[0] + "_zh.json"

        names = set()
        failures = []

        def candidate(name):
            value = str(name).strip()
            if not value or "://" in value or "?version=" in value:
                return False
            translated = TRANSLATE_DICT.get(value, "").strip()
            return _is_extractable_source(value) and not translated

        QtWidgets.QApplication.setOverrideCursor(WAIT_CURSOR)
        try:
            library_views = 0
            item_count = 0

            def _walk_model(model, prefix):
                def visit(index, path):
                    nonlocal item_count
                    item_count += 1
                    try:
                        text = index.data(
                            QtCore.Qt.ItemDataRole.DisplayRole
                        )
                    except Exception:
                        text = None
                    if isinstance(text, str):
                        value = text.strip()
                        if value and candidate(value):
                            names.add(value)
                    for row in range(model.rowCount(index)):
                        visit(
                            model.index(row, 0, index),
                            path + "/" + str(row),
                        )

                for row in range(model.rowCount()):
                    visit(model.index(row, 0), prefix + "/" + str(row))

            def _drain_lazy(model):
                """拉取懒加载模型尚未加载的行（canFetchMore/fetchMore）。"""
                guard = 0
                root = QtCore.QModelIndex()
                while guard < 200:
                    try:
                        if not model.canFetchMore(root):
                            break
                        model.fetchMore(root)
                    except Exception:
                        break
                    guard += 1

            def _walk_model_chain(model):
                """遍历视图模型及其代理链（sourceModel），覆盖全部数据。"""
                visited = set()
                current = model
                while current is not None and id(current) not in visited:
                    visited.add(id(current))
                    _drain_lazy(current)
                    _walk_model(current, "")
                    source_getter = getattr(
                        current, "sourceModel", None
                    )
                    current = (
                        source_getter() if callable(source_getter)
                        else None
                    )

            tree_view = None
            list_view = None
            for widget in QtWidgets.QApplication.allWidgets():
                if not isinstance(widget, QtWidgets.QAbstractItemView):
                    continue
                if _is_library_tree(widget):
                    tree_view = widget
                elif _is_resource_list(widget):
                    list_view = widget

            if tree_view is not None:
                library_views += 1
                try:
                    tree_view.expandAll()
                except Exception:
                    pass
                QtWidgets.QApplication.processEvents()
                tree_model = tree_view.model()
                if tree_model is not None:
                    _walk_model_chain(tree_model)
                    # 收集树中所有叶节点（分类），逐个选中让右侧列表
                    # 加载该分类的全部条目。
                    leaf_indices = []

                    def collect_leaves(index):
                        if tree_model.rowCount(index) == 0:
                            leaf_indices.append(index)
                            return
                        for row in range(tree_model.rowCount(index)):
                            collect_leaves(
                                tree_model.index(row, 0, index)
                            )

                    for row in range(tree_model.rowCount()):
                        collect_leaves(tree_model.index(row, 0))
                    for leaf_index, index in enumerate(leaf_indices, 1):
                        try:
                            tree_view.scrollTo(index)
                            tree_view.setCurrentIndex(index)
                            QtWidgets.QApplication.processEvents()
                            # 直接触发视图的 clicked/activated 信号，让
                            # Designer 加载该分类条目；比模拟鼠标更干净可靠。
                            tree_view.clicked.emit(index)
                            QtWidgets.QApplication.processEvents()
                            tree_view.activated.emit(index)
                            QtWidgets.QApplication.processEvents()
                            if (list_view is not None
                                    and list_view.model() is not None):
                                _walk_model_chain(list_view.model())
                        except Exception as exc:
                            failures.append(str(exc))
                        self.status_label.setText(
                            f"正在读取分类 {leaf_index}/"
                            f"{len(leaf_indices)}，"
                            f"已发现 {len(names)} 个名称"
                        )
                        QtWidgets.QApplication.processEvents()
            elif list_view is not None:
                library_views += 1
                if list_view.model() is not None:
                    _walk_model_chain(list_view.model())

            if library_views == 0:
                failures.append("未找到 Designer 界面中的资源库控件")

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
                name: existing.get(name, "")
                if isinstance(existing.get(name, ""), str) else ""
                for name in names
            }
            payload = {
                "$schema": "sp-translation-v1",
                "id": "designer-untranslated-assets",
                "language": "zh-CN",
                "description": (
                    "Untranslated asset names exported from the "
                    "Substance 3D Designer library"
                ),
                "extraction": {
                    "library_view_count": library_views,
                    "item_count": item_count,
                    "term_count": len(names),
                    "failed_count": len(failures),
                },
                "translations": dict(sorted(
                    translations.items(), key=lambda item: item[0].casefold()
                )),
            }
            _write_json_atomic(output, payload)
            self.output_edit.setText(output)
            self.status_label.setText(
                f"资产库导出完成：{len(names)} 条词条"
            )
            self.log.appendPlainText(
                f"资产库导出  {output}  "
                f"[界面库控件 {library_views}，条目 {item_count}，"
                f"词条 {len(names)}，失败 {len(failures)}]"
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "资产库导出失败", str(exc)
            )
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
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            QtWidgets.QMessageBox.warning(
                self, "无法开始", "请先选择资产目录。"
            )
            return
        folder = os.path.abspath(folder_text)
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
        # 防止误选磁盘根目录导致扫描整个分区。
        if os.path.dirname(folder) == folder:
            QtWidgets.QMessageBox.warning(
                self, "无法开始",
                "不能直接选择磁盘根目录作为资产目录，请选择具体的文件夹。",
            )
            return
        if not output.lower().endswith("_zh.json"):
            QtWidgets.QMessageBox.warning(self, "无法开始", "输出文件名必须以 _zh.json 结尾。")
            return
        if not self.package_id_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "无法开始", "翻译包 ID 不能为空。")
            return
        if not os.path.isfile(EXTRACTOR_PATH):
            QtWidgets.QMessageBox.critical(
                self, "无法开始", "缺少 C++ 词条提取器。请重新安装插件。"
            )
            return
        # 空目录直接拦截，避免启动提取器后误报"完成 0 条"。
        has_files = False
        output_abs = os.path.abspath(output)
        for root, dirs, files in os.walk(folder):
            dirs[:] = [
                name for name in dirs
                if name != "__pycache__" and name != "_unpacked_assets"
                and not name.startswith(".")
            ]
            for name in files:
                if os.path.abspath(os.path.join(root, name)) != output_abs:
                    has_files = True
                    break
            if has_files:
                break
        if not has_files:
            QtWidgets.QMessageBox.warning(
                self, "无法开始",
                "资产目录为空（或仅包含被忽略的隐藏/缓存目录），"
                "没有可提取的文件。",
            )
            return
        excluded = set(TRANSLATE_DICT)
        for translations in CONTROL_TRANSLATE_DICTS.values():
            excluded.update(translations)
        descriptor, request_path = tempfile.mkstemp(
            prefix="sp_translation_request_", suffix=".json"
        )
        os.close(descriptor)
        request = {
            "source": folder,
            "output": output,
            "package_id": self.package_id_edit.text().strip(),
            "description": self.description_edit.text().strip(),
            "ordinary_filenames": self.filename_check.isChecked(),
            "folder_names": self.foldername_check.isChecked(),
            "attributes": attributes,
            "excluded": sorted(excluded, key=str.casefold),
        }
        try:
            _write_json_atomic(request_path, request)
        except Exception as exc:
            try:
                os.remove(request_path)
            except OSError:
                pass
            QtWidgets.QMessageBox.critical(self, "无法开始", str(exc))
            return

        self._cancelled = False
        self.log.clear()
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self._set_running(True)
        self.status_label.setText("正在启动 C++ 词条提取器…")
        self._extractor_request = request_path
        self._extractor_stdout = ""
        process = QtCore.QProcess(self)
        self._extractor_process = process
        process.readyReadStandardOutput.connect(
            self._read_extractor_output
        )
        process.readyReadStandardError.connect(
            self._read_extractor_error
        )
        process.finished.connect(self._extractor_finished)
        process.errorOccurred.connect(self._extractor_error)
        process.start(EXTRACTOR_PATH, ["--request", request_path])

    def _read_extractor_output(self):
        process = self._extractor_process
        if not is_safe(process):
            return
        self._extractor_stdout += bytes(
            process.readAllStandardOutput()
        ).decode("utf-8", errors="replace")
        while "\n" in self._extractor_stdout:
            line, self._extractor_stdout = self._extractor_stdout.split(
                "\n", 1
            )
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except Exception:
                self.log.appendPlainText(line)
                continue
            message_type = message.get("type")
            if message_type == "progress":
                try:
                    current = int(message.get("current", 0))
                except (TypeError, ValueError):
                    current = 0
                try:
                    total = max(0, int(message.get("total", 0)))
                except (TypeError, ValueError):
                    total = 0
                self.progress.setRange(0, max(1, total))
                self.progress.setValue(current)
                try:
                    name = os.path.relpath(
                        message.get("file", ""),
                        self.folder_edit.text().strip(),
                    )
                except Exception:
                    name = message.get("file", "")
                self.status_label.setText(
                    f"[{current}/{total}] {name}"
                )
            elif message_type == "warning":
                self.log.appendPlainText(
                    f"失败  {message.get('file', '')}  "
                    f"[{message.get('message', '')}]"
                )
            elif message_type == "success":
                added = int(message.get("terms", 0))
                self.log.appendPlainText(
                    f"成功  {message.get('file', '')}  [新增 {added} 条]"
                )
            elif message_type == "finished":
                self.status_label.setText(
                    f"完成：新增 {message.get('terms', 0)} 条，"
                    f"失败 {message.get('failures', 0)} 个"
                )
                self.log.appendPlainText(
                    f"\n已写入: {message.get('output', '')}"
                )
            elif message_type == "fatal":
                self.log.appendPlainText(
                    f"致命错误: {message.get('message', '')}"
                )

    def _read_extractor_error(self):
        process = self._extractor_process
        if is_safe(process):
            text = bytes(process.readAllStandardError()).decode(
                "utf-8", errors="replace"
            ).strip()
            if text:
                self.log.appendPlainText(text)

    def _cleanup_extractor_request(self):
        if self._extractor_request:
            try:
                os.remove(self._extractor_request)
            except OSError:
                pass
            self._extractor_request = ""

    def _extractor_finished(self, exit_code, _exit_status):
        self._read_extractor_output()
        self._read_extractor_error()
        self._cleanup_extractor_request()
        self._set_running(False)
        if self._cancelled:
            self.status_label.setText("已取消，没有覆盖输出文件。")
        elif exit_code != 0:
            self.status_label.setText(f"提取失败（错误码 {exit_code}）")
        self._extractor_process = None

    def _extractor_error(self, _error):
        process = self._extractor_process
        if not is_safe(process):
            return
        error_text = process.errorString()
        self.log.appendPlainText(f"提取器错误: {error_text}")
        # QProcess 启动失败时（如提取器被占用）不会触发 finished()，
        # 这里补做收尾，避免界面一直停在“运行中”。
        self._read_extractor_output()
        self._cleanup_extractor_request()
        self._set_running(False)
        self.status_label.setText(f"提取器启动失败：{error_text}")
        self._extractor_process = None

    def _cancel(self):
        self._cancelled = True
        self.cancel_button.setEnabled(False)
        self.status_label.setText("正在取消…")
        process = self._extractor_process
        if is_safe(process):
            process.kill()

    def shutdown(self):
        self._cancelled = True
        process = self._extractor_process
        if is_safe(process):
            process.kill()
            process.waitForFinished(1500)
        self._extractor_process = None
        self._cleanup_extractor_request()


_label_extractor_dialog = None
_label_extractor_action = None
_label_extractor_menu_bar = None


def _set_layers_panel_translation(enabled):
    """Toggle C++ translation of UI controls inside Painter's Layers panel."""
    global TRANSLATE_LAYERS_PANEL
    TRANSLATE_LAYERS_PANEL = bool(enabled)
    QtCore.QSettings().setValue(
        "substance3d_chinese_translator/translate_layers_panel",
        TRANSLATE_LAYERS_PANEL,
    )
    dll = _load_native_delegate()
    if dll is not None:
        try:
            dll.sp_delegate_set_translate_layers(int(TRANSLATE_LAYERS_PANEL))
        except Exception as exc:
            print(">>> 切换图层面板翻译失败:", exc)


def _set_fuzzy_match(enabled):
    """Toggle the fuzzy fallback of the C++ translation engine.

    Exact dictionary lookups always win; fuzzy matching only catches casing,
    full/half-width, underscore and whitespace differences.
    """
    global FUZZY_MATCH_ENABLED
    FUZZY_MATCH_ENABLED = bool(enabled)
    if HOST == "painter":
        QtCore.QSettings().setValue(
            "substance3d_chinese_translator/fuzzy_match", FUZZY_MATCH_ENABLED
        )
    dll = _load_native_delegate()
    if dll is not None:
        try:
            dll.sp_delegate_set_fuzzy_match(int(FUZZY_MATCH_ENABLED))
        except Exception as exc:
            print(">>> 切换模糊匹配失败:", exc)


def _set_fallback_scan(enabled):
    """切换 C++ 的每 10 秒全量扫描兜底（默认关闭）。"""
    global FALLBACK_SCAN_ENABLED
    FALLBACK_SCAN_ENABLED = bool(enabled)
    QtCore.QSettings().setValue(
        "substance3d_chinese_translator/fallback_scan",
        FALLBACK_SCAN_ENABLED,
    )
    dll = _load_native_delegate()
    if dll is not None:
        try:
            dll.sp_delegate_set_fallback_scan(int(FALLBACK_SCAN_ENABLED))
        except Exception as exc:
            print(">>> 切换全量扫描兜底失败:", exc)


def _set_translation_enabled(enabled):
    """Toggle the whole translation engine on/off.

    Unchecking the master switch stops translation and restores every
    translated widget in the interface back to its original text.
    """
    global IS_TRANSLATION_ENABLED
    IS_TRANSLATION_ENABLED = bool(enabled)
    if HOST == "painter":
        QtCore.QSettings().setValue(
            "substance3d_chinese_translator/enabled", IS_TRANSLATION_ENABLED
        )
    dll = _load_native_delegate()
    if dll is not None:
        try:
            dll.sp_delegate_set_enabled(int(IS_TRANSLATION_ENABLED))
        except Exception as exc:
            print(">>> 切换插件翻译总开关失败:", exc)
    if _enabled_action is not None:
        try:
            if _enabled_action.isChecked() != IS_TRANSLATION_ENABLED:
                _enabled_action.setChecked(IS_TRANSLATION_ENABLED)
        except Exception:
            pass
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
        url, headers={"User-Agent": "substance3d_chinese_translator-updater"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _latest_release_info_api():
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
        # Accept versioned names such as
        # substance3d_chinese_translator_2.0.1.zip.
        for asset in data.get("assets") or []:
            name = (asset.get("name") or "").strip()
            lowered = name.casefold()
            if lowered.startswith(
                "substance3d_chinese_translator"
            ) and lowered.endswith(".zip"):
                download_url = asset.get("browser_download_url") or ""
                break
    if not download_url:
        raise RuntimeError(
            f"最新发布 {tag} 中没有找到 {PLUGIN_ASSET_NAME} 安装包"
            "（支持 substance3d_chinese_translator.zip 或 "
            "substance3d_chinese_translator_版本.zip）。"
        )
    notes = data.get("body") or ""
    return version, download_url, notes


def _latest_release_info_via_redirect():
    """绕过 GitHub API 限流：跟随 releases/latest 重定向，从标签构造下载地址。

    网页版 releases/latest 不经过 api.github.com，不受未认证 60 次/小时限制。
    最终地址形如 https://github.com/owner/repo/releases/tag/v1.0.0，
    资产下载地址按 GitHub 固定规则构造。
    """
    try:
        request = urllib.request.Request(
            f"https://github.com/{PLUGIN_REPO}/releases/latest",
            headers={
                "User-Agent": "substance3d_chinese_translator-updater"
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            final_url = response.geturl()
        marker = "/releases/tag/"
        index = final_url.rfind(marker)
        if index < 0:
            return None
        tag = final_url[index + len(marker):].split("?")[0].strip()
        if not tag:
            return None
        version = tag.lstrip("vV")
        download_url = (
            f"https://github.com/{PLUGIN_REPO}/releases/download/"
            f"{tag}/{PLUGIN_ASSET_NAME}"
        )
        return version, download_url, ""
    except Exception:
        return None


def _latest_release_info():
    """获取最新正式版信息；API 被限流时自动回退到网页重定向。"""
    try:
        return _latest_release_info_api()
    except Exception as api_error:
        fallback = _latest_release_info_via_redirect()
        if fallback is not None:
            return fallback
        raise api_error


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
        url, headers={"User-Agent": "substance3d_chinese_translator-updater"}
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
    # Replacing the plug-in while an extraction is running would fail on the
    # locked extractor EXE. Ask the user to finish or cancel the extraction
    # first instead of letting the update fail and roll back mid-way.
    tool_dialog = (
        _label_extractor_dialog if is_safe(_label_extractor_dialog) else parent
    )
    if (is_safe(tool_dialog)
            and getattr(tool_dialog, "_extractor_process", None) is not None):
        QtWidgets.QMessageBox.warning(
            parent,
            "正在提取词条",
            "当前正在进行词条提取，请先等待提取完成或点击“取消”后再检查更新。",
        )
        return
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
            f"substance3d_chinese_translator_{version}.zip",
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
        # Apply the package in place without closing the host application,
        # then ask the user to restart so the new files (and native DLL)
        # are loaded.
        _apply_update_now(destination, parent)
    except Exception as exc:
        detail = str(exc)
        if "403" in detail or "rate limit" in detail.casefold():
            hint = (
                "GitHub API 触发限流（未登录每小时 60 次）。\n"
                "插件已自动尝试通过网页重定向获取版本信息，"
                "若仍失败请稍后再试。"
            )
        else:
            hint = "请确认网络可访问 GitHub，稍后再试。"
        QtWidgets.QMessageBox.warning(
            parent,
            "检查更新失败",
            f"无法获取最新版本：\n{exc}\n\n{hint}",
        )


def _copy_file_safely(source, target):
    """Copy ``source`` to ``target``, working around a locked native binary.

    A DLL mapped into the host application (or the standalone extractor EXE
    while an extraction is running) cannot be overwritten, but Windows allows
    it to be renamed, so the old file is moved aside and the new one is
    written under the original name. The running session keeps using the old
    image in memory; the new file is loaded at the next start.
    """
    try:
        shutil.copy2(source, target)
        return
    except PermissionError:
        lowered = target.lower()
        if not (lowered.endswith(".dll") or lowered.endswith(".exe")):
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


def _cleanup_pending_native_files():
    """Remove native DLLs/EXEs renamed aside by a previous live update."""
    try:
        if not os.path.isdir(NATIVE_DIR):
            return
        for name in os.listdir(NATIVE_DIR):
            lowered = name.lower()
            if lowered.endswith(".dll.old") or lowered.endswith(".exe.old"):
                try:
                    os.remove(os.path.join(NATIVE_DIR, name))
                except OSError:
                    pass
    except Exception:
        pass


def _apply_update_now(zip_path, parent=None):
    """Apply a downloaded release package in place, without closing the host.

    The old plug-in directory is backed up, every file shipped by the new
    package is copied over it (a loaded native DLL is renamed aside first),
    and the user's own translation JSON files are preserved. The host is left
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
        "Substance3DChineseTranslationBackup",
    )
    stage_dir = None
    preserve_dir = None
    QtWidgets.QApplication.setOverrideCursor(WAIT_CURSOR)
    try:
        stage_dir = tempfile.mkdtemp(prefix="sp_update_stage_")
        with zipfile.ZipFile(zip_path) as archive:
            # Reject path traversal and symlinks before anything is written:
            # a tampered update package must never escape the staging folder.
            for info in archive.infolist():
                raw_name = info.filename.replace("\\", "/")
                parts = [part for part in raw_name.split("/")
                         if part not in ("", ".")]
                unsafe = (
                    raw_name.startswith("/")
                    or any(part == ".." for part in parts)
                    or (len(raw_name) >= 2 and raw_name[1] == ":")
                )
                if unsafe:
                    raise RuntimeError(
                        f"更新包包含不安全路径: {info.filename}"
                    )
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError(
                        f"更新包包含符号链接: {info.filename}"
                    )
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
                lowered = name.lower()
                if not (lowered.endswith(".dll.old")
                        or lowered.endswith(".exe.old")):
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

        result_file = os.path.join(
            tempfile.gettempdir(), "substance3d_update_result.txt"
        )
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
            f"请重启 {HOST_DISPLAY_NAME} 以启用新版本。\n"
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
        kept = (
            f"\n更新包保留在: {zip_path}，可稍后重试或手动安装。"
            if os.path.isfile(zip_path) else ""
        )
        QtWidgets.QMessageBox.warning(
            parent,
            "更新失败",
            f"应用更新失败：\n{exc}\n\n插件目录已保持/恢复为原版本。{kept}",
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
    for name in (
        "Substance3DChineseTranslationBackup",
        "Substance3DChineseTranslationUpdate",
    ):
        path = os.path.join(local_app_data, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    temp_dir = tempfile.gettempdir()
    for name in ("substance3d_apply_update.ps1",
                 "substance3d_update_result.txt"):
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
    result_file = os.path.join(
        tempfile.gettempdir(), "substance3d_update_result.txt"
    )
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
                lambda: (
                    QtWidgets.QMessageBox.warning(
                        main_window, "更新未完成", message
                    )
                    if is_safe(main_window) else None
                ),
            )
        else:
            QtCore.QTimer.singleShot(
                1500,
                lambda: (
                    QtWidgets.QMessageBox.information(
                        main_window, "插件已更新", message
                    )
                    if is_safe(main_window) else None
                ),
            )


def show_translation_tool():
    global _label_extractor_dialog
    if not is_safe(_label_extractor_dialog):
        if HOST == "designer":
            ui_manager = (
                sd.getContext().getSDApplication().getQtForPythonUIMgr()
            )
            parent = ui_manager.getMainWindow()
        else:
            parent = sp.ui.get_main_window()
        _label_extractor_dialog = ChineseTranslationToolDialog(parent)
    _label_extractor_dialog.fuzzy_match_check.setChecked(FUZZY_MATCH_ENABLED)
    _label_extractor_dialog.fallback_scan_check.setChecked(
        FALLBACK_SCAN_ENABLED
    )
    _label_extractor_dialog.translation_enabled_check.setChecked(
        IS_TRANSLATION_ENABLED
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


# ==========================================
# 9b. Designer 生命周期的启动与清理
# ==========================================
def initializeSDPlugin():
    """Substance 3D Designer 插件入口。"""
    global _enabled_action, _tool_action, _startup_timer

    context = sd.getContext()
    application = context.getSDApplication()
    ui_manager = application.getQtForPythonUIMgr()
    if ui_manager is None:
        raise RuntimeError("Designer Qt UI manager is not available")
    main_window = ui_manager.getMainWindow()

    # 移除上次原地更新遗留的 .old 原生文件（与 Painter 一致）。
    _cleanup_pending_native_files()

    load_translation_packages()
    native_dictionary_ok = _sync_native_dictionary()
    native_ui_ok = _install_native_ui(QtWidgets.QApplication.instance())
    if not native_dictionary_ok or not native_ui_ok:
        print(
            ">>> 原生翻译引擎未完全启用: "
            f"dictionary={native_dictionary_ok}, ui={native_ui_ok}"
        )
    # Designer 主窗口还在构建中，先禁用翻译，3 秒后自动启用。
    _set_translation_enabled(False)

    # 保持 Designer 菜单紧凑：菜单栏只加一个“中文翻译工具”入口。
    _enabled_action = QAction("启用实时翻译", main_window)
    _enabled_action.setCheckable(True)
    _enabled_action.setChecked(False)
    _enabled_action.toggled.connect(_set_translation_enabled)
    _tool_action = QAction("中文翻译工具", main_window)
    _tool_action.triggered.connect(show_translation_tool)
    main_window.menuBar().addAction(_tool_action)

    _startup_timer = QtCore.QTimer(main_window)
    _startup_timer.setSingleShot(True)
    _startup_timer.timeout.connect(lambda: _set_translation_enabled(True))
    _startup_timer.start(3000)
    # 更新成功提示与临时残留清理（与 Painter 一致）。
    QtCore.QTimer.singleShot(
        2000, lambda window=main_window: _notify_update_result(window)
    )
    print("[Designer 中文翻译] 插件已启动，版本", PLUGIN_VERSION)


def uninitializeSDPlugin():
    """Substance 3D Designer 插件卸载入口。"""
    global _enabled_action, _tool_action, _label_extractor_dialog
    global _startup_timer

    if _native_delegate is not None:
        try:
            _native_delegate.sp_delegate_set_enabled(0)
        except Exception:
            pass
    if is_safe(_label_extractor_dialog):
        try:
            _label_extractor_dialog.shutdown()
            _label_extractor_dialog.close()
            delete(_label_extractor_dialog)
        except Exception:
            pass
    _label_extractor_dialog = None
    if is_safe(_tool_action):
        try:
            main_window = (
                sd.getContext().getSDApplication()
                .getQtForPythonUIMgr().getMainWindow()
            )
            main_window.menuBar().removeAction(_tool_action)
        except Exception:
            pass
        delete(_tool_action)
    if is_safe(_enabled_action):
        delete(_enabled_action)
    _enabled_action = None
    _tool_action = None
    _startup_timer = None
    print("[Designer 中文翻译] 插件已停止")


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
                action.setObjectName(
                    "substance3d_chinese_translator_plugin_registration"
                )
                return True
    return False


def start_plugin():
    global IS_APP_QUITTING, IS_CLEANING, IS_TRANSLATION_ENABLED
    global TRANSLATE_LAYERS_PANEL, FUZZY_MATCH_ENABLED, FALLBACK_SCAN_ENABLED
    global _label_extractor_action, _label_extractor_menu_bar

    app = QtWidgets.QApplication.instance()
    if not is_safe(app):
        return

    startup_started = time.perf_counter()
    close_plugin()

    IS_APP_QUITTING = False
    IS_CLEANING = False
    IS_TRANSLATION_ENABLED = _read_bool_setting(
        "substance3d_chinese_translator/enabled", True
    )
    TRANSLATE_LAYERS_PANEL = _read_bool_setting(
        "substance3d_chinese_translator/translate_layers_panel", True
    )
    FUZZY_MATCH_ENABLED = _read_bool_setting(
        "substance3d_chinese_translator/fuzzy_match", True
    )
    FALLBACK_SCAN_ENABLED = _read_bool_setting(
        "substance3d_chinese_translator/fallback_scan", False
    )

    # Remove native DLLs/EXEs renamed aside by a previous in-place update.
    _cleanup_pending_native_files()

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
    _label_extractor_action.setObjectName(
        "substance3d_chinese_translator_tool_action"
    )
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

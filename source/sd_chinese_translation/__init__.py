# -*- coding: utf-8 -*-
"""Realtime Chinese translation supplement for Substance 3D Designer."""

import ctypes
import json
import os
import tempfile

import sd
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import getCppPointer, isValid


PLUGIN_VERSION = "0.1.0"
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PUBLIC_TRANSLATIONS_DIR = os.path.normpath(
    os.path.join(MODULE_DIR, "..", "public", "translations")
)
# SP and SD share the repository dictionary set. Release packages receive a
# private copy during packaging because source/public is not installed.
TRANSLATIONS_DIR = (
    _PUBLIC_TRANSLATIONS_DIR
    if os.path.isdir(_PUBLIC_TRANSLATIONS_DIR)
    else os.path.join(MODULE_DIR, "translations")
)
NATIVE_PATH = os.path.join(MODULE_DIR, "native", "sd_translation_delegate_qt6.dll")
EXTRACTOR_PATH = os.path.join(MODULE_DIR, "native", "sd_translation_extractor.exe")

_translations = {}
_translation_paths = {}
_control_translations = {}
_native = None
_menu = None
_enabled_action = None
_tool_action = None
_tool_dialog = None
_startup_timer = None
_fuzzy_match_enabled = True


def _is_safe(obj):
    if obj is None:
        return False
    try:
        return isValid(obj)
    except Exception:
        return False


def _write_json_atomic(path, payload):
    destination = os.path.abspath(path)
    directory = os.path.dirname(destination) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".sd_translation_", suffix=".tmp", dir=directory
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


def _load_packages():
    _translations.clear()
    _translation_paths.clear()
    _control_translations.clear()
    if not os.path.isdir(TRANSLATIONS_DIR):
        return

    for name in sorted(os.listdir(TRANSLATIONS_DIR), key=str.casefold):
        if not name.lower().endswith("_zh.json"):
            continue
        path = os.path.join(TRANSLATIONS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8-sig") as stream:
                payload = json.load(stream)
            if payload.get("$schema") != "sp-translation-v1":
                raise ValueError("unsupported schema")
            if payload.get("language") != "zh-CN":
                raise ValueError("language must be zh-CN")

            for source, target in payload.get("translations", {}).items():
                if isinstance(source, str) and isinstance(target, str) and source and target:
                    _translations[source] = target
                    _translation_paths[source] = path

            for control_type, section in payload.get("control_types", {}).items():
                destination = _control_translations.setdefault(control_type, {})
                for source, target in section.get("translations", {}).items():
                    if isinstance(source, str) and isinstance(target, str) and source and target:
                        destination[source] = target
                        _translation_paths[source] = path
            print("[Designer 中文翻译] 已加载", name)
        except Exception as exc:
            print("[Designer 中文翻译] 跳过无效词库", name, exc)


def _load_native():
    global _native
    if _native is not None:
        return _native

    dll = ctypes.CDLL(NATIVE_PATH)
    dll.sp_delegate_api_version.restype = ctypes.c_int
    dll.sp_delegate_clear_translations.argtypes = []
    dll.sp_delegate_reserve_translations.argtypes = [ctypes.c_int]
    dll.sp_delegate_add_translation.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    dll.sp_delegate_add_control_translation.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]
    dll.sp_delegate_set_translation_path.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]
    dll.sp_delegate_set_fallback_path.argtypes = [ctypes.c_wchar_p]
    dll.sp_delegate_set_enabled.argtypes = [ctypes.c_int]
    dll.sp_delegate_set_fuzzy_match.argtypes = [ctypes.c_int]
    dll.sp_delegate_set_translate_layers.argtypes = [ctypes.c_int]
    dll.sp_delegate_install_ui.argtypes = [ctypes.c_void_p]
    dll.sp_delegate_install_ui.restype = ctypes.c_int
    if dll.sp_delegate_api_version() != 10:
        raise RuntimeError("C++ translation module API mismatch")
    _native = dll
    return dll


def _sync_and_install():
    dll = _load_native()
    # Keep translation disabled while Designer constructs its main window.
    dll.sp_delegate_set_enabled(0)
    dll.sp_delegate_clear_translations()
    dll.sp_delegate_set_fallback_path(
        os.path.join(TRANSLATIONS_DIR, "user_added_zh.json")
    )
    # Painter's layer-panel specialization must not run in Designer.
    dll.sp_delegate_set_translate_layers(0)
    dll.sp_delegate_set_fuzzy_match(int(_fuzzy_match_enabled))
    dll.sp_delegate_reserve_translations(len(_translations))

    for source, target in _translations.items():
        dll.sp_delegate_add_translation(source, target)
        source_path = _translation_paths.get(source)
        if source_path:
            dll.sp_delegate_set_translation_path(source, source_path)

    for control_type, entries in _control_translations.items():
        for source, target in entries.items():
            dll.sp_delegate_add_control_translation(control_type, source, target)

    application = QtWidgets.QApplication.instance()
    if application is None:
        raise RuntimeError("QApplication is not available")
    pointer = getCppPointer(application)[0]
    if not pointer or dll.sp_delegate_install_ui(ctypes.c_void_p(pointer)) != 1:
        raise RuntimeError("failed to install Qt translation engine")


def _enable_after_startup():
    if _native is not None:
        _native.sp_delegate_set_enabled(1)
    if _enabled_action is not None:
        _enabled_action.setChecked(True)


def _set_enabled(enabled):
    if _native is not None:
        _native.sp_delegate_set_enabled(int(bool(enabled)))


def _set_fuzzy_match(enabled):
    global _fuzzy_match_enabled
    _fuzzy_match_enabled = bool(enabled)
    if _native is not None:
        _native.sp_delegate_set_fuzzy_match(int(_fuzzy_match_enabled))


def _reload():
    _load_packages()
    _sync_and_install()
    if _native is not None:
        _native.sp_delegate_set_enabled(1)
        _native.sp_delegate_set_fuzzy_match(int(_fuzzy_match_enabled))
    if _enabled_action is not None:
        _enabled_action.setChecked(True)
    if _is_safe(_tool_dialog):
        _tool_dialog.translation_enabled_check.setChecked(True)


class ChineseTranslationToolDialog(QtWidgets.QDialog):
    """Designer front end for the standalone C++ Substance term extractor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"中文翻译工具 v{PLUGIN_VERSION}")
        self.setObjectName("sd_chinese_translation_tool")
        self.setMinimumSize(780, 610)
        self.setSizeGripEnabled(True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._cancelled = False
        self._extractor_process = None
        self._extractor_request = ""
        self._extractor_stdout = ""
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        translation_group = QtWidgets.QGroupBox("界面翻译", self)
        translation_layout = QtWidgets.QVBoxLayout(translation_group)
        self.translation_enabled_check = QtWidgets.QCheckBox(
            "启用插件翻译（翻译 Designer 界面）", translation_group
        )
        self.translation_enabled_check.setChecked(
            bool(_enabled_action is None or _enabled_action.isChecked())
        )
        self.translation_enabled_check.toggled.connect(self._toggle_translation)
        translation_layout.addWidget(self.translation_enabled_check)
        self.fuzzy_match_check = QtWidgets.QCheckBox(
            "启用模糊匹配（精准匹配优先，兼容大小写、全半角、下划线等差异）",
            translation_group,
        )
        self.fuzzy_match_check.setChecked(_fuzzy_match_enabled)
        self.fuzzy_match_check.toggled.connect(_set_fuzzy_match)
        translation_layout.addWidget(self.fuzzy_match_check)
        reload_button = QtWidgets.QPushButton("重新加载词库", translation_group)
        reload_button.clicked.connect(_reload)
        translation_layout.addWidget(reload_button)
        layout.addWidget(translation_group)

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
        self.package_id_edit = QtWidgets.QLineEdit("designer-extracted-assets")
        form.addRow("翻译包 ID", self.package_id_edit)
        self.description_edit = QtWidgets.QLineEdit(
            "Extracted Substance Designer asset labels"
        )
        form.addRow("说明", self.description_edit)
        layout.addWidget(extract_group)

        options_group = QtWidgets.QGroupBox("提取选项", self)
        options_form = QtWidgets.QFormLayout(options_group)
        name_widget = QtWidgets.QWidget(options_group)
        name_layout = QtWidgets.QHBoxLayout(name_widget)
        name_layout.setContentsMargins(0, 0, 0, 0)
        self.filename_check = QtWidgets.QCheckBox("提取普通文件名", name_widget)
        self.filename_check.setChecked(True)
        self.foldername_check = QtWidgets.QCheckBox("提取文件夹名", name_widget)
        self.foldername_check.setChecked(False)
        name_layout.addWidget(self.filename_check)
        name_layout.addWidget(self.foldername_check)
        name_layout.addStretch(1)
        options_form.addRow("名称", name_widget)

        attribute_widget = QtWidgets.QWidget(options_group)
        attribute_grid = QtWidgets.QGridLayout(attribute_widget)
        attribute_grid.setContentsMargins(0, 0, 0, 0)
        specs = [
            ("label_check", "提取 label", True),
            ("text_check", "提取 text", True),
            ("group_check", "提取 group", True),
            ("description_check", "提取 description", False),
            ("category_check", "提取 category", True),
            ("keywords_check", "提取 keywords（可能影响搜索）", False),
            ("values_check", "提取下拉选项 values", True),
            ("disabled_description_check",
             "提取禁用说明 description_disabled", False),
        ]
        self._attribute_checks = []
        for index, (attribute, caption, checked) in enumerate(specs):
            checkbox = QtWidgets.QCheckBox(caption, attribute_widget)
            checkbox.setChecked(checked)
            setattr(self, attribute, checkbox)
            self._attribute_checks.append(checkbox)
            attribute_grid.addWidget(checkbox, index // 3, index % 3)
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

        self.progress = QtWidgets.QProgressBar(self)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status_label = QtWidgets.QLabel("就绪", self)
        layout.addWidget(self.status_label)
        self.log = QtWidgets.QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        layout.addWidget(self.log, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.open_translations_button = QtWidgets.QPushButton(
            "打开插件词条目录", self
        )
        self.open_translations_button.clicked.connect(
            self._open_translations_directory
        )
        buttons.addWidget(self.open_translations_button)
        buttons.addStretch(1)
        self.extract_button = QtWidgets.QPushButton("开始提取", self)
        self.cancel_button = QtWidgets.QPushButton("取消", self)
        self.close_button = QtWidgets.QPushButton("关闭", self)
        self.cancel_button.setEnabled(False)
        self.extract_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.extract_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def _toggle_translation(self, enabled):
        if _enabled_action is not None and _enabled_action.isChecked() != enabled:
            _enabled_action.setChecked(enabled)
        else:
            _set_enabled(enabled)

    def _open_translations_directory(self):
        os.makedirs(TRANSLATIONS_DIR, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(os.path.normpath(TRANSLATIONS_DIR))
        )

    def _browse_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择 Substance 资产目录", self.folder_edit.text()
        )
        if folder:
            self.folder_edit.setText(folder)
            if not self.output_edit.text().strip():
                self.output_edit.setText(
                    os.path.join(folder, "extracted_assets_zh.json")
                )

    def _browse_output(self):
        initial = self.output_edit.text().strip() or "extracted_assets_zh.json"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存翻译包", initial,
            "Chinese translation package (*_zh.json)"
        )
        if path:
            if not path.lower().endswith("_zh.json"):
                path = os.path.splitext(path)[0] + "_zh.json"
            self.output_edit.setText(path)

    def _set_running(self, running):
        controls = [
            self.extract_button, self.folder_edit, self.output_edit,
            self.package_id_edit, self.description_edit, self.filename_check,
            self.foldername_check, self.folder_button, self.output_button,
        ] + self._attribute_checks
        for control in controls:
            if _is_safe(control):
                control.setEnabled(not running)
        if _is_safe(self.cancel_button):
            self.cancel_button.setEnabled(running)

    def _start(self):
        folder = os.path.abspath(self.folder_edit.text().strip())
        output = os.path.abspath(self.output_edit.text().strip())
        attributes = [
            name for name, checkbox in (
                ("label", self.label_check),
                ("text", self.text_check),
                ("group", self.group_check),
                ("description", self.description_check),
                ("category", self.category_check),
                ("keywords", self.keywords_check),
                ("values", self.values_check),
                ("description_disabled", self.disabled_description_check),
            ) if checkbox.isChecked()
        ]
        if not os.path.isdir(folder):
            QtWidgets.QMessageBox.warning(self, "无法开始", "请选择有效的资产目录。")
            return
        if not output.lower().endswith("_zh.json"):
            QtWidgets.QMessageBox.warning(
                self, "无法开始", "输出文件名必须以 _zh.json 结尾。"
            )
            return
        if not self.package_id_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "无法开始", "翻译包 ID 不能为空。")
            return
        if not os.path.isfile(EXTRACTOR_PATH):
            QtWidgets.QMessageBox.critical(
                self, "无法开始", "缺少 C++ 词条提取器，请重新安装插件。"
            )
            return

        excluded = set(_translations)
        for entries in _control_translations.values():
            excluded.update(entries)
        descriptor, request_path = tempfile.mkstemp(
            prefix="sd_translation_request_", suffix=".json"
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
        process.readyReadStandardOutput.connect(self._read_extractor_output)
        process.readyReadStandardError.connect(self._read_extractor_error)
        process.finished.connect(self._extractor_finished)
        process.errorOccurred.connect(self._extractor_error)
        process.start(EXTRACTOR_PATH, ["--request", request_path])

    def _read_extractor_output(self):
        process = self._extractor_process
        if not _is_safe(process):
            return
        self._extractor_stdout += bytes(
            process.readAllStandardOutput()
        ).decode("utf-8", errors="replace")
        while "\n" in self._extractor_stdout:
            line, self._extractor_stdout = self._extractor_stdout.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except Exception:
                self.log.appendPlainText(line)
                continue
            kind = message.get("type")
            if kind == "progress":
                current = int(message.get("current", 0))
                total = max(0, int(message.get("total", 0)))
                self.progress.setRange(0, max(1, total))
                self.progress.setValue(current)
                try:
                    name = os.path.relpath(
                        message.get("file", ""), self.folder_edit.text().strip()
                    )
                except Exception:
                    name = message.get("file", "")
                self.status_label.setText(f"[{current}/{total}] {name}")
            elif kind == "warning":
                self.log.appendPlainText(
                    f"失败  {message.get('file', '')}  "
                    f"[{message.get('message', '')}]"
                )
            elif kind == "success":
                self.log.appendPlainText(
                    f"成功  {message.get('file', '')}  "
                    f"[新增 {int(message.get('terms', 0))} 条]"
                )
            elif kind == "finished":
                self.status_label.setText(
                    f"完成：新增 {message.get('terms', 0)} 条，"
                    f"失败 {message.get('failures', 0)} 个"
                )
                self.log.appendPlainText(f"\n已写入: {message.get('output', '')}")
            elif kind == "fatal":
                self.log.appendPlainText(f"致命错误: {message.get('message', '')}")

    def _read_extractor_error(self):
        process = self._extractor_process
        if _is_safe(process):
            output = bytes(process.readAllStandardError()).decode(
                "utf-8", errors="replace"
            ).strip()
            if output:
                self.log.appendPlainText(output)

    def _cleanup_request(self):
        if self._extractor_request:
            try:
                os.remove(self._extractor_request)
            except OSError:
                pass
            self._extractor_request = ""

    def _extractor_finished(self, exit_code, _exit_status):
        self._read_extractor_output()
        self._read_extractor_error()
        self._cleanup_request()
        self._set_running(False)
        if self._cancelled:
            self.status_label.setText("已取消，没有覆盖输出文件。")
        elif exit_code != 0:
            self.status_label.setText(f"提取失败（错误码 {exit_code}）")
        self._extractor_process = None

    def _extractor_error(self, _error):
        process = self._extractor_process
        if _is_safe(process):
            self.log.appendPlainText(process.errorString())

    def _cancel(self):
        self._cancelled = True
        self.cancel_button.setEnabled(False)
        self.status_label.setText("正在取消…")
        if _is_safe(self._extractor_process):
            self._extractor_process.kill()

    def shutdown(self):
        self._cancelled = True
        if _is_safe(self._extractor_process):
            self._extractor_process.kill()
            self._extractor_process.waitForFinished(1500)
        self._extractor_process = None
        self._cleanup_request()


def _show_translation_tool():
    global _tool_dialog
    if not _is_safe(_tool_dialog):
        context = sd.getContext()
        ui_manager = context.getSDApplication().getQtForPythonUIMgr()
        _tool_dialog = ChineseTranslationToolDialog(ui_manager.getMainWindow())
    _tool_dialog.translation_enabled_check.setChecked(
        bool(_enabled_action is None or _enabled_action.isChecked())
    )
    _tool_dialog.fuzzy_match_check.setChecked(_fuzzy_match_enabled)
    _tool_dialog.show()
    _tool_dialog.raise_()
    _tool_dialog.activateWindow()


def initializeSDPlugin():
    global _menu, _enabled_action, _tool_action, _startup_timer

    context = sd.getContext()
    application = context.getSDApplication()
    ui_manager = application.getQtForPythonUIMgr()
    if ui_manager is None:
        raise RuntimeError("Designer Qt UI manager is not available")
    main_window = ui_manager.getMainWindow()

    _load_packages()
    _sync_and_install()

    # Keep the release UI compact: one menu-bar action opens the complete
    # translation tool. Translation itself still starts automatically.
    _enabled_action = QtGui.QAction("启用实时翻译", main_window)
    _enabled_action.setCheckable(True)
    _enabled_action.setChecked(False)
    _enabled_action.toggled.connect(_set_enabled)
    _tool_action = QtGui.QAction("中文翻译工具", main_window)
    _tool_action.triggered.connect(_show_translation_tool)
    main_window.menuBar().addAction(_tool_action)

    _startup_timer = QtCore.QTimer(main_window)
    _startup_timer.setSingleShot(True)
    _startup_timer.timeout.connect(_enable_after_startup)
    _startup_timer.start(3000)
    print("[Designer 中文翻译] 插件已启动，版本", PLUGIN_VERSION)


def uninitializeSDPlugin():
    global _menu, _enabled_action, _tool_action, _tool_dialog, _startup_timer

    if _native is not None:
        _native.sp_delegate_set_enabled(0)
    if _is_safe(_tool_dialog):
        try:
            _tool_dialog.shutdown()
            _tool_dialog.close()
            _tool_dialog.deleteLater()
        except Exception:
            pass
    if _is_safe(_tool_action):
        try:
            main_window = sd.getContext().getSDApplication().getQtForPythonUIMgr().getMainWindow()
            main_window.menuBar().removeAction(_tool_action)
        except Exception:
            pass
        _tool_action.deleteLater()
    if _is_safe(_enabled_action):
        _enabled_action.deleteLater()
    _menu = None
    _enabled_action = None
    _tool_action = None
    _tool_dialog = None
    _startup_timer = None
    print("[Designer 中文翻译] 插件已停止")

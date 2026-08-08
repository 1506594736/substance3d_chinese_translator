import substance_painter.ui
import substance_painter.project
import substance_painter.logging as sp_logging
from PySide6 import QtCore, QtWidgets, QtGui
import shiboken6 as shiboken

# ==========================================
# 1. 全局配置与逻辑映射 (保持不变)
# ==========================================
TOOL_LOGIC_GROUPS = {
    "绘画": ["Paint", "Paint_Physics"],
    "橡皮": ["Eraser", "Eraser_Physics"],
    "映射": ["PaintProjective", "PaintProjective_Physics"],
    "沿路径绘制": ["Curve_Stroke_3D", "Curve_Ribbon", "Curve_Fill","Curve_Eraser_Stroke_3D", "Curve_Smudge_Stroke_3D"],
    "涂抹": ["Smudge"],
    "克隆": ["clone_relative", "clone_absolute"],
    "几何体填充": ["Geometry"],
    "材质选择器": ["materials_action"]
}

if not hasattr(QtCore, '_auto_align_cfg'):
    QtCore._auto_align_cfg = {
        '3A': 1, '3S': 0, 
        '2A': 3, '2S': 2,
        'enabled': True,
        'last_view': None,
        'last_tool': None,
        'active_groups': {
            "绘画": True, 
            "橡皮": True, 
            "映射": False,
            "几何体填充": False, 
            "涂抹": True, 
            "克隆": False,
            "沿路径绘制": False, 
            "材质选择器": False
        }
    }

ALIGN_ITEMS = ["镜头", "切线|Wrap包裹", "切线|平面", "UV"]
SPACE_ITEMS = ["物体", "视图", "纹理"]

# ==========================================
# 2. 核心逻辑 (保持不变)
# ==========================================
def get_current_tool_id():
    main_win = substance_painter.ui.get_main_window()
    if not main_win or not shiboken.isValid(main_win): return None
    
    # 【优化】精准定位：只在左侧工具栏（Toolbar）中寻找
    # 通常工具栏的 objectName 包含 "Toolbar"
    toolbar = main_win.findChild(QtWidgets.QToolBar, "Toolbar") 
    search_scope = toolbar if toolbar and shiboken.isValid(toolbar) else main_win
    
    buttons = search_scope.findChildren(QtWidgets.QToolButton)
    for btn in buttons:
        if shiboken.isValid(btn) and btn.isChecked():
            action = btn.defaultAction()
            if action:
                action_id = action.objectName()
                # 【优化】排除掉插件自身的按钮或常见的干扰 ID
                if action_id and not action_id.startswith("qt_") and action_id != "enable":
                    return action_id
    return None

_sync_error_logged = False
_tick_count = 0
_tool_buttons = []


def run_sync():
    """定时入口：内部异常只记录一次，避免每 200ms 刷屏。"""
    global _sync_error_logged, _tick_count
    _tick_count += 1
    # 工具栏可能被 Painter 重建，定期重挂 toggled 连接。
    if _tick_count % 50 == 0:
        _install_tool_buttons()
    try:
        _run_sync()
        _sync_error_logged = False
    except Exception as exc:
        if not _sync_error_logged:
            _sync_error_logged = True
            sp_logging.warning(f"映射校准助手同步异常: {exc}")


def _run_sync():
    if not substance_painter.project.is_open(): return

    cfg = QtCore._auto_align_cfg
    if not cfg['enabled']: return
    current_id = get_current_tool_id()
    matched_group = None
    for group_name, id_list in TOOL_LOGIC_GROUPS.items():
        if current_id in id_list:
            matched_group = group_name
            break
    if not matched_group or not cfg['active_groups'].get(matched_group, False):
        return

    pos = QtGui.QCursor.pos()
    widget = QtWidgets.QApplication.widgetAt(pos)
    view_type = None
    if widget and shiboken.isValid(widget):
        curr = widget
        for _ in range(8):
            if not curr or not shiboken.isValid(curr): break
            name = curr.objectName()
            if name == "Viewer3D": view_type = "3D"; break
            if name == "TextureViewer": view_type = "2D"; break
            curr = curr.parentWidget()
    if current_id == cfg['last_tool'] and view_type == cfg['last_view']:
        return
    if view_type:
        prefix = "3" if view_type == "3D" else "2"
        target_a = cfg[f'{prefix}A']
        target_s = cfg[f'{prefix}S']
        main_win = substance_painter.ui.get_main_window()
        applied = False
        if main_win and shiboken.isValid(main_win):
            tool_panel = main_win.findChild(QtWidgets.QWidget, "Tool")
            if tool_panel and shiboken.isValid(tool_panel):
                combos = tool_panel.findChildren(QtWidgets.QComboBox)
                for cb in combos:
                    # 面板关闭时控件不可见：不写入也不触发 activated，
                    # 避免 Painter 在回调里重建面板导致访问越界崩溃。
                    if not shiboken.isValid(cb) or not cb.isVisible(): continue
                    obj_name = cb.objectName().lower()
                    if "alignment" in obj_name:
                        applied = True
                        if cb.currentIndex() != target_a:
                            cb.setCurrentIndex(target_a)
                            cb.activated.emit(target_a)
                    if "size_space" in obj_name:
                        applied = True
                        if cb.currentIndex() != target_s:
                            cb.setCurrentIndex(target_s)
                            cb.activated.emit(target_s)
                # 只有真正在可见面板上应用成功才记录状态；
                # 面板关闭/控件不可见时不记录，下个周期继续尝试，
                # 面板重新打开后会立即补上当前工具的预设。
                if applied:
                    cfg['last_tool'] = current_id
                    cfg['last_view'] = view_type
    else:
        cfg['last_tool'] = current_id
        cfg['last_view'] = view_type


def _on_tool_toggled(_checked=False):
    # 工具切换后只延迟调度，不在信号回调里执行任何宿主控件操作。
    QtCore.QTimer.singleShot(0, run_sync)


def _install_tool_buttons():
    """把工具栏工具按钮的 toggled 接到同步入口（幂等，可重复调用）。"""
    global _tool_buttons
    _tool_buttons = [btn for btn in _tool_buttons if shiboken.isValid(btn)]
    main_win = substance_painter.ui.get_main_window()
    if not main_win or not shiboken.isValid(main_win):
        return
    toolbar = main_win.findChild(QtWidgets.QToolBar, "Toolbar")
    scope = toolbar if toolbar and shiboken.isValid(toolbar) else main_win
    for btn in scope.findChildren(QtWidgets.QToolButton):
        if not shiboken.isValid(btn) or btn in _tool_buttons:
            continue
        action = btn.defaultAction()
        if not action:
            continue
        action_id = action.objectName()
        if not action_id or action_id.startswith("qt_") or action_id == "enable":
            continue
        try:
            btn.toggled.connect(_on_tool_toggled)
            _tool_buttons.append(btn)
        except RuntimeError:
            pass


# ==========================================
# 3. UI 类 (修正销毁回调)
# ==========================================
class AlignControl(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(substance_painter.ui.get_main_window())
        self.setObjectName("MappingAlignHelperUI")
        self.setWindowTitle("映射校准助手")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose) # 确保关闭时释放内存
        self.setMinimumWidth(380)
        self.cfg = QtCore._auto_align_cfg
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        credit = QtWidgets.QLabel(
            '<a href="https://space.bilibili.com/281243426" '
            'style="color: #66aaff;">'
            "本插件由 bilibili 神说要凑数 制作，点击可查看作者主页</a>",
            self,
        )
        credit.setOpenExternalLinks(True)
        credit.setToolTip("打开 bilibili 作者主页")
        layout.addWidget(credit)

        tool_group = QtWidgets.QGroupBox("受影响的工具")
        grid_layout = QtWidgets.QGridLayout(tool_group)
        group_names = ["绘画", "几何体填充", "橡皮", "涂抹", "沿路径绘制", "克隆", "映射", "材质选择器"]
        for index, name in enumerate(group_names):
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(self.cfg['active_groups'].get(name, False))
            cb.toggled.connect(lambda s, n=name: self.cfg['active_groups'].update({n: s}))
            grid_layout.addWidget(cb, index // 2, index % 2)
        layout.addWidget(tool_group)

        def make_group(title, a_key, s_key):
            group = QtWidgets.QGroupBox(title)
            gl = QtWidgets.QGridLayout(group)
            gl.addWidget(QtWidgets.QLabel("校准"), 0, 0)
            ca = QtWidgets.QComboBox(); ca.addItems(ALIGN_ITEMS)
            ca.setCurrentIndex(self.cfg[a_key]); ca.activated.connect(lambda i: self.cfg.update({a_key: i}))
            gl.addWidget(ca, 0, 1)
            gl.addWidget(QtWidgets.QLabel("间距大小"), 1, 0)
            cs = QtWidgets.QComboBox(); cs.addItems(SPACE_ITEMS)
            cs.setCurrentIndex(self.cfg[s_key]); cs.activated.connect(lambda i: self.cfg.update({s_key: i}))
            gl.addWidget(cs, 1, 1)
            gl.setColumnStretch(1, 1)
            layout.addWidget(group)

        make_group("3D 视图预设", '3A', '3S')
        make_group("2D 视图预设", '2A', '2S')

        self.btn = QtWidgets.QPushButton()
        self.btn.setCheckable(True); self.btn.setChecked(self.cfg['enabled'])
        self.btn.setFixedHeight(38); self.btn.toggled.connect(self.toggle_sync)
        layout.addWidget(self.btn)
        self.update_style(self.cfg['enabled'])

    def update_style(self, on):
        self.btn.setText("自动校准运行中 (点击停止)" if on else "启用自动校准")
        self.btn.setStyleSheet("background: #2D5A27; color: white; font-weight: bold; border-radius: 4px;" if on else "")

    def toggle_sync(self, c):
        self.cfg['enabled'] = c
        self.update_style(c)

    def closeEvent(self, event):
        global _ui_inst
        _ui_inst = None # 窗口关闭时清除全局引用
        super().closeEvent(event)

# ==========================================
# 4. 生命周期管理 (加强版销毁逻辑)
# ==========================================
_timer = None
_ui_inst = None

def start_plugin():
    global _timer, _tick_count
    # 防止重复启动产生多个定时器（Painter 可能重复调用插件入口）。
    if _timer is not None:
        try:
            _timer.stop()
            _timer.timeout.disconnect()
            _timer.deleteLater()
        except Exception:
            pass
        _timer = None
    main_win = substance_painter.ui.get_main_window()
    if not main_win:
        QtCore.QTimer.singleShot(1000, start_plugin)
        return
    remove_menu()
    _tick_count = 0
    _install_tool_buttons()
    action = main_win.menuBar().addAction("映射校准助手")
    action.setObjectName("MappingHelperAction")
    action.triggered.connect(show_ui)
    _timer = QtCore.QTimer()
    _timer.timeout.connect(run_sync)
    _timer.start(200)
    sp_logging.info(">>> 映射校准助手已启用")

def remove_menu():
    """彻底清理菜单动作"""
    main_win = substance_painter.ui.get_main_window()
    if not main_win: return
    # 遍历所有动作，根据 ObjectName 或文本彻底删除
    for a in main_win.menuBar().actions():
        if a.objectName() == "MappingHelperAction" or a.text() == "映射校准助手":
            main_win.menuBar().removeAction(a)
            a.deleteLater()

def close_plugin():
    """安全、彻底地销毁所有插件资源"""
    global _timer, _ui_inst, _tool_buttons
    
    # 1. 先停掉定时器，防止销毁过程中触发 run_sync 导致崩溃
    if _timer:
        try:
            _timer.stop()
            _timer.timeout.disconnect()
        except: pass
        _timer.deleteLater()
        _timer = None

    # 2. 断开工具按钮信号
    for btn in _tool_buttons:
        try:
            if shiboken.isValid(btn):
                btn.toggled.disconnect(_on_tool_toggled)
        except (RuntimeError, TypeError):
            pass
    _tool_buttons = []

    # 3. 销毁 UI 窗口
    if _ui_inst is not None:
        try:
            if shiboken.isValid(_ui_inst):
                _ui_inst.close()
                _ui_inst.deleteLater()
        except: pass
        _ui_inst = None

    # 4. 移除菜单栏入口
    try:
        remove_menu()
    except: pass
    
    sp_logging.info(">>> 映射校准助手已关闭")

def show_ui():
    global _ui_inst
    if _ui_inst and not shiboken.isValid(_ui_inst):
        _ui_inst = None
    if _ui_inst is None:
        _ui_inst = AlignControl()
    _ui_inst.show()
    _ui_inst.raise_()
    _ui_inst.activateWindow()

if __name__ == "__main__":
    start_plugin()

# -*- coding: utf-8 -*-
"""
sp_tools — Substance 3D Painter 属性面板图层工具插件（混合式架构）

架构：
  * C++ 原生模块（packages/sp_tools_delegate_qt6.dll）负责界面：
    查找属性面板通道按钮、注入“每通道 混合模式 + 不透明度”控件面板、
    控件生命周期与面板被重建后的自动重注入。
  * Python 负责数据：读写图层的混合模式与不透明度（sp.layerstack），
    通过 ctypes 与 C++ 双向同步（通道列表 / 当前值下行，控件改动上行）。

支持：Adobe Substance 3D Painter 10.1+（PySide6 / Qt6）。
"""

import ctypes
import os
import re
import time

import substance_painter as sp

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    QT_MAJOR = 6
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    QT_MAJOR = 5

try:
    from shiboken6 import getCppPointer, isValid as _is_valid
except ImportError:
    from shiboken2 import getCppPointer, isValid as _is_valid

QAction = QtWidgets.QAction if QT_MAJOR == 5 else QtGui.QAction

PLUGIN_DISPLAY_NAME = "属性面板图层工具"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGES_DIR = os.path.join(PLUGIN_DIR, "packages")
DELEGATE_DLL_PATH = os.path.join(PACKAGES_DIR, "sp_layer_tools_delegate_qt6.dll")

# 通道按钮文字：中文直接匹配，英文按包含关系匹配
CHANNEL_KEYS = ("颜色", "金属度", "粗糙度", "法线", "高度")
CHANNEL_KEYS_EN = (
    "color", "metallic", "roughness", "normal", "height",
    "metal", "rough", "nrm", "basecolor", "base",
)

# 通道按钮文字缩写/别名 → 通道名（适配 Painter 英文缩写 color/metal/rough/nrm/height）
CHANNEL_TEXT_ALIASES = {
    "color": "BaseColor",
    "basecolor": "BaseColor",
    "base": "BaseColor",
    "颜色": "BaseColor",
    "metal": "Metallic",
    "metallic": "Metallic",
    "金属度": "Metallic",
    "rough": "Roughness",
    "roughness": "Roughness",
    "粗糙度": "Roughness",
    "nrm": "Normal",
    "normal": "Normal",
    "法线": "Normal",
    "height": "Height",
    "高度": "Height",
}

# 混合模式中文名；键为“去符号小写”形式，兼容 PASS_THROUGH / PASSTHROUGH 等写法
BLEND_MODE_NAMES = {
    "normal": "正常",
    "passthrough": "穿透",
    "disable": "禁用",
    "replace": "替换",
    "multiply": "正片叠底",
    "divide": "除法",
    "inversedivide": "反向除法",
    "darken": "变暗",
    "lighten": "变亮",
    "lineardodge": "线性减淡",
    "subtract": "减去",
    "inversesubtract": "反向减去",
    "difference": "差值",
    "exclusion": "排除",
    "signedaddition": "有符号叠加",
    "overlay": "叠加",
    "screen": "滤色",
    "linearburn": "线性加深",
    "colorburn": "颜色加深",
    "colordodge": "颜色减淡",
    "softlight": "柔光",
    "hardlight": "强光",
    "vividlight": "亮光",
    "linearlight": "线性光",
    "pinlight": "点光",
    "tint": "色调",
    "saturation": "饱和度",
    "color": "颜色",
    "value": "明度",
    "normalmapcombine": "法线贴图合并",
    "normalmapdetail": "法线贴图细节",
    "normalmapinversedetail": "法线贴图反向细节",
}

CHANNEL_BY_KEY = [
    (("颜色", "basecolor", "color", "base"), "BaseColor"),
    (("金属度", "metallic", "metal"), "Metallic"),
    (("粗糙度", "roughness", "rough"), "Roughness"),
    (("法线", "normal", "nrm"), "Normal"),
    (("高度", "height"), "Height"),
]

STANDARD_CHANNEL_DISPLAY = {
    "basecolor": "颜色",
    "color": "颜色",
    "metallic": "金属度",
    "roughness": "粗糙度",
    "normal": "法线",
    "height": "高度",
    "opacity": "不透明度",
    "emissive": "自发光",
    "ao": "环境光遮蔽",
    "displacement": "置换",
    "glossiness": "光泽度",
    "specular": "高光",
    "specularedgecolor": "高光边缘颜色",
    "translucency": "半透明",
    "scattering": "散射",
    "scattercolor": "散射颜色",
    "transmissive": "透射",
    "reflection": "反射",
    "ior": "折射率",
    "diffuse": "漫反射",
    "specularlevel": "高光级别",
    "anisotropylevel": "各向异性级别",
    "anisotropyangle": "各向异性角度",
    "sheenopacity": "光泽不透明度",
    "sheenroughness": "光泽粗糙度",
    "sheencolor": "光泽颜色",
    "coatopacity": "涂层不透明度",
    "coatcolor": "涂层颜色",
    "coatroughness": "涂层粗糙度",
    "coatnormal": "涂层法线",
    "blendingmask": "混合遮罩",
    "bentnormals": "弯曲法线",
    "curvature": "曲率",
    "thickness": "厚度",
    "position": "位置",
    "id": "ID",
    "worldspacenormal": "世界空间法线",
}


def _safe(obj):
    try:
        return obj is not None and _is_valid(obj)
    except Exception:
        return False


def _clean(text):
    return re.sub(r"\s+", "", str(text or "")).replace("&", "")


def _normalize(name):
    # 保留中文字符，方便匹配中文标签
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", str(name).lower())


def _is_channel_button(button):
    text = _clean(button.text())
    if not text:
        return False
    if text in CHANNEL_KEYS:
        return True
    normalized = _normalize(text)
    return any(key in normalized for key in CHANNEL_KEYS_EN)


def _channel_display_name(channel):
    """通道的显示名：标准通道用中文映射，User 通道用自定义标签。"""
    name = getattr(channel, "name", "") or ""
    normalized = _normalize(name)
    display = STANDARD_CHANNEL_DISPLAY.get(normalized)
    if display:
        return display
    try:
        label = channel.label()
        if label and label.strip():
            return label.strip()
    except Exception:
        pass
    return name


def _channel_text_keys(channel):
    """生成一个通道所有可能的按钮文字匹配键。"""
    keys = set()
    name = getattr(channel, "name", "") or ""
    keys.add(_normalize(name))
    display = STANDARD_CHANNEL_DISPLAY.get(_normalize(name))
    if display:
        keys.add(_normalize(display))
    try:
        label = channel.label()
        if label and label.strip():
            keys.add(_normalize(label))
    except Exception:
        pass
    return keys


def _build_channel_list():
    """读取当前图层栈的通道列表（保持通道集顺序）。"""
    try:
        stack = sp.textureset.get_active_stack()
        return list(stack.all_channels().keys())
    except Exception:
        return []


def _match_button_to_channel(button, channel_by_key):
    """按按钮文字匹配通道（支持中文、英文、User 自定义标签）。"""
    text = _clean(button.text())
    normalized = _normalize(text)
    if not normalized:
        return None
    alias = CHANNEL_TEXT_ALIASES.get(normalized)
    if alias:
        alias_norm = _normalize(alias)
        for channel in channel_by_key:
            channel_name = _normalize(getattr(channel, "name", "") or "")
            if channel_name == alias_norm:
                return channel
    for channel, keys in channel_by_key.items():
        for key in keys:
            if key and (key in normalized or normalized in key):
                return channel
    return None


def _enum_member(enum, name):
    """按多种命名写法解析枚举成员（PASS_THROUGH / Passthrough / passthrough…）。"""
    if not name:
        return None
    variants = [name, name.upper(), name.lower(), name.title()]
    compact = re.sub(r"[_\- ]", "", name)
    variants += [compact, compact.upper(), compact.lower()]
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    variants += [snake, snake.upper(), snake.lower()]
    for candidate in variants:
        member = getattr(enum, candidate, None)
        if member is not None:
            return member
    return None


def _channel_for_button(button):
    """根据按钮文字推断标准通道（返回 ChannelType 成员）。"""
    text = _clean(button.text())
    if not text:
        return None
    normalized = _normalize(text)
    channel_name = None
    for keys, channel in CHANNEL_BY_KEY:
        if text in keys or any(key in normalized for key in keys):
            channel_name = channel
            break
    if channel_name is None:
        return None
    return _enum_member(sp.textureset.ChannelType, channel_name)


def _map_buttons_to_channels(buttons):
    """把通道按钮映射到实际的 ChannelType，支持 User0/User1 等自定义通道。"""
    channels = _build_channel_list()
    if channels:
        # 1) 按按钮文字匹配（按钮顺序可能与通道集顺序不同）
        channel_by_key = {
            channel: _channel_text_keys(channel) for channel in channels
        }
        pairs = []
        for button in buttons:
            channel = _match_button_to_channel(button, channel_by_key)
            if channel is not None:
                pairs.append((button, channel))
        if len(pairs) >= 3:
            return pairs
        # 2) 文字匹配不足时退回按顺序配对
        if len(buttons) == len(channels):
            return list(zip(buttons, channels))
        return pairs
    # 3) 没有活动项目：按默认五个标准通道匹配
    pairs = []
    for button in buttons:
        channel = _channel_for_button(button)
        if channel is not None:
            pairs.append((button, channel))
    return pairs


def _find_channel_groups(widget):
    """在控件树中找出“通道按钮组”（仅可见按钮），按命中数量排序。"""
    groups = {}
    for button in widget.findChildren(QtWidgets.QAbstractButton):
        if not _safe(button):
            continue
        try:
            if not button.isVisible():
                continue
        except Exception:
            continue
        if not _is_channel_button(button):
            continue
        parent = button.parentWidget()
        if not _safe(parent):
            parent = widget
        entry = groups.setdefault(id(parent), [parent, []])
        entry[1].append(button)
    result = [entry for entry in groups.values() if len(entry[1]) >= 3]
    result.sort(key=lambda entry: len(entry[1]), reverse=True)
    return result


def _find_channel_bar(panel):
    """返回 (通道栏容器, 全部可见通道按钮)，包含 User0/User1 等自定义通道。"""
    groups = _find_channel_groups(panel)
    if not groups:
        return None, []
    container, standard = groups[0]
    buttons = [
        child for child in container.children()
        if (isinstance(child, QtWidgets.QAbstractButton) and _safe(child)
            and child.isVisible())
    ]
    if not buttons:
        buttons = [
            child for child in container.findChildren(QtWidgets.QAbstractButton)
            if _safe(child) and child.isVisible()
        ]
    if not buttons:
        buttons = standard
    buttons.sort(key=lambda b: (b.geometry().y(), b.geometry().x()))
    return container, buttons


def _find_properties_panel():
    app = QtWidgets.QApplication.instance()
    if not _safe(app):
        return None
    dock_candidates = []
    class_candidates = []
    for widget in app.allWidgets():
        if not _safe(widget):
            continue
        if isinstance(widget, QtWidgets.QDockWidget):
            try:
                title = widget.windowTitle() or ""
            except Exception:
                continue
            if "属性" in title or "properties" in _normalize(title):
                dock_candidates.append(widget)
        else:
            try:
                class_name = widget.metaObject().className() or ""
            except Exception:
                class_name = ""
            if "Properties" in class_name and "Widget" in class_name:
                class_candidates.append(widget)
    for panel in dock_candidates + class_candidates:
        groups = _find_channel_groups(panel)
        if groups:
            return panel
    if dock_candidates:
        return dock_candidates[0]
    for widget in app.allWidgets():
        if not _safe(widget):
            continue
        groups = _find_channel_groups(widget)
        if groups:
            return widget
    return None


def _find_layers_panel():
    app = QtWidgets.QApplication.instance()
    if not _safe(app):
        return None
    for widget in app.allWidgets():
        if not _safe(widget):
            continue
        if isinstance(widget, QtWidgets.QDockWidget):
            try:
                title = widget.windowTitle() or ""
            except Exception:
                continue
            if "图层" in title or "layers" in _normalize(title):
                return widget
    return None


def _class_of(widget):
    try:
        return widget.metaObject().className() or type(widget).__name__
    except Exception:
        return type(widget).__name__


def _parent_chain_text(widget):
    chain = []
    current = widget
    for _depth in range(8):
        if not _safe(current):
            break
        try:
            name = current.objectName() or ""
        except Exception:
            name = ""
        chain.append(f"{_class_of(current)}({name})")
        try:
            current = current.parentWidget()
        except Exception:
            break
        if not _safe(current):
            break
    return " <- ".join(chain)


# ==========================================
# ctypes 绑定 C++ 原生模块
# ==========================================
_native = None
_VALUE_CALLBACK_TYPE = ctypes.CFUNCTYPE(
    None, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_double
)
_RESOLVE_CALLBACK_TYPE = ctypes.CFUNCTYPE(
    None, ctypes.c_int, ctypes.POINTER(ctypes.c_wchar_p)
)
_VALUE_REQUEST_TYPE = ctypes.CFUNCTYPE(None)
_LAYER_CONTROLS_CALLBACK_TYPE = ctypes.CFUNCTYPE(None)
_value_callback_handle = None
_resolve_callback_handle = None
_value_request_handle = None
_layer_controls_handle = None
_NATIVE_CHANNELS = []  # [(ChannelType, label)]，顺序与按钮一致


def _load_native():
    global _native
    if _native is not None:
        return _native
    try:
        dll = ctypes.CDLL(DELEGATE_DLL_PATH)
        dll.sp_tools_api_version.restype = ctypes.c_int
        dll.sp_tools_set_enabled.argtypes = [ctypes.c_int]
        dll.sp_tools_set_enabled.restype = None
        dll.sp_tools_set_value_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_value_callback.restype = None
        dll.sp_tools_set_resolve_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_resolve_callback.restype = None
        dll.sp_tools_set_value_request_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_value_request_callback.restype = None
        dll.sp_tools_set_layer_controls_callback.argtypes = [ctypes.c_void_p]
        dll.sp_tools_set_layer_controls_callback.restype = None
        dll.sp_tools_set_selected_layer_name.argtypes = [ctypes.c_wchar_p]
        dll.sp_tools_set_selected_layer_name.restype = None
        dll.sp_tools_check_channels.argtypes = []
        dll.sp_tools_check_channels.restype = None
        dll.sp_tools_set_blend_modes.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        dll.sp_tools_set_blend_modes.restype = None
        dll.sp_tools_set_channels.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        dll.sp_tools_set_channels.restype = None
        dll.sp_tools_set_value.argtypes = [
            ctypes.c_int, ctypes.c_wchar_p, ctypes.c_double
        ]
        dll.sp_tools_set_value.restype = None
        dll.sp_tools_reinject.argtypes = []
        dll.sp_tools_reinject.restype = None
        dll.sp_tools_install.argtypes = [ctypes.c_void_p]
        dll.sp_tools_install.restype = ctypes.c_int
        if dll.sp_tools_api_version() != 3:
            print(">>> sp_tools: 原生模块 API 版本不匹配")
            return None
        _native = dll
    except Exception as exc:
        print(">>> sp_tools 原生模块加载失败:", exc)
        _native = None
    return _native


def _wstr_array(strings):
    array = (ctypes.c_wchar_p * len(strings))()
    for i, value in enumerate(strings):
        array[i] = str(value)
    return array


def _on_value_changed(index, mode_name, opacity):
    """C++ 控件改动回调：把新值写回当前图层的对应通道。"""
    try:
        layer = _selected_layer()
        if layer is None:
            return
        if index < 0 or index >= len(_NATIVE_CHANNELS):
            return
        channel = _NATIVE_CHANNELS[index][0]
        with sp.layerstack.ScopedModification("sp_tools 调整图层"):
            mode = (_enum_member(sp.layerstack.BlendingMode, mode_name)
                    if mode_name else None)
            if mode is not None and layer.get_blending_mode(channel) != mode:
                layer.set_blending_mode(mode, channel)
            if opacity is not None and opacity >= 0.0:
                opacity_value = opacity / 100.0
                if abs(layer.get_opacity(channel) - opacity_value) > 1e-6:
                    layer.set_opacity(opacity_value, channel)
    except Exception as exc:
        print(">>> sp_tools 应用图层参数失败:", exc)


class _ButtonText:
    """把按钮文字包装成按钮对象，供通道匹配函数使用。"""

    def __init__(self, text):
        self._text = str(text or "")

    def text(self):
        return self._text


def _on_resolve_channels(count, texts):
    """C++ 请求解析通道：按按钮文字匹配通道并回填 C++。"""
    global _NATIVE_CHANNELS
    dll = _load_native()
    if dll is None:
        return
    try:
        buttons = [_ButtonText(texts[i]) for i in range(count)]
        pairs = _map_buttons_to_channels(buttons)
        _NATIVE_CHANNELS = [(channel, _channel_display_name(channel))
                            for _button, channel in pairs]
        ids = [getattr(channel, "name", "") or ""
               for channel, _label in _NATIVE_CHANNELS]
        labels = [label for _channel, label in _NATIVE_CHANNELS]
        dll.sp_tools_set_channels(len(ids), _wstr_array(ids),
                                  _wstr_array(labels))
    except Exception as exc:
        print(">>> sp_tools 解析通道失败:", exc)


def _on_value_request():
    """C++ 控件面板就绪后请求当前图层各通道的值。"""
    _sync_values_to_native()


def _on_layer_controls_changed():
    """图层面板里的混合模式/不透明度控件发生变化：重新同步我们的控件。"""
    _sync_values_to_native()


def _selected_layer():
    try:
        stack = sp.textureset.get_active_stack()
        for node in sp.layerstack.get_selected_nodes(stack):
            if hasattr(node, "has_blending") and node.has_blending():
                return node
    except Exception:
        return None
    return None


def _sync_blend_modes_to_native():
    dll = _load_native()
    if dll is None:
        return
    enum = sp.layerstack.BlendingMode
    member_map = getattr(enum, "__members__", None)
    entries = []
    if isinstance(member_map, dict):
        for name, _member in member_map.items():
            entries.append((name, BLEND_MODE_NAMES.get(_normalize(name), name)))
    else:
        for key, label in BLEND_MODE_NAMES.items():
            member = _enum_member(enum, key)
            if member is not None:
                entries.append((member.name, label))
    entries.sort(key=lambda item: (0 if item[1] == "正常"
                                   else 1 if item[1] == "穿透"
                                   else 2, item[1]))
    names = [name for name, _label in entries]
    labels = [label for _name, label in entries]
    dll.sp_tools_set_blend_modes(len(entries), _wstr_array(names),
                                 _wstr_array(labels))


def _sync_values_to_native():
    dll = _load_native()
    if dll is None:
        return
    try:
        layer = _selected_layer()
        layer_name = ""
        if layer is not None:
            try:
                layer_name = layer.get_name() or ""
            except Exception:
                layer_name = ""
        # 把当前图层名同步给 C++，用于在图层面板中定位选中图层行
        dll.sp_tools_set_selected_layer_name(layer_name)
        for index, (channel, _label) in enumerate(_NATIVE_CHANNELS):
            if layer is None:
                dll.sp_tools_set_value(index, "", -1.0)
                continue
            try:
                mode = layer.get_blending_mode(channel)
                opacity = layer.get_opacity(channel) * 100.0
                dll.sp_tools_set_value(index,
                                       getattr(mode, "name", "") or "",
                                       opacity)
            except Exception:
                dll.sp_tools_set_value(index, "", -1.0)
    except Exception as exc:
        print(">>> sp_tools 同步图层值失败:", exc)


# ==========================================
# 事件与生命周期
# ==========================================
_ACTION = None
_DUMP_ACTION = None
_MENU_BAR = None
_STACK_PENDING = False
_LAST_DUMP_TIME = 0.0
_DUMP_TIMER = None


def _maybe_auto_dump():
    """节流自动导出面板结构报告（至少间隔 3 秒）。"""
    global _LAST_DUMP_TIME
    now = time.time()
    if now - _LAST_DUMP_TIME < 3.0:
        return
    _LAST_DUMP_TIME = now
    dump_panel_tree()


def _periodic_dump_check():
    """兜底：有项目且选中了图层时，周期更新面板结构报告。"""
    try:
        stack = sp.textureset.get_active_stack()
        if not sp.layerstack.get_selected_nodes(stack):
            return
    except Exception:
        return
    _maybe_auto_dump()


def _on_stack_changed(_event):
    global _STACK_PENDING
    if _STACK_PENDING:
        return
    _STACK_PENDING = True
    QtCore.QTimer.singleShot(80, _stack_changed_debounced)


def _stack_changed_debounced():
    global _STACK_PENDING
    _STACK_PENDING = False
    dll = _load_native()
    if dll is None:
        return
    dll.sp_tools_check_channels()
    # 图层切换后 API 的选择状态可能稍后才就绪，分段补推保证立即刷新
    _sync_values_to_native()
    QtCore.QTimer.singleShot(200, _sync_values_to_native)
    QtCore.QTimer.singleShot(600, _sync_values_to_native)
    # 有图层活动的状态下自动更新面板结构报告（节流）
    QtCore.QTimer.singleShot(400, _maybe_auto_dump)


def _on_project_opened(_event):
    QtCore.QTimer.singleShot(200, _project_opened_debounced)


def _project_opened_debounced():
    dll = _load_native()
    if dll is None:
        return
    dll.sp_tools_set_enabled(1)
    dll.sp_tools_reinject()
    # 项目打开后自动更新面板结构报告（此时通常已选中图层）
    QtCore.QTimer.singleShot(600, lambda: dump_panel_tree())


def _on_project_closing(_event):
    dll = _load_native()
    if dll is not None:
        dll.sp_tools_set_enabled(0)


def _force_refresh():
    dll = _load_native()
    if dll is None:
        return
    dll.sp_tools_set_enabled(1)
    dll.sp_tools_reinject()


def dump_panel_tree(panel=None):
    """诊断：把属性面板 + 图层面板的完整信息写入插件目录下的报告文件。

    全程逐控件防御：任何控件失效/被销毁都跳过，不中断，最后必定写文件。
    """
    report = os.path.join(PLUGIN_DIR, "properties_panel_report.txt")
    lines = []
    errors = []
    lines.append("=== sp_tools 属性面板诊断 ===")
    lines.append("时间: " + time.strftime("%Y-%m-%d %H:%M:%S"))

    def safe_props(widget):
        try:
            class_name = _class_of(widget)
            object_name = widget.objectName() or ""
            text = ""
            if hasattr(widget, "text"):
                text = widget.text()
            return class_name, object_name, str(text)[:40]
        except Exception:
            return None

    def walk(widget, depth):
        if not _safe(widget) or depth > 24:
            return
        props = safe_props(widget)
        if props is None:
            return
        class_name, object_name, text = props
        lines.append(
            f"{'  ' * depth}[{depth}] {class_name} "
            f"object={object_name!r} text={text!r}"
        )
        try:
            children = widget.children()
        except Exception:
            return
        for child in children:
            if isinstance(child, QtWidgets.QWidget):
                walk(child, depth + 1)

    def dump_buttons(root, label):
        lines.append(f"--- {label}全部带文字按钮 ---")
        try:
            buttons = root.findChildren(QtWidgets.QAbstractButton)
        except Exception:
            return
        for button in buttons:
            if not _safe(button):
                continue
            try:
                button_text = button.text()
            except Exception:
                continue
            if not button_text.strip():
                continue
            lines.append(
                f"按钮 text={button_text!r} "
                f"父链={_parent_chain_text(button)}"
            )

    def dump_value_widgets(root, label):
        lines.append(f"--- {label}数值/输入控件 ---")
        found = []
        try:
            for widget in root.findChildren(QtWidgets.QAbstractSpinBox):
                if _safe(widget):
                    found.append(widget)
            for widget in root.findChildren(QtWidgets.QLineEdit):
                if _safe(widget):
                    found.append(widget)
        except Exception:
            pass
        for widget in found:
            if not _safe(widget):
                continue
            try:
                value = widget.text()
                object_name = widget.objectName() or ""
            except Exception:
                continue
            lines.append(
                f"控件 {_class_of(widget)} object={object_name!r} "
                f"值={value!r} 父链={_parent_chain_text(widget)}"
            )

    try:
        stack = sp.textureset.get_active_stack()
        selected = sp.layerstack.get_selected_nodes(stack)
        lines.append(f"选中节点数: {len(selected)}")
        lines.append("通道集: " + ", ".join(
            _channel_display_name(channel)
            for channel in stack.all_channels().keys()
        ))
    except Exception as exc:
        lines.append(f"图层栈读取失败: {exc}")

    try:
        if panel is None:
            panel = _find_properties_panel()
        if not _safe(panel):
            lines.append("未找到属性面板")
        else:
            lines.append(
                "属性面板: " + _class_of(panel)
                + " object=" + repr(panel.objectName())
            )
            lines.append("--- 属性面板控件树 ---")
            walk(panel, 0)
            dump_buttons(panel, "属性面板")
            dump_value_widgets(panel, "属性面板")
            lines.append("--- 材质参数视图布局 ---")
            try:
                widgets = panel.findChildren(QtWidgets.QWidget)
            except Exception:
                widgets = []
            for widget in widgets:
                if not _safe(widget):
                    continue
                class_name = _class_of(widget)
                object_name = ""
                try:
                    object_name = widget.objectName() or ""
                except Exception:
                    pass
                if (class_name in ("Alg::MaterialParametersView",
                                   "Alg::MonoChannelParametersView")
                        or object_name in ("materialView", "grayscaleView",
                                           "frame", "grayscaleSource",
                                           "materialModeParams",
                                           "channelButtons")):
                    try:
                        layout = widget.layout()
                        lines.append(
                            f"{class_name} object={object_name!r} "
                            f"布局={type(layout).__name__ if layout else '无'} "
                            f"条目数={layout.count() if layout else 0}"
                        )
                    except Exception:
                        pass
    except Exception as exc:
        errors.append(f"属性面板部分失败: {exc}")

    try:
        layers_panel = _find_layers_panel()
        if not _safe(layers_panel):
            lines.append("未找到图层面板")
        else:
            lines.append(
                "图层面板: " + _class_of(layers_panel)
                + " object=" + repr(layers_panel.objectName())
            )
            lines.append("--- 图层面板控件树 ---")
            walk(layers_panel, 0)
            dump_buttons(layers_panel, "图层面板")
            dump_value_widgets(layers_panel, "图层面板")
    except Exception as exc:
        errors.append(f"图层面板部分失败: {exc}")

    if errors:
        lines.append("--- 部分失败 ---")
        lines.extend(errors)

    try:
        with open(report, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
        print(f">>> sp_tools: 面板结构报告已写入 {report}（{len(lines)} 行）")
    except Exception as exc:
        print(">>> sp_tools: 写面板报告失败:", exc)


def start_plugin():
    global _ACTION, _DUMP_ACTION, _MENU_BAR
    global _value_callback_handle, _resolve_callback_handle
    global _value_request_handle, _layer_controls_handle, _DUMP_TIMER
    app = QtWidgets.QApplication.instance()
    main_window = sp.ui.get_main_window()
    if not _safe(app) or not _safe(main_window):
        return

    close_plugin()

    try:
        dll = _load_native()
        if dll is None:
            print(">>> sp_tools: 原生模块不可用，插件未启用")
        else:
            _value_callback_handle = _VALUE_CALLBACK_TYPE(_on_value_changed)
            dll.sp_tools_set_value_callback(_value_callback_handle)
            _resolve_callback_handle = _RESOLVE_CALLBACK_TYPE(
                _on_resolve_channels)
            dll.sp_tools_set_resolve_callback(_resolve_callback_handle)
            _value_request_handle = _VALUE_REQUEST_TYPE(_on_value_request)
            dll.sp_tools_set_value_request_callback(_value_request_handle)
            _layer_controls_handle = _LAYER_CONTROLS_CALLBACK_TYPE(
                _on_layer_controls_changed)
            dll.sp_tools_set_layer_controls_callback(_layer_controls_handle)

            _sync_blend_modes_to_native()

            pointer = getCppPointer(app)[0]
            dll.sp_tools_install(ctypes.c_void_p(pointer))
            dll.sp_tools_set_enabled(1)
    except Exception as exc:
        print(">>> sp_tools 启动原生模块失败:", exc)

    _ACTION = QAction(PLUGIN_DISPLAY_NAME, main_window)
    _ACTION.triggered.connect(lambda: _force_refresh())
    _DUMP_ACTION = QAction("导出属性面板控件树", main_window)
    _DUMP_ACTION.triggered.connect(lambda: dump_panel_tree())
    _MENU_BAR = main_window.menuBar()
    _MENU_BAR.addAction(_ACTION)
    _MENU_BAR.addAction(_DUMP_ACTION)

    # 启动后自动写一份面板结构报告，便于排查（不依赖手动点击）
    QtCore.QTimer.singleShot(800, lambda: dump_panel_tree())

    _DUMP_TIMER = QtCore.QTimer()
    _DUMP_TIMER.setInterval(5000)
    _DUMP_TIMER.timeout.connect(_periodic_dump_check)
    _DUMP_TIMER.start()

    for event_cls, callback in (
        (sp.event.LayerStacksModelDataChanged, _on_stack_changed),
        (sp.event.ProjectOpened, _on_project_opened),
        (sp.event.ProjectAboutToClose, _on_project_closing),
    ):
        try:
            sp.event.DISPATCHER.connect_strong(event_cls, callback)
        except Exception as exc:
            print(">>> sp_tools 事件绑定失败:", exc)

    print(">>> sp_tools 插件已启动（C++ 界面模块 + Python 数据桥）")


def close_plugin():
    global _ACTION, _DUMP_ACTION, _MENU_BAR, _DUMP_TIMER
    if _DUMP_TIMER is not None:
        try:
            _DUMP_TIMER.stop()
        except Exception:
            pass
    _DUMP_TIMER = None
    for event_cls, callback in (
        (sp.event.LayerStacksModelDataChanged, _on_stack_changed),
        (sp.event.ProjectOpened, _on_project_opened),
        (sp.event.ProjectAboutToClose, _on_project_closing),
    ):
        try:
            sp.event.DISPATCHER.disconnect(event_cls, callback)
        except Exception:
            pass
    for action in (_ACTION, _DUMP_ACTION):
        if _safe(action):
            try:
                if _safe(_MENU_BAR):
                    _MENU_BAR.removeAction(action)
            except Exception:
                pass
    _ACTION = None
    _DUMP_ACTION = None
    _MENU_BAR = None
    dll = _load_native()
    if dll is not None:
        try:
            dll.sp_tools_set_enabled(0)
        except Exception:
            pass

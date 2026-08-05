# sp_tools — 属性面板图层工具

在 Substance 3D Painter 的“属性”面板中，于通道按钮（颜色 / 金属度 / 粗糙度 /
法线 / 高度，以及 User0/User1 等自定义通道）之后插入
“图层混合模式 + 不透明度”控件，实时作用于当前选中图层的对应通道。

## 架构（混合式）

- `packages/sp_layer_tools_delegate_qt6.dll`：C++ 界面模块，负责查找属性面板
  通道按钮、注入控件面板、面板被重建后自动重新注入，并通过 ctypes 回调把
  控件改动通知 Python。
- `__init__.py`：Python 数据桥，读写 `sp.layerstack` 的混合模式与不透明度，
  把通道列表 / 图层当前值同步给 C++。

两个插件（sp_chinese_translation、sp_tools）源码完全独立。

## 安装

把本目录（`sp_tools`）整体复制到：

```text
C:\Users\<用户名>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
```

重启 Painter，在顶部菜单 `Python` 中勾选“属性面板图层工具”。

> 原生 DLL 需要与 Painter 的 Qt6 匹配；更换 Painter 大版本后请重新编译。

## 编译原生模块

需要 Windows x64 + CMake + MSVC（Visual Studio 2022 Build Tools），
Qt6 SDK 位于 `source/qt-sdk/6.5.3/msvc2019_64`（两个插件共用工具链）：

```text
cmake -S source/sp_tools/c++ -B source/sp_tools/c++/build
cmake --build source/sp_tools/c++/build --config Release
```

编译产物 `sp_layer_tools_delegate_qt6.dll` 需放入 `packages/`。

## 使用

- 打开或新建项目后，右侧“属性”面板的通道按钮之后会出现控件；
- 选择任意图层后，控件自动读取该图层的混合模式和不透明度；
- 修改下拉框或数值框会立即写回当前图层，并进入撤销记录。

## 说明

- 插件只修改图层的显示参数（混合模式、不透明度），不修改任何项目数据文件。
- 若属性面板布局或版本发生变化导致控件未出现，点击菜单
  “属性面板图层工具”可重新注入；“导出属性面板控件树”会把面板结构写入
  `properties_panel_report.txt` 便于排查。

# Substance 3D Painter 中文翻译补全插件

这是一个适用于 Windows 版 Adobe Substance 3D Painter 的中文界面补全插件。插件会读取自带及用户添加的中文词库，对 Painter 官方汉化尚未覆盖的菜单、按钮、参数、资源目录和资产名称进行补充翻译。

插件不会覆盖 Painter 已经显示为中文的内容。Painter 7.2 至最新版的界面翻译和资源列表显示均由原生 C++ 模块处理；插件会根据 Painter 的 Qt 主版本自动选择 Qt5 或 Qt6 DLL。

## 主要功能

- 补充翻译菜单、按钮、标签、选项卡、下拉选项和参数名称。
- 翻译资产库目录树、资源列表及添加滤镜等资源选择窗口。
- 保留 Painter 官方已有的中文翻译，不重复覆盖。
- 界面动态变化或拖动参数时自动补充翻译。
- 鼠标悬停在普通翻译文字及插件汉化的菜单项上时显示英文原文。
- 资产缩略图区域保留 Painter 官方大图预览，不显示冲突的原文提示。
- `Ctrl + 鼠标右键`直接修改当前翻译，并写回该词条所属的原始 JSON 词库。
- “更改翻译”窗口显示当前控件的用途和实际 Qt 类型，并使用 Painter 当前界面配色。
- “中文翻译工具”内的“翻译图层面板”开关默认开启；图层通道、混合模式、其他控件和用户创建的图层名称使用独立规则翻译，不修改项目中保存的实际图层名称。
- 内置中文翻译工具，可扫描资源文件和 GLSL 材质元数据。
- 可通过 Painter 官方资源接口导出资产库中尚未翻译的资产名称。
- 支持加载插件 `translations` 目录下的所有 `*_zh.json` 词库。

## 适用环境

- Windows 10/11 64 位
- Adobe Substance 3D Painter 7.2 至官方最新版

兼容规则：

- Painter 7.2–10.0（Python 3.7 / PySide2 / Qt5）使用专用 Qt5 C++ 翻译引擎。
- Painter 10.1 及以后（Python 3.11 / PySide6 / Qt6）使用 Qt6 C++ 翻译引擎。
- 插件会在启动时自动识别 Qt 主版本，不需要手动选择。
- Qt5 与 Qt6 的二进制接口不兼容，因此旧版不会尝试加载 Qt6 DLL。

## 安装方法

1. 在以下目录中新建 `sp_chinese_translation` 文件夹：

   ```text
   C:\Users\你的用户名\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
   ```

2. 将发布包 `sp_chinese_translation.zip` 直接解压到这个新建文件夹。压缩包根目录就是插件内容，不再额外包含同名外层目录。

3. 安装后的入口文件应位于：

   ```text
   ...\python\plugins\sp_chinese_translation\__init__.py
   ```

4. 启动 Substance 3D Painter。
5. 打开顶部菜单 `Python`，确认“中文翻译补全插件”已勾选。

如果 Painter 在安装时正在运行，请先完全退出 Painter，再替换插件文件。原生 DLL 在 Painter 运行期间会被占用，无法安全覆盖。

## 基本使用

插件启用后会自动加载词库并翻译当前界面，无需手动执行扫描。新打开的面板、弹窗和动态参数也会自动处理。

### 查看英文原文

将鼠标悬停在插件翻译过的普通文字、菜单项、下拉框当前项、展开后的下拉选项、选项卡或停靠面板标题上，可查看对应的英文原文；鼠标离开当前控件后提示会立即隐藏。提示只对插件实际完成汉化的项目生效；Painter 自带中文内容、未翻译内容及其原有帮助提示不会被替换。

以下区域不会强制显示英文原文：

- 颜色选择框
- 数字输入框
- 滑块操作区域
- Painter 资产缩略图区域

这样可以避免覆盖 Painter 自带的参数说明或资产大图预览。资产库左侧目录树仍保留英文原文提示。

### 修改翻译

在插件已经汉化的文字上按住 `Ctrl` 并点击鼠标右键，会打开“更改翻译”窗口。窗口显示：

- 原英文
- 当前翻译
- 新翻译

保存后界面会立即刷新：

- 能确定词条来源时，新译文直接写回该词条所属的原始 `*_zh.json`。
- 无法确定词条来源时，插件会在 `translations` 目录自动创建 `user_added_zh.json` 并保存该词条。

自动创建的文件采用相同的 `sp-translation-v1` 标准结构，重启 Painter 后会作为普通 `*_zh.json` 词库自动加载。

普通鼠标右键完全交给 Painter，不会触发插件编辑窗口，也不会影响 Painter 原有右键菜单。

## 中文翻译工具

点击 Painter 顶部菜单栏中的“中文翻译工具”打开工具。图层面板翻译开关也位于此窗口中，默认开启；关闭后会恢复图层面板中由插件修改的显示文字。

中文翻译工具可执行以下操作：

- 递归扫描指定资源目录。
- 从支持的资源容器中提取 XML 元数据词条。
- 解析 `.spsm` 智能材质（HDF5）中的图层名（仅提取需要翻译的英文名）。
- 提取 `label`、`text`、`group`、`description`、`category` 等字段。
- 将 `label`、`label0`、`label1` 等统一作为 `label` 处理。
- 提取 GLSL 元数据中的 `label`、`group`、`description`、`description_disabled` 和下拉框 `values`。
- 可选提取普通文件名，默认开启。
- 可选提取文件夹名，默认关闭。
- `.sbsar`、`.spsm` 等可识别资源容器始终记录容器文件名。
- 保留已有 JSON 中已经填写的译文，新词条以空译文加入。
- XML、GLSL、文件名和文件夹名中已经包含中文的原文不会被提取；重复扫描已有输出时也会移除中文原文词条。

支持扫描的 GLSL 类扩展名包括：

```text
.glsl  .glslfx  .vert  .frag  .geom  .tesc  .tese  .comp
```

PNG、EXR、SVG、字体、QML、JavaScript 等普通资源不会解析内部代码；启用“提取普通文件名”时会记录它们的文件名。提取器不解析 ABR 文件内部的笔刷名称。

提取资源容器时使用插件内置 Python 模块，不需要安装或调用外部 7-Zip 程序。
Painter 7.2–10.0 的 Python 3.7 环境会按当前可用模块自动识别容器；即使某个二进制解析器不兼容，普通文件、XML、GLSL 和 ZIP 扫描仍会继续，不会使整个提取任务失败。

### 导出资产库未翻译名称

在词条提取器中点击“导出资产库未翻译名称”，插件会通过 Painter 官方资源 API 枚举当前所有资产架及其子资源。

以下资产不会重复导出：

- Painter 已经显示为中文的资产。
- 已加载词库中存在非空中文译文的资产。

导出结果是可直接编辑的 `*_zh.json` 文件。

## 词库格式

插件会按文件名排序加载 `translations` 文件夹中的所有 `*_zh.json`。同一英文词条出现在多个文件时，排序靠后的文件最终生效。

词库必须使用以下结构：

```json
{
  "$schema": "sp-translation-v1",
  "id": "my-translations",
  "language": "zh-CN",
  "description": "My Painter translations",
  "translations": {
    "English source": "中文翻译",
    "Another source": "另一条翻译"
  }
}
```

需要限定到特定控件类型的词条放在 `control_types` 中。一个文件可以包含多个控件类型，每个类型拥有独立词表：

```json
{
  "$schema": "sp-translation-v1",
  "id": "control-specific-translations",
  "language": "zh-CN",
  "control_types": {
    "layer_blend_mode": {
      "description": "Layer blend mode menu entries",
      "translations": {
        "Normal": "正常",
        "Multiply": "正片叠底"
      }
    },
    "another_control_type": {
      "translations": {
        "English source": "仅用于该控件的翻译"
      }
    }
  }
}
```

控件专属词条不会进入全局词典，因此相同英文在不同控件中可以使用不同译文。

要求：

- 文件名必须以 `_zh.json` 结尾。
- 文件编码为 UTF-8。
- `$schema` 必须是 `sp-translation-v1`。
- `language` 必须是 `zh-CN`。
- 空译文不会加载。
- 不支持简单的“原文: 译文”平面 JSON。

插件默认正式词库为：

```text
translations\official_assets_zh.json
```

添加或手动修改词库后，请重新加载插件或重启 Painter。

## 插件目录说明

```text
sp_chinese_translation/
├─ __init__.py                         Python 插件入口和词条提取器
├─ native/
│  ├─ sp_translation_delegate_qt6.dll  Painter 10.1+ 的 Qt6 C++ 模块
│  └─ sp_translation_delegate_qt5.dll  Painter 7.2–10.0 的 Qt5 C++ 模块
├─ packages/                           资源容器解析所需的精简 Python 依赖
├─ translations/
│  ├─ official_assets_zh.json          默认中文词库
│  ├─ control_types_zh.json             按控件类型隔离的专属词库
│  └─ user_added_zh.json               无法溯源时按需创建的用户词库
└─ THIRD_PARTY_LICENSES.txt              第三方依赖许可证（合并文件）
```

`native`（自编译 DLL）与 `packages`（第三方依赖）都属于插件运行依赖，
`THIRD_PARTY_LICENSES.txt` 是随附的第三方许可证文件，发布或安装完整功能版本时请保留。

## 卸载

1. 完全退出 Substance 3D Painter。
2. 删除以下文件夹：

   ```text
   C:\Users\你的用户名\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\sp_chinese_translation
   ```

3. 重新启动 Painter。

## 注意事项

- 替换 DLL 或整个插件前必须完全退出 Painter。
- Ctrl+右键会直接修改原词库，或在无法溯源时写入 `user_added_zh.json`；建议在大量手工调整前自行备份词库。
- 某些 Painter 控件由内部模型动态绘制，插件只改变显示文本，不修改资产本体或项目数据。
- 插件仅补充界面显示，不会修改 Substance 资源文件内容。
- 如果某个控件已经由 Painter 官方显示中文，插件会跳过该控件。

## 许可证

项目许可证见根目录 `LICENSE`。第三方组件许可证见插件包中的 `THIRD_PARTY_LICENSES.txt`。

## 仓库结构

两个插件源码各自独立：`source/sp_chinese_translation/`（含其 `c++/` 原生模块）
与 `source/sp_tools/`（含其 `c++/` 原生模块）；`source/qt-sdk` 是两个插件
共用的 Qt 构建工具链（非插件源码）。工具脚本在
`source/sp_chinese_translation/scripts/`，发布包由
`source/sp_chinese_translation/scripts/build_package.py` 生成到
`dist/sp_chinese_translation.zip`。
该脚本会先从 `source/sp_chinese_translation/c++/translation_ui_delegate.cpp`
重新编译 C++ 翻译模块；编译成功后才会打包，运行方式为：

```text
python source/sp_chinese_translation/scripts/build_package.py
```

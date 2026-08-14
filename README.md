# Substance 3D Painter / Designer 中文翻译补全插件

为 Windows 版 Adobe Substance 3D Painter（SP）与 Substance 3D Designer（SD）补全中文界面。插件读取自带及用户添加的中文词库，对官方汉化尚未覆盖的菜单、按钮、标签、选项卡、下拉选项、参数名称、资源库目录树、资产名称以及 Designer 节点图文字进行补充翻译，**不覆盖**软件已有的中文内容。

**一个插件，两个软件共用。** 同一份源码编译出 Qt5 与 Qt6 两个引擎 DLL：旧版 Painter（7.2–10.0）自动使用 Qt5，新版 Painter（10.1+）与 Designer（15+）共用 Qt6 引擎，C++ 侧在运行时自动识别宿主。

## 功能特性

- **界面补翻译**：自动翻译菜单、按钮、标签、选项卡、下拉选项、参数名、资源库目录树和资源列表；软件已显示中文的控件自动跳过。
- **动态刷新**：界面变化或拖动参数时实时补充翻译；悬停在插件翻译过的文字上可查看英文原文。
- **图层面板翻译**（Painter）：翻译图层面板（包括用户创建的图层名称），仅改变显示，不修改项目数据。
- **节点图翻译**（Designer）：实验性功能，默认关闭。用户确认启用后翻译节点标题与输入/输出端口标签；关闭时立即回滚原生绘制挂钩。
- **即时开关**：取消勾选"启用插件翻译"立即恢复全部界面原文，只影响显示。
- **直接改词**：`Ctrl + 鼠标右键` 打开"更改翻译"窗口，普通修改写入用户覆盖词库 `user_added_zh.json`；专项控件 ID 修改写入随更新包覆盖的 `control_ids_zh.json`，更新前如需保留应另行备份。
- **词条提取工具**：内置独立 C++ 提取器，扫描资源文件与材质元数据，批量生成待翻译词库；提取过程与宿主进程隔离，解析崩溃不会带入软件。
- **导出资产库未翻译名称**：通过软件界面读取资源库中尚无中文译文的资产名称，保存为可直接编辑的 `*_zh.json`。
- **在线更新**：从 GitHub Releases 获取正式版并原地更新，不关闭软件、不关闭当前工程。

## 支持环境

- Windows 10/11 64 位。
- Substance 3D Painter 7.2 至最新版（Qt5/Qt6 自动识别）。
- Substance 3D Designer 15 及以上（Qt6）。

## 安装方法

同一个发布包 `substance3d_chinese_translator.zip` 适用于两个软件，解压到各自的插件目录即可：

- **Substance 3D Painter**：解压到 `C:\Users\用户名\Documents\Adobe\Adobe Substance 3D Painter\python\plugins`，此时应该有 `pluginInfo.json` 在 `...\python\plugins\substance3d_chinese_translator\` 文件夹中，启动后打开菜单 `Python`，勾选"中文翻译补全插件"。
- **Substance 3D Designer**：解压到 `C:\Users\用户名\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins`，此时应该有 `pluginInfo.json` 在 `...\python\sduserplugins\substance3d_chinese_translator` 文件夹，启动后插件自动加载，菜单栏出现"中文翻译工具"，没有就在工具，插件管理器里勾选。

手动安装或替换插件目录前请先完全退出对应软件；插件自带的"检查插件更新"无需退出。

## 快速使用

插件启用后自动加载词库并翻译当前界面，无需手动操作。

- **悬停**：在插件翻译过的文字上悬停，可查看英文原文。
- **改词**：按住 `Ctrl` 点击鼠标右键，打开"更改翻译"窗口。
- **开关**：通过"中文翻译工具"窗口控制总开关、图层面板翻译（Painter）与模糊匹配。

## 中文翻译工具

菜单 `Python → 中文翻译工具`（Painter）或菜单栏"中文翻译工具"（Designer）打开工具窗口，包含"界面翻译 / 提取设置 / 提取选项"分区。

### 界面翻译设置

- **启用插件翻译**：总开关，默认开启；取消勾选立即恢复所有界面原文。
- **翻译图层面板（包括用户创建的图层名称）**：Painter 图层面板专用开关。
- **启用模糊匹配**：精准匹配优先，兼容大小写、全半角、下划线等差异。
- **启用节点图翻译**（Designer）：默认关闭；首次启用会显示风险确认。仅在 Designer 15/16、64 位与 Qt 6.5–6.9 兼容白名单内安装挂钩，检查失败时保持关闭。
- **检查插件更新**：见[在线更新](#在线更新)。

### 词条提取

在"提取设置"中选择资产目录与输出 JSON 路径，按需调整"提取选项"后点击"开始提取"：

- **名称**：提取普通文件名（默认开）、文件夹名（默认关）。
- **词条属性**：`label`、`text`、`group`、`description`、`category`、`keywords`、`values`、`description_disabled`，可按需勾选。

提取完成后自动生成可直接编辑的 `*_zh.json` 词库；若输出文件已存在，其中已有译文会保留，新词条以空译文加入。

### 提取规则

提取器支持：

- 递归扫描资产目录，跳过 `.` 开头的隐藏目录（如 `.git`）与 `__pycache__`、`_unpacked_assets`；
- 从 7z/ZIP/HDF5 容器提取 XML 元数据词条，并展开嵌套容器（嵌套深度、容器数、成员数及整个任务的展开大小均有上限）；
- 解析 `.sbs`（含无显式标签时以参数 `identifier` 作为参数名）、`.spsm` 智能材质、`.sppr` 预设、GLSL 注解等。
- 提取 `label`、`text`、`group`、`description`、`category`、`keywords`、`values` 等元数据。

以下内容不会被提取：

- 已含中文的原文；
- 纯整数、小数、科学计数法和百分比数值；
- 内部资源引用 URL（`?version=` 形式）；
- 插件现有词库中已存在的原文。
- 超过大小上限的解析文件（XML/GLSL/preset.bin 64 MB，HDF5 数据集 256 MB）。

每个文件无论成败都会输出到面板日志；失败项同时写入输出文件旁的 `_failures.txt`。

### 导出资产库未翻译名称

"导出资产库未翻译名称"读取软件资源库中尚无中文译文的名称，保存为可直接编辑的 `*_zh.json`：

- **Painter**：遍历所有资产架资源；
- **Designer**：遍历界面资源库的目录树与资源列表（含全部已加载分类）。

导出结果只包含插件词库中尚未出现中文译文的名称；已有译文的名称不会重复导出。

## 在线更新

"中文翻译工具"窗口内的"检查插件更新"按钮，通过 GitHub Releases API 从 `iillya/substance3d_chinese_translator` 查询最新正式版：

- 已是最新版时提示"已是最新版本"；
- 正在执行词条提取时点击会提示先完成或取消提取，避免文件占用；
- 发现新版本时确认后弹出下载进度窗口（后台下载，可取消）；
- 下载完成后必须通过 GitHub Release 资产 SHA-256、完整文件清单、版本一致性、CRC、路径及下载/解压大小上限校验，然后原地替换插件文件；无法获得资产摘要时安全中止；
- 应用完成后提示"请重启软件以启用新版本"，由用户自行决定重启时机；
- 重启后提示"插件已更新成功"，并自动清理临时备份与更新残留；
- 更新失败自动回滚旧版本并保留安装包；用户自建词库会原样保留，更新包自带的 `official_assets_zh.json`、`my_assets_zh.json`、`control_ids_zh.json` 直接以新版覆盖，不再合并本地内容。

## 词库格式

插件按文件名排序加载 `translations` 文件夹下所有 `*_zh.json`，后加载的词库覆盖同名词条。

全局词库结构：

```json
{
  "$schema": "sp-translation-v1",
  "id": "my-translations",
  "language": "zh-CN",
  "description": "My translations",
  "translations": {
    "English source": "中文翻译"
  }
}
```

专项词库（控件 ID 专属）与全局词库格式相同，放在 `control_ids_zh.json`，
键为完整控件 ID（`上级类名||自身类名||自身 objectName||原文`），
用于让同一个原文在不同控件下显示不同的译文：

```json
{
  "$schema": "sp-translation-v1",
  "id": "control-id-specific-translations",
  "language": "zh-CN",
  "translations": {
    "QToolButton||QMenu||blendingModeMenu||Normal": "正常",
    "QToolButton||QMenu||blendingModeMenu||Multiply": "正片叠底"
  }
}
```

翻译查找顺序：① 控件 ID 专属词库（control_ids_zh.json）→ ② 全局词库 → ③ 模糊匹配兜底。

词库要求：文件名以 `_zh.json` 结尾、UTF-8 编码、`$schema` 为 `sp-translation-v1`、`language` 为 `zh-CN`；空译文不会加载（可作为待翻译占位符）。修改词库后重新加载插件或重启软件生效。“更改翻译”窗口勾选“保存到专项词库（control_ids_zh.json）”时，新译文以完整控件 ID 为键写入该文件。

## 工作原理

插件由三层构成：

- **Python 层**：负责生命周期管理、词库加载、工具窗口、提取任务调度与在线更新。
- **原生翻译引擎**（Qt5/Qt6 DLL）：向宿主的 QApplication 安装事件过滤器与列表项绘制委托，实时翻译控件文本、图层面板与资产列表；Designer 节点图挂钩必须由用户明确启用，并通过宿主/Qt 白名单、安装校验与失败回滚。
- **独立词条提取器**：脱离宿主进程运行的 C++ 程序，解析容器与元数据格式。

三层之间通过 C API 和 JSON 文件通信。Python 只负责"翻译什么"，界面渲染由原生引擎在 Qt 层完成。

## 开发与构建

### 仓库结构

```text
sp插件/
├─ source/
│  ├─ substance3d_chinese_translator/  统一插件源码（SP/SD 共用）
│  │  ├─ __init__.py                   Painter 入口（加载同目录同名子模块）
│  │  ├─ pluginInfo.json               Designer 插件元数据
│  │  ├─ substance3d_chinese_translator/  合并后的 Python 模块（双入口 + 宿主识别）
│  │  ├─ cpp/                          原生 C++ 引擎（CMakeLists + 翻译引擎 + 提取器）
│  │  ├─ native/                       Qt5/Qt6 翻译 DLL 与独立提取器 EXE
│  │  └─ translations/                 词库目录（official_assets_zh.json 等）
│  └─ public/
│     ├─ scripts/                      构建脚本与开发工具
│     └─ sdks/                         随仓库捆绑的构建依赖（Qt SDK + 静态库）
├─ dist/                               构建输出（substance3d_chinese_translator.zip）
└─ README.md
```

### 构建要求

- Windows x64，安装 CMake 与 Visual Studio 2022 Build Tools（MSVC C++ 工具链）。
- Qt SDK 与提取器依赖已随仓库捆绑在 `source/public/sdks/`，**构建无需 vcpkg、无需网络**。

### 构建步骤

在仓库根目录运行：

```text
python source/public/scripts/build_package.py
```

脚本会依次：校验源码（含 Python 3.7 语法兼容检查）→ 编译 Qt5 与通用 Qt6 两个 DLL → 编译独立提取器 EXE → 生成 `dist/substance3d_chinese_translator.zip`。任一编译失败都会中止，不会发布旧产物。

### 发布新版本

1. 修改 `source/substance3d_chinese_translator/substance3d_chinese_translator/__init__.py` 中的 `PLUGIN_VERSION` 与 `source/substance3d_chinese_translator/pluginInfo.json` 的版本号。
2. 运行构建脚本生成发布包。
3. 在 GitHub 创建版本号高于当前 `PLUGIN_VERSION` 的正式 Release，把 ZIP 以 `substance3d_chinese_translator.zip`（或 `substance3d_chinese_translator_版本.zip`）上传为附件。

## 兼容性说明

- Painter 7.2–10.0 使用 Qt5 引擎 DLL，10.1+ 与 Designer 15+ 使用 Qt6 引擎 DLL（同一文件，运行时自动识别宿主）。
- Designer 的资源库/节点图识别依赖软件内部控件类名，个别版本升级后若内部结构变化，相关面板翻译可能静默失效（不会崩溃），需按版本适配。
- 资源库搜索仍按英文原始名称匹配（翻译只作用于显示层），这是当前版本的有意限制。

## 卸载

完全退出对应软件后，删除其插件目录下的 `substance3d_chinese_translator` 文件夹，重新启动软件。

## 注意事项

- 手动替换 DLL 或整个插件目录前必须完全退出对应软件。
- `Ctrl + 右键`会直接修改词库，建议在大量手工调整前自行备份。
- 插件只改变界面显示文本，不修改资产本体或项目数据。
- 提取器处理的是用户选择的资产目录，请勿对不信任的来源目录执行提取；解析文件大小与嵌套层数均有限制，但导入恶意构造的压缩包仍有风险。



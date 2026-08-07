# Substance 3D Painter 中文翻译补全插件

为 Windows 版 Adobe Substance 3D Painter 补全中文界面。插件读取自带及用户添加的中文词库，对官方汉化尚未覆盖的菜单、按钮、标签、选项卡、下拉选项、参数名称、资产库目录树和资产名称进行补充翻译，**不覆盖** Painter 已有的中文内容。

界面翻译由原生 C++ 模块完成，插件启动时根据 Painter 的 Qt 主版本自动选择 Qt5 或 Qt6 DLL，无需手动配置。

## 功能特性

- **界面补翻译**：自动翻译菜单、按钮、标签、选项卡、下拉选项、参数名、资产库目录树和资源列表。
- **动态刷新**：界面变化或拖动参数时自动补充翻译；悬停在插件翻译过的文字上可查看英文原文。
- **图层面板翻译**：翻译图层面板（包括用户创建的图层名称），仅改变显示，不修改项目中保存的实际图层名称。
- **即时开关**：取消勾选"启用插件翻译"立即恢复全部界面原文，只影响显示。
- **直接改词**：`Ctrl + 鼠标右键` 打开"更改翻译"窗口，保存后写回该词条所属的 JSON 词库。
- **词条提取工具**：内置独立 C++ 提取器，扫描资源文件与 GLSL 材质元数据，批量生成待翻译词库；提取过程与 Painter 进程隔离，解析崩溃不会带入 Painter。
- **资产库导出**：通过 Painter 官方资源 API 导出尚无中文译文的资产名称，结果可直接编辑。
- **在线更新**：从 GitHub Releases 获取正式版并原地更新，不关闭 Painter、不关闭当前工程。

## 工作原理

插件由三层构成：

- **Python 层**（`__init__.py`）：负责生命周期管理、词库加载、工具窗口、提取任务调度与在线更新。
- **原生翻译引擎**（Qt5/Qt6 DLL）：向 Painter 的 QApplication 安装事件过滤器与列表项绘制委托，实时翻译控件文本、图层面板与资产列表；Painter 官方已显示中文的控件会被自动跳过。
- **独立词条提取器**（`sp_translation_extractor.exe`）：脱离 Painter 进程运行的 C++ 程序，解析 7z/ZIP/HDF5 容器、XML 元数据、GLSL 注解与智能材质图层结构。

三层之间通过 C API 和 JSON 文件通信。Python 只负责"翻译什么"，界面渲染由原生引擎在 Qt 层完成。

## 适用环境

- Windows 10/11 64 位，Adobe Substance 3D Painter 7.2 至最新版。
- Painter 7.2–10.0 使用 Qt5 引擎，10.1 及以后使用 Qt6 引擎；插件启动时自动识别，无需手动选择。

## 安装方法

1. 打开 `C:\Users\用户名\Documents\Adobe\Adobe Substance 3D Painter\python\plugins` 文件夹。
2. 将发布包 `sp_chinese_translation.zip` 解压到该文件夹。
3. 此时你应该看到 `__init__.py` 在目录 `...\python\plugins\sp_chinese_translation` 中。
4. 启动 Substance 3D Painter，打开菜单 `Python`，勾选"中文翻译补全插件"。

手动安装或替换插件目录前请先完全退出 Painter；插件自带的"检查插件更新"无需退出。

## 快速使用

插件启用后自动加载词库并翻译当前界面，无需手动操作。

- 悬停：在插件翻译过的文字上悬停，可查看英文原文。
- 改词：按住 `Ctrl` 点击鼠标右键，打开"更改翻译"窗口；能溯源时写回原词库，否则自动创建 `user_added_zh.json` 保存。
- 开关：通过"中文翻译工具"窗口控制总开关与图层面板翻译开关。

## 中文翻译工具

菜单 `Python → 中文翻译工具` 打开工具窗口，包含"界面翻译 / 提取设置 / 提取选项"分区。

### 界面翻译设置

- **启用插件翻译**：总开关，默认开启。取消勾选立即恢复所有界面原文，仅影响显示。
- **翻译图层面板（包括用户创建的图层名称）**：图层面板专用开关，仅总开关开启时可用。
- **检查插件更新**：见[在线更新](#在线更新)。

### 词条提取

在"提取设置"中选择资产目录与输出 JSON 路径，按需调整"提取选项"后点击"开始提取"：

- **名称**：提取普通文件名（默认开）、文件夹名（默认关）。
- **词条属性**：`label`、`text`、`group`、`description`、`category`、`keywords`、`values`、`description_disabled`，可按需勾选。

提取完成后自动生成可直接编辑的 `*_zh.json` 词库；若输出文件已存在，其中已有译文会保留，新词条以空译文加入。

### 提取规则

提取器支持：

- 递归扫描资源目录；
- 从 7z/ZIP/HDF5 容器提取 XML 元数据词条，并展开嵌套容器（每资产最多 128 层嵌套，防止压缩炸弹）；
- 解析 `.spsm` 智能材质与 `.sppr` 预设中的图层名；
- 提取 GLSL 元数据（`//:` JSON 注解与 `DisplayName` 等声明）；
- 提取时跳过 `.` 开头的隐藏目录（如 `.alg_meta`、`.git`）。

以下内容不会被提取：

- 已含中文的原文；
- 纯整数、小数、科学计数法和百分比数值；
- 内部资源引用 URL（`?version=` 形式的资产地址）；
- 插件现有全局词库及控件专属词库中已存在的原文；
- 超过大小上限的解析文件（XML/GLSL/preset.bin 64 MB，HDF5 数据集 256 MB）。

每个文件无论成败都会输出到面板日志；失败项同时写入输出文件旁的 `_failures.txt`。

### 导出资产库未翻译名称

"导出资产库未翻译名称"通过 Painter 官方资源 API 导出尚无中文译文的资产名称，保存为可直接编辑的 `*_zh.json`。

## 词库格式

插件按文件名排序加载 `translations` 文件夹下所有 `*_zh.json`，后加载的词库覆盖同名词条。

全局词库结构：

```json
{
  "$schema": "sp-translation-v1",
  "id": "my-translations",
  "language": "zh-CN",
  "description": "My Painter translations",
  "translations": {
    "English source": "中文翻译"
  }
}
```

限定到特定控件类型的词条放在 `control_types` 中，每个类型拥有独立词表（如图层混合模式）：

```json
{
  "$schema": "sp-translation-v1",
  "id": "control-specific-translations",
  "language": "zh-CN",
  "description": "Control-scoped translations",
  "control_types": {
    "layer_blend_mode": {
      "translations": {
        "Normal": "正常",
        "Multiply": "正片叠底"
      }
    }
  }
}
```

词库要求：文件名以 `_zh.json` 结尾、UTF-8 编码、`$schema` 为 `sp-translation-v1`、`language` 为 `zh-CN`；空译文不加载。修改词库后重新加载插件或重启 Painter 生效。

内置词库：`official_assets_zh.json`（约 6362 条）、`my_assets_zh.json`（约 1809 条）、`control_types_zh.json`（32 条控件专属词条，图层混合模式）。

## 在线更新

"中文翻译工具"窗口内的"检查插件更新"按钮，通过 GitHub Releases API 从 `iillya/sp_chinese_translation` 查询最新正式版：

- 已是最新版时提示"已是最新版本"。
- 正在执行词条提取时点击会提示先完成或取消提取，避免文件占用。
- 发现新版本时确认后弹出下载进度窗口（后台下载，可取消），安装包下载到 Painter 的 `python\plugins` 目录。
- 下载完成后校验安装包完整性（含必需文件、无路径穿越与符号链接），然后原地替换插件文件；被占用的原生 DLL/EXE 先改名再写入新文件，当前会话继续用旧版本。
- 应用完成后提示"请重启 Substance 3D Painter 以启用新版本"，由用户自行决定重启时机。
- 重启后提示"插件已更新成功"，并自动清理临时备份与更新残留。
- 更新失败自动回滚旧版本并保留安装包；用户自建词库 JSON 不会被覆盖。

## 开发与构建

### 仓库结构

```text
sp插件/
├─ source/
│  ├─ sp_chinese_translation/        插件源码
│  │  ├─ __init__.py                 插件入口、工具窗口、更新流程
│  │  ├─ cpp/                        原生 C++ 模块（CMakeLists + 翻译引擎 + 提取器）
│  │  ├─ native/                     Qt5/Qt6 翻译 DLL 与独立提取器 EXE
│  │  ├─ translations/               词库目录（official_assets_zh.json 等）
│  │  ├─ scripts/                    构建脚本与开发工具
│  │  └─ THIRD_PARTY_LICENSES.txt    第三方许可证
│  └─ sdks/                          随仓库捆绑的构建依赖
│     ├─ qt/                         Qt 5.12.5 / 6.5.3 工具链
│     └─ deps/                       提取器静态依赖库（含许可证文件）
├─ dist/                             构建输出（sp_chinese_translation.zip）
└─ README.md
```

### 构建要求

- Windows x64，安装 CMake 与 Visual Studio 2022 Build Tools（MSVC C++ 工具链）。
- Qt SDK 与提取器依赖已随仓库捆绑在 `source/public/sdks/`，**构建无需 vcpkg、无需网络**。

### 构建步骤

在仓库根目录运行：

```text
python source/sp_chinese_translation/scripts/build_package.py
```

脚本会依次：校验源码（含 Python 3.7 语法兼容检查）→ 编译 Qt5/Qt6 两个 DLL → 编译独立提取器 EXE → 生成 `dist/sp_chinese_translation.zip`。任一编译失败都会中止，不会发布旧产物。

### 发布新版本

1. 修改 `source/sp_chinese_translation/__init__.py` 中的 `PLUGIN_VERSION` 与 `cpp/vcpkg.json` 的版本号，并在 README 版本历史中记录更新内容。
2. 运行构建脚本生成发布包。
3. 在 GitHub 创建版本号高于当前 `PLUGIN_VERSION` 的正式 Release，把 ZIP 以 `sp_chinese_translation.zip`（或 `sp_chinese_translation_版本.zip`）上传为附件。

## 卸载

完全退出 Painter 后，删除 `python\plugins\sp_chinese_translation` 文件夹，重新启动 Painter。

## 注意事项

- 手动替换 DLL 或整个插件目录前必须完全退出 Painter。
- Ctrl+右键会直接修改词库，建议在大量手工调整前自行备份。
- 插件只改变界面显示文本，不修改资产本体或项目数据；Painter 已显示中文的控件会被跳过。
- 提取器处理的是用户选择的资产目录，请勿对不信任的来源目录执行提取；解析文件大小与嵌套层数均有限制，但导入恶意构造的压缩包仍有风险。

## 版本历史

### v3.0.0

- 修复提取器嵌套容器上限跨文件累计的 bug：此前处理到第 128 个含嵌套容器的资产后，后续容器文件会全部被误判为"超过嵌套上限"而失败。
- 提取器新增资产 URL 过滤：不再提取 `?version=` 形式的内部资源引用（如 `/Fabric Pattern?version=…`）。
- 提取器增加解析防护：XML/GLSL/preset.bin 与 HDF5 数据集均设置大小上限，防止恶意文件耗尽内存。
- 提取日志改为每个文件都输出成功/失败；`_failures.txt` 仍只记录失败项。
- 更新流程加固：更新包解压前校验成员路径并拒绝符号链接，防止路径穿越；正在执行的词条提取会阻止检查更新；被占用的 DLL/EXE 可改名替换。
- 目录结构整理：原生 C++ 源码合并至 `cpp/`；SP、SD 共用 `source/public/translations/` 词库；Qt SDK 与提取器依赖合并至 `source/public/sdks/`，构建不再需要 vcpkg。
- 移除旧版遗留的 Python 词条提取死代码，消除潜在异常路径。

### v2.0.2

- 资源词条提取改为独立 C++ 程序，不再依赖 Painter 的 Python、NumPy、h5py 或 py7zr 版本。
- 修复 SPPR 参数标签、SPSM 智能材质图层名及嵌套容器词条遗漏。
- 提取失败与 Painter 进程隔离，并保留已有输出译文。

### v2.0.1

- 更新流程重构：下载后原地替换插件文件，不关闭 Painter 和当前工程，提示重启生效。
- 下载进度弹窗重做，修复空白和鼠标转圈问题，可随时取消。
- 更新成功后自动清理备份与残留；更新包应用后自动删除；用户自建词库不被覆盖。
- 更新失败自动回滚并保留安装包；界面文案统一排版。

## 许可证

项目许可证见根目录 `LICENSE`；第三方组件许可证见 `source/sp_chinese_translation/THIRD_PARTY_LICENSES.txt`，各库完整许可文本随仓库捆绑于 `source/public/sdks/deps/share/`。

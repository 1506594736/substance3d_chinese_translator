# Substance 3D Painter 中文翻译补全插件

适用于 Windows 版 Adobe Substance 3D Painter 的中文界面补全插件。插件读取自带及用户添加的中文词库，对 Painter 官方汉化尚未覆盖的菜单、按钮、参数、资源目录和资产名称进行补充翻译，不覆盖 Painter 已有的中文内容。界面翻译由原生 C++ 模块处理，插件会根据 Painter 的 Qt 主版本自动选择 Qt5 或 Qt6 DLL。

## 主要功能

- 补充翻译菜单、按钮、标签、选项卡、下拉选项和参数名称，以及资产库目录树和资源列表。
- 界面动态变化或拖动参数时自动补充翻译；悬停在插件翻译过的文字上可查看英文原文。
- `Ctrl + 鼠标右键`直接修改当前翻译，并写回该词条所属的 JSON 词库。
- 翻译图层面板（包括用户创建的图层名称），不修改项目中保存的实际图层名称。
- 内置中文翻译工具，可扫描资源文件、GLSL 材质元数据，并导出资产库中未翻译的名称。
- 支持加载 `translations` 目录下所有 `*_zh.json` 词库。
- 内置“检查插件更新”，从 GitHub Releases 获取正式版并原地更新。

## 适用环境

- Windows 10/11 64 位，Adobe Substance 3D Painter 7.2 至最新版。
- Painter 7.2–10.0 使用 Qt5 引擎，10.1 及以后使用 Qt6 引擎，启动时自动识别，无需手动选择。

## 安装方法

1. 在 `...\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\` 下新建 `sp_chinese_translation` 文件夹。
2. 将发布包 `sp_chinese_translation.zip` 直接解压到该文件夹（压缩包根目录就是插件内容）。
3. 启动 Substance 3D Painter，打开菜单 `Python`，确认“中文翻译补全插件”已勾选。

手动安装或替换插件目录前请先完全退出 Painter；插件自带的“检查插件更新”无需退出。

## 基本使用

插件启用后自动加载词库并翻译当前界面，无需手动操作。在插件汉化的文字上按住 `Ctrl` 点击鼠标右键，可打开“更改翻译”窗口修改译文；能溯源时写回原词库，否则自动创建 `user_added_zh.json` 保存。

## 检查更新

“中文翻译工具”窗口内右上角的“检查插件更新”按钮，通过 GitHub Releases API 从 `iillya/sp_chinese_translation` 查询最新正式版：

- 已是最新版时提示“已是最新版本”。
- 发现新版本时确认后弹出下载进度窗口（后台下载，可取消），安装包下载到 Painter 的 `python\plugins` 目录。
- 下载完成后直接原地替换插件文件，不关闭 Painter、不关闭当前工程；被占用的原生 DLL 先改名再写入新文件，当前会话继续用旧版本。
- 应用完成后提示“请重启 Substance 3D Painter 以启用新版本”，由用户自行决定重启时机。
- 重启后提示“插件已更新成功”，并自动清理临时备份与更新残留。
- 更新失败自动回滚旧版本并保留安装包；用户自建词库 JSON 不会被覆盖。

发布新版本：在仓库根目录运行 `python source/sp_chinese_translation/scripts/build_package.py` 生成 `dist/sp_chinese_translation.zip`，在 GitHub 创建版本号高于当前 `PLUGIN_VERSION` 的正式 Release，并把 ZIP 以 `sp_chinese_translation.zip`（或 `sp_chinese_translation_版本.zip`）上传为附件。

## 中文翻译工具

工具窗口包含“界面翻译 / 提取设置 / 提取选项”分区：

- **启用插件翻译**：总开关，默认开启。取消勾选立即恢复所有界面原文，仅影响显示。
- **翻译图层面板（包括用户创建的图层名称）**：图层面板专用开关，仅总开关开启时可用。
- **检查插件更新**：见上文。

词条提取支持：递归扫描资源目录；从 7z/ZIP/HDF5 容器提取 XML 元数据词条；解析 `.spsm` 智能材质中的图层名；提取 `label`、`text`、`group`、`description`、`category`、`keywords`、`values` 等字段；提取 GLSL 元数据；可选提取普通文件名（默认开）和文件夹名（默认关）。已含中文的原文不会被提取；纯整数、小数、科学计数法和百分比数值也不会作为词条提取；插件目录现有全局词库及控件专属词库中已存在的原文会被跳过；已有输出中的已有译文会保留，新词条以空译文加入。

“导出资产库未翻译名称”通过 Painter 官方资源 API 导出尚无中文译文的资产名称，结果可直接编辑。

## 词库格式

插件按文件名排序加载 `translations` 文件夹下所有 `*_zh.json`。词库结构：

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

限定到特定控件类型的词条（如图层混合模式）放在 `control_types` 中，每个类型拥有独立词表。要求：文件名以 `_zh.json` 结尾、UTF-8 编码、`$schema` 为 `sp-translation-v1`、`language` 为 `zh-CN`、空译文不加载。

修改词库后重新加载插件或重启 Painter 生效。

## 插件目录说明

```text
sp_chinese_translation/
├─ __init__.py                         插件入口和词条提取器
├─ native/                             原生 C++ 翻译模块（Qt6/Qt5 两个 DLL）
├─ packages/                           资源容器解析依赖
├─ translations/                       词库目录（official_assets_zh.json 等）
└─ THIRD_PARTY_LICENSES.txt            第三方许可证
```

## 卸载

完全退出 Painter 后，删除 `python\plugins\sp_chinese_translation` 文件夹，重新启动 Painter。

## 注意事项

- 手动替换 DLL 或整个插件目录前必须完全退出 Painter。
- Ctrl+右键会直接修改词库，建议在大量手工调整前自行备份。
- 插件只改变界面显示文本，不修改资产本体或项目数据；Painter 已显示中文的控件会被跳过。

## 版本历史

### v2.0.2

- 修复 Painter 2021 / Python 3.7 中资源词条提取全部失败的问题。
- 内置 7z 解析器兼容 Python 3.7，并增加解析模块缓存与安全降级。
- 打包时自动校验内置 Python 模块的 Python 3.7 语法兼容性。

### v2.0.1

- 更新流程重构：下载后原地替换插件文件，不关闭 Painter 和当前工程，提示重启生效。
- 下载进度弹窗重做，修复空白和鼠标转圈问题，可随时取消。
- 更新成功后自动清理备份与残留；更新包应用后自动删除；用户自建词库不被覆盖。
- 更新失败自动回滚并保留安装包；界面文案统一排版。

## 许可证

项目许可证见根目录 `LICENSE`，第三方组件许可证见 `THIRD_PARTY_LICENSES.txt`。

## 仓库结构

`source/sp_chinese_translation/`（含 `c++/` 原生模块）与 `source/sp_tools/`（含 `c++/` 原生模块）为两个独立插件源码；`source/qt-sdk` 为共用 Qt 构建工具链。构建脚本 `source/sp_chinese_translation/scripts/build_package.py` 会先编译 C++ 模块再打包到 `dist/`。

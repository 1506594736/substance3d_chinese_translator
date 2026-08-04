# Substance 3D Painter 中文翻译补全插件

这是一个适用于 Windows 版 Adobe Substance 3D Painter 的中文界面补全插件。插件会读取自带及用户添加的中文词库，对 Painter 官方汉化尚未覆盖的菜单、按钮、参数、资源目录和资产名称进行补充翻译。

插件不会覆盖 Painter 已经显示为中文的内容。界面翻译和资源列表显示由原生 C++ 模块处理，以降低刷新延迟并提高退出稳定性。

## 主要功能

- 补充翻译菜单、按钮、标签、选项卡、下拉选项和参数名称。
- 翻译资产库目录树、资源列表及添加滤镜等资源选择窗口。
- 保留 Painter 官方已有的中文翻译，不重复覆盖。
- 界面动态变化或拖动参数时自动补充翻译。
- 鼠标悬停在普通翻译文字上时显示英文原文。
- 资产缩略图区域保留 Painter 官方大图预览，不显示冲突的原文提示。
- `Ctrl + 鼠标右键`直接修改当前翻译，并写回该词条所属的原始 JSON 词库。
- 内置翻译词条提取器，可扫描资源文件和 GLSL 材质元数据。
- 可通过 Painter 官方资源接口导出资产库中尚未翻译的资产名称。
- 支持加载插件 `translations` 目录下的所有 `*_zh.json` 词库。

## 适用环境

- Windows 10/11 64 位
- Adobe Substance 3D Painter 11.x
- Painter 自带的 Python 3.11 / PySide6 环境

当前原生模块按 Substance 3D Painter 11.x 使用的 Qt 6 环境编译。其他大版本若升级了 Python 或 Qt，可能需要重新编译原生 DLL。

## 安装方法

1. 解压发布包 `sp_chinese_translation.zip`。
2. 将整个 `sp_chinese_translation` 文件夹复制到：

   ```text
   C:\Users\你的用户名\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\
   ```

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

将鼠标悬停在插件翻译过的普通文字上，可查看对应的英文原文。

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

保存后界面会立即刷新。新译文直接写回该词条最终来源的原始 `*_zh.json`，不会额外生成用户覆盖词库。

普通鼠标右键完全交给 Painter，不会触发插件编辑窗口，也不会影响 Painter 原有右键菜单。

## 翻译词条提取器

点击 Painter 顶部菜单栏中的“翻译词条提取器”打开工具。

提取器可执行以下操作：

- 递归扫描指定资源目录。
- 从支持的资源容器中提取 XML 元数据词条。
- 提取 `label`、`text`、`group`、`description`、`category` 等字段。
- 将 `label`、`label0`、`label1` 等统一作为 `label` 处理。
- 提取 GLSL 元数据中的 `label`、`group`、`description`、`description_disabled` 和下拉框 `values`。
- 可选提取普通文件名，默认开启。
- 可选提取文件夹名，默认关闭。
- `.sbsar`、`.spsm` 等可识别资源容器始终记录容器文件名。
- 保留已有 JSON 中已经填写的译文，新词条以空译文加入。

支持扫描的 GLSL 类扩展名包括：

```text
.glsl  .glslfx  .vert  .frag  .geom  .tesc  .tese  .comp
```

PNG、EXR、SVG、字体、QML、JavaScript 等普通资源不会解析内部代码；启用“提取普通文件名”时会记录它们的文件名。提取器不解析 ABR 文件内部的笔刷名称。

提取资源容器时使用插件内置 Python 模块，不需要安装或调用外部 7-Zip 程序。

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
│  └─ sp_native_asset_delegate.dll     原生界面与资源列表翻译模块
├─ translations/
│  └─ official_assets_zh.json          默认中文词库
├─ vendor/                             资源容器解析所需的精简 Python 依赖
└─ THIRD_PARTY_LICENSES/                第三方依赖许可证
```

`vendor` 和 `THIRD_PARTY_LICENSES` 属于插件运行依赖及其许可证文件，发布或安装完整功能版本时请保留。

## 卸载

1. 完全退出 Substance 3D Painter。
2. 删除以下文件夹：

   ```text
   C:\Users\你的用户名\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\sp_chinese_translation
   ```

3. 重新启动 Painter。

## 注意事项

- 替换 DLL 或整个插件前必须完全退出 Painter。
- Ctrl+右键会直接修改词库文件，建议在大量手工调整前自行备份词库。
- 某些 Painter 控件由内部模型动态绘制，插件只改变显示文本，不修改资产本体或项目数据。
- 插件仅补充界面显示，不会修改 Substance 资源文件内容。
- 如果某个控件已经由 Painter 官方显示中文，插件会跳过该控件。

## 许可证

项目许可证见根目录 `LICENSE`。第三方组件许可证见插件包中的 `THIRD_PARTY_LICENSES` 目录。

# Substance 3D Designer 中文翻译补全

面向 Substance 3D Designer 15.x 的实时 Qt6 界面翻译试验版。

- 使用 Designer 官方 Python 插件入口加载。
- 使用独立 C++ Qt 事件过滤器翻译动态界面控件。
- 读取模块内 `translations` 目录下全部 `*_zh.json`。
- 菜单“中文翻译补全”可启停翻译、重新加载词库或打开“中文翻译工具”。
- “中文翻译工具”可递归提取 Substance 资源词条，支持 `.sbs` 的
  `label`、`label0...`、`description`、`group`、`category` 等 Designer
  XML 元数据，并继续支持 SBSAR、SPSM、SPPR、GLSL 等现有格式。
- 词条提取由随插件发布的独立 C++ 程序完成，不依赖 Designer 内置
  Python 版本；Python 仅负责面板和进度显示。

开发目录安装位置：

`Documents/Adobe/Adobe Substance 3D Designer/python/sduserplugins/sd_chinese_translation`

当前版本首先复用 Painter 的通用 Qt 翻译引擎和词库，Designer 专属控件规则及专属词库将在实际嗅探后继续拆分完善。

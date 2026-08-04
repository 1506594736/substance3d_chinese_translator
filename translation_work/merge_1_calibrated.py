import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INCOMING = Path(os.environ.get("SP_INCOMING", Path.home() / "Desktop/1.json"))
OFFICIAL = ROOT / "package_compact/sp_chinese_translation/translations/official_assets_zh.json"


CORRECTIONS = {
    "3d_gradient": "3D 渐变",
    "Black Ops One": "Black Ops One 字体",
    "Chathura": "Chathura 字体",
    "Dancing Script": "Dancing Script 字体",
    "hard surface": "硬表面",
    "height_blend": "高度混合",
    "Jura": "Jura 字体",
    "Leaks - Paints": "渗漏 - 漆面",
    "lens-studio": "Lens Studio 预设",
    "metal": "金属度",
    "Orbitron": "Orbitron 字体",
    "Paint Roller": "油漆滚筒",
    "scratches_generators": "划痕生成器",
    "Sheen Color": "光泽颜色",
    "Shimmering": "微光",
    "Source Han": "思源字体",
}


def calibrated(source, target):
    match = re.fullmatch(r"Kyle Brush Presets\.alpha\.(\d+)", source)
    if match:
        return f"Kyle 笔刷预设 Alpha {match.group(1)}"
    return CORRECTIONS.get(source, target.strip())


def main():
    incoming_payload = json.loads(INCOMING.read_text(encoding="utf-8-sig"))
    official_payload = json.loads(OFFICIAL.read_text(encoding="utf-8-sig"))
    incoming = incoming_payload["translations"]
    official = official_payload["translations"]

    added = 0
    for source in sorted(set(incoming) - set(official), key=str.casefold):
        target = calibrated(source, str(incoming[source]))
        if not target:
            raise ValueError(f"新增词条缺少译文: {source}")
        official[source] = target
        added += 1

    official_payload["id"] = "official-assets"
    official_payload["language"] = "zh-CN"
    official_payload["description"] = "Reviewed Chinese translations for Substance 3D Painter assets and UI labels"
    official_payload["translations"] = dict(
        sorted(official.items(), key=lambda item: item[0].casefold())
    )
    OFFICIAL.write_text(
        json.dumps(official_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"合并完成：新增 {added} 条，总计 {len(official)} 条")


if __name__ == "__main__":
    main()

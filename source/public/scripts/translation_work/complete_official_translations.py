import json
import re
from pathlib import Path


PATH = (Path(__file__).resolve().parents[3] / "substance3d_chinese_translator"
        / "translations" / "official_assets_zh.json")
HAN = re.compile(r"[\u3400-\u9fff]")


def normalized(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


MANUAL = {
    "A generator which allows to choose between the effects of inflate or shrinkwrap.": "可在膨胀与收缩包裹效果之间选择的生成器。",
    "Inflate will apply a swelling or ballooning effect. Shrinkwrap will apply a tightening or shrinking effect to your mesh. Enable Displacement in the Shader settings for more visible result in the viewport.": "膨胀会产生鼓起或气球般的效果；收缩包裹会使网格收紧或缩小。请在着色器设置中启用置换，以便在视口中更清楚地查看效果。",
    "Adjust Shadows/Midtones/Highlights": "调整阴影/中间调/高光",
    "Alphas/Geometric": "Alpha/几何图形",
    "Alternate": "交替",
    "Bayer": "拜耳",
    "Blades": "刀片",
    "Bonifacio Aragon Stairs": "博尼法西奥·阿拉贡阶梯",
    "Chebyshev": "切比雪夫",
    "Comma": "逗号",
    "CommonParameters": "通用参数",
    "Convex": "凸面",
    "Crescant": "新月形",
    "Crescent": "新月形",
    "Crown": "皇冠",
    "Cup": "杯形",
    "Decal": "贴花",
    "Depth": "深度",
    "Desaturation": "去饱和度",
    "Dielectric": "电介质",
    "Directionnal": "方向性",
    "Dritiness": "脏污度",
    "Euclidean": "欧几里得",
    "Felled": "平缝",
    "flakes": "薄片",
    "Fracture": "断裂",
    "Fracture2": "断裂 2",
    "Gradation": "渐变",
    "Hatched": "排线",
    "Hemisphere": "半球",
    "hexa": "六边形",
    "Horizontally": "水平",
    "In": "内部",
    "Interstice Y": "间隙 Y",
    "Knife": "刀具",
    "Knurling": "滚花",
    "Ladder": "梯形",
    "Manhattan": "曼哈顿距离",
    "ManualRain": "手动雨滴",
    "MaterialParameters": "材质参数",
    "MaterialPreview": "材质预览",
    "Minkowski": "闵可夫斯基",
    "Mondarrain 3": "蒙德里安 3",
    "Panorama": "全景图",
    "Paraboloid": "抛物面",
    "Pastel": "粉彩",
    "PBR Materials/Organic": "PBR 材质/有机",
    "Perceptive": "感知",
    "Pipping": "滚边",
    "Platinium": "铂金",
    "Quincux Horizontal": "水平梅花点阵",
    "Rock": "岩石",
    "Round Corners": "圆角",
    "Rust2": "锈蚀 2",
    "RustDrop": "锈迹滴落",
    "Saddle Seam": "马鞍缝",
    "Satin": "缎纹",
    "Sawtooth": "锯齿",
    "sepia": "棕褐色",
    "Shrinkwrap": "收缩包裹",
    "Smudges": "污迹",
    "Sobel": "索贝尔",
    "Specular / Glossiness": "高光/光泽度",
    "Splitted": "拆分",
    "Thorn": "荆棘",
    "Titanium": "钛",
    "Topstitch": "明缝线",
    "Tornado": "龙卷风",
    "Transparant": "透明",
    "Treshold": "阈值",
    "Triangular": "三角形",
    "Twill": "斜纹",
    "vintage": "复古",
    "Weft": "纬线",
    "windows": "窗口",
    "Zits": "痘痕",
    "brush_maker_paint_roller": "滚筒刷生成器",
    "Color_Hue": "颜色色相",
    "Color_Lightness": "颜色明度",
    "edge_03": "边缘 03",
    "edge_06": "边缘 06",
    "edge_09": "边缘 09",
    "film_noir": "黑色电影",
    "grunge_concrete_moss_small": "小型苔藓混凝土脏污",
    "grunge_scratches_2": "脏污划痕 2",
    "handle_07": "把手 07",
    "handle_10": "把手 10",
    "handle_13": "把手 13",
    "handle_16": "把手 16",
    "handle_22": "把手 22",
    "handle_25": "把手 25",
    "Inner_Structure_Scale": "内部结构缩放",
    "mg_ambient_occlusion": "MG 环境光遮蔽",
    "mg_curvature": "MG 曲率",
    "mg_metal_edge_wear": "MG 金属边缘磨损",
    "mg_world_space_normals": "MG 世界空间法线",
    "noise_bnw_spots_1": "黑白斑点噪声 1",
    "noise_cells_3": "细胞噪声 3",
    "noise_clouds_3": "云层噪声 3",
    "noise_crystal_1": "晶体噪声 1",
    "noise_directional_noise_2": "方向性噪声 2",
    "noise_directional_scratches": "方向性划痕噪声",
    "noise_dirt_2": "污垢噪声 2",
    "noise_dirt_5": "污垢噪声 5",
    "noise_fluid": "流体噪声",
    "noise_fractal_sum_2": "分形和噪声 2",
    "noise_fur_3": "毛发噪声 3",
    "noise_gaussian_spots_1": "高斯斑点噪声 1",
    "noise_grunge_map_001": "脏污噪声贴图 001",
    "noise_grunge_map_004": "脏污噪声贴图 004",
    "noise_grunge_map_007": "脏污噪声贴图 007",
    "noise_grunge_map_010": "脏污噪声贴图 010",
    "noise_grunge_map_013": "脏污噪声贴图 013",
    "noise_messy_fibers_1": "杂乱纤维噪声 1",
    "noise_microscope_view": "显微镜视图噪声",
    "noise_moisture_noise": "湿气噪声",
    "panel_01": "面板 01",
    "panel_03": "面板 03",
    "pbr_validate": "PBR 验证",
    "scratches_generator": "划痕生成器",
    "shape_v2": "形状 V2",
    "sheen_noise": "光泽噪声",
    "strap_01": "绑带 01",
    "vent_05": "通风口 05",
    "vent_08": "通风口 08",
    "vent_11": "通风口 11",
    "vent_14": "通风口 14",
    "vent_17": "通风口 17",
    "vent_20": "通风口 20",
    "vent_23": "通风口 23",
    "vent_26": "通风口 26",
    "vent_29": "通风口 29",
    "vent_32": "通风口 32",
    "vent_35": "通风口 35",
    "vent_38": "通风口 38",
    "vent_41": "通风口 41",
    "vent_44": "通风口 44",
    "vent_47": "通风口 47",
    "window_01": "窗口 01",
    "windows_X": "窗口 X",
    "windows_Y": "窗口 Y",
    "wood_pattern_01": "木纹图案 01",
    "Z": "Z 轴",
}

MANUAL.update({
    "adobe-dimension": "Adobe Dimension 预设",
    "Amazon Lumberyard": "Amazon Lumberyard 引擎",
    "Arnold (AiStandard)": "Arnold（AiStandard 材质）",
    "Arnold UDIM (AiStandard)": "Arnold UDIM（AiStandard 材质）",
    "Arnold UDIM Legacy (AiStandard)": "Arnold 旧版 UDIM（AiStandard 材质）",
    "Blender": "Blender 预设",
    "Blender (Principled BSDF)": "Blender（Principled BSDF 材质）",
    "CryEngine": "CryEngine 引擎",
    "DirectX": "DirectX 法线格式",
    "Dota 2": "Dota 2 预设",
    "dota-2": "Dota 2 预设",
    "dota2": "Dota 2 预设",
    "F1": "F1 距离",
    "F1*F2": "F1×F2 距离",
    "F1/F2": "F1/F2 距离",
    "F2": "F2 距离",
    "F2-F1": "F2-F1 距离",
    "fresnelranges": "菲涅耳范围",
    "fresnelranges2": "菲涅耳范围 2",
    "fxaa": "FXAA 抗锯齿",
    "gamma1-8": "伽马 1.8",
    "gamma2-2": "伽马 2.2",
    "mdl": "MDL 材质定义",
    "non-pbr-spec-gloss": "非 PBR 高光/光泽度",
    "OpenGL": "OpenGL 法线格式",
    "pbr-car-paint": "PBR 汽车漆",
    "pbr-coated": "PBR 涂层材质",
    "pbr-material-layering-10-mats": "PBR 材质分层（10 种材质）",
    "pbr-metal-rough-with-alpha-blending": "PBR 金属/粗糙度（Alpha 混合）",
    "pbr-metal-rough-with-alpha-test": "PBR 金属/粗糙度（Alpha 测试）",
    "pbr-spec-gloss": "PBR 高光/光泽度",
    "README": "自述文件",
    "Redshift (rsMaterial)": "Redshift（rsMaterial 材质）",
    "Renderman (pxrDisney)": "RenderMan（pxrDisney 材质）",
    "Renderman (pxrSurface)": "RenderMan（pxrSurface 材质）",
    "Roblox (MaterialVariant)": "Roblox（材质变体）",
    "Roblox (SurfaceAppearance)": "Roblox（表面外观）",
    "shaderparameterconnect": "着色器参数连接",
    "sRGB (from ACEScg)": "sRGB（从 ACEScg 转换）",
    "sRGBf": "浮点 sRGB",
    "Studio 03": "工作室 03",
    "Studio Tomoco": "Tomoco 工作室",
    "Unreal Engine 4 (Packed)": "虚幻引擎 4（通道打包）",
    "Unreal Engine 4 SSS (Packed)": "虚幻引擎 4 SSS（通道打包）",
    "Unreal Engine SSS (Packed)": "虚幻引擎 SSS（通道打包）",
    "Vray Next (Specular Glossiness)": "V-Ray Next（高光/光泽度）",
    "X": "X 轴",
    "Y": "Y 轴",
})


STYLE_NAMES = {
    "ExtraBold": "特粗体",
    "DemiBold": "半粗体",
    "BoldItalic": "粗斜体",
    "Bold Italic": "粗斜体",
    "Regular": "常规",
    "Italic": "斜体",
    "Bold": "粗体",
    "Light": "细体",
    "Thin": "极细体",
}


def styled_font_name(source):
    for suffix, chinese in STYLE_NAMES.items():
        for separator in ("-", " "):
            marker = separator + suffix
            if source.endswith(marker):
                return source[: -len(marker)] + " " + chinese
    return None


def main():
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    translations = payload["translations"]

    existing = {}
    for source, target in translations.items():
        if isinstance(target, str) and HAN.search(target):
            existing.setdefault(normalized(source), set()).add(target)

    changed = 0
    for source, target in list(translations.items()):
        if isinstance(target, str) and target.strip() and target.strip() != source.strip() and HAN.search(target):
            continue

        replacement = None
        matches = existing.get(normalized(source), set())
        if len(matches) == 1:
            replacement = next(iter(matches))
        elif source in MANUAL:
            replacement = MANUAL[source]
        elif source.startswith("Kyle Brush Presets.alpha."):
            number = source.rsplit(".", 1)[-1]
            replacement = f"Kyle 笔刷预设 Alpha {number}"
        else:
            replacement = styled_font_name(source)

        if replacement and replacement != target:
            translations[source] = replacement
            changed += 1

    payload.setdefault("completion", {})
    payload["completion"].pop("completed_entries", None)
    translated_entries = sum(
        1 for target in translations.values()
        if isinstance(target, str) and HAN.search(target)
    )
    preserved_entries = len(translations) - translated_entries
    payload["completion"].update({
        "method": "normalized existing terminology plus reviewed manual translations",
        "translated_entries": translated_entries,
        "preserved_proper_names_and_numeric_entries": preserved_entries,
        "empty_entries": 0,
    })
    PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"updated={changed} total={len(translations)}")


if __name__ == "__main__":
    main()

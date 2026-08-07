import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TARGET = Path(__file__).with_name("extracted_assets_zh.json")
OFFICIAL = ROOT / "source/public/translations/official_assets_zh.json"
HAN = re.compile(r"[\u3400-\u9fff]")


MANUAL = {
    "Alpha Test": "Alpha 测试", "Ambient": "环境光", "Ambient Color": "环境光颜色",
    "Ambient Light": "环境光", "Ambient Scale": "环境光强度", "Anisotropy axis": "各向异性轴",
    "Base color amount": "基础颜色量", "Base local axis for anisotropic highlight": "各向异性高光的基础局部轴",
    "Base Surface": "基础表面", "Blinn": "Blinn", "BRDF": "BRDF", "BRDF type": "BRDF 类型",
    "Coat Layer": "涂层", "Common Parameters": "通用参数", "Debug channel": "调试通道",
    "Debug Mode": "调试模式", "Detail Map": "细节贴图", "Detail Scale": "细节缩放",
    "Diffuse Warp": "漫反射扭曲", "Double sided": "双面", "Edginess": "边缘强度",
    "Enable absorption": "启用吸收", "Enable alpha blending": "启用 Alpha 混合",
    "Enable anisotropy": "启用各向异性", "Enable edge color": "启用边缘颜色",
    "Enable translucency": "启用半透明", "Fabric Tint": "织物色调", "Fiber Scale": "纤维缩放",
    "Fibers Texture": "纤维纹理", "Flake Color": "薄片颜色", "Flakes Scale": "薄片缩放",
    "Flakes Texture": "薄片纹理", "Fresnel IOR": "菲涅耳折射率", "Fresnel Power": "菲涅耳幂",
    "Fresnel Strength": "菲涅耳强度", "Geometry": "几何体", "Geometry/Opacity": "几何体/不透明度",
    "GGX tail falloff": "GGX 尾部衰减", "High (64 spp)": "高（64 spp）", "IBL Lighting": "IBL 照明",
    "Impact": "影响", "Index of refraction": "折射率", "IOR": "折射率", "Keep details": "保留细节",
    "Light Color": "灯光颜色", "Light Intensity": "灯光强度", "Light Position": "灯光位置",
    "Lock fresnel IOR to refraction IOR": "将菲涅耳折射率锁定到折射折射率",
    "Low (16 spp)": "低（16 spp）", "Medium (32 spp)": "中（32 spp）", "Normal from Masks": "从遮罩生成法线",
    "Options": "选项", "Phong": "Phong", "Reflection": "反射", "Reflection amount": "反射量",
    "Refraction": "折射", "Refraction amount": "折射量", "Refraction glossiness": "折射光泽度",
    "Rim Light Color": "边缘光颜色", "Rim Light Scale": "边缘光缩放", "Rim Lighting": "边缘光照明",
    "Secondary Paint Color": "次要绘制颜色", "Separate fresnel reflection IOR, when not locked to refraction IOR.": "未锁定到折射折射率时使用独立的菲涅耳反射折射率。",
    "Separate refraction glossiness": "独立的折射光泽度", "Sheen": "光泽", "Sheen Variation": "光泽变化",
    "Smooth surface": "平滑表面", "Specular Exponent": "高光指数", "Specular Scale": "高光缩放",
    "Surface behavior": "表面行为", "Tertiary Paint Color": "第三绘制颜色", "Trace reflections": "追踪反射",
    "Trace refractions": "追踪折射", "Ultra (256 spp)": "极高（256 spp）", "Use fresnel": "使用菲涅耳",
    "Use the same IOR as refraction for reflection fresnel.": "反射菲涅耳使用与折射相同的折射率。",
    "Variation Scale": "变化缩放", "Very high (128 spp)": "很高（128 spp）", "Very low (4 spp)": "很低（4 spp）",
    "Index of refraction for refraction effect and fresnel reflections (unless disabled in Reflection options)": "折射效果和菲涅耳反射所用的折射率（除非在反射选项中禁用）。",
    "Make reflection strength dependent on the viewing angle (e.g. glass materials). Depends on IOR.": "使反射强度随观察角度变化（例如玻璃材质），效果取决于折射率。",
    "When disabled, refractions are not traced": "禁用时不追踪折射。",
    "When disabled, reflections are not traced, resulting in only highlights. Also the diffuse color is not dimmed by the reflection color, as would happen normally": "禁用时不追踪反射，只保留高光；漫反射颜色也不会像通常那样被反射颜色压暗。",
    "When enabled, V-Ray also shades the back-facing surfaces. Otherwise, the lighting for the outer side is always computed. Can be used to achieve a fake translucent effect for thin objects like paper.": "启用后 V-Ray 也会为背面着色；否则始终计算外侧照明。可用于纸张等薄物体的模拟半透明效果。",
    "Multiply with MaskCoat (user1) channel": "与涂层遮罩（user1）通道相乘",
    "Override with RoughnessCoat (user0) channel": "使用涂层粗糙度（user0）通道覆盖",
    "Nyanneco Fabric Weave Generator": "Nyanneco 织物编织生成器",
    "TR Stylized Texture Generator remastered": "TR 风格化纹理生成器重制版",
    "Dark Hatcher": "深色排线", "Archive Inker": "档案墨线笔", "GGGBB_Toon": "GGGBB 卡通",
    "GNUTypewriter": "GNU 打字机字体", "Pollock CD": "波洛克 CD", "RGBA": "RGBA",
    "NyanToon": "Nyan 卡通着色", "NyanToon_CN": "Nyan 卡通着色中文版",
    "Shahn": "Shahn 字体", "Ward": "Ward", "GGX": "GGX",
    "<html><head/><body><p>Allows for refractive transmission of light through the surface.<br/><b>Please note</b>: The following channel needs to be present for this parameter to have an effect: <b>Translucency</b></p></body></html>": "<html><head/><body><p>允许光线通过表面进行折射透射。<br/><b>请注意</b>：必须存在<b>半透明</b>通道，此参数才会生效。</p></body></html>",
    "<html><head/><body><p>Allows reflections to stretch in one direction along the surface.<br/><b>Please note</b>: The following channels need to be present for this parameter to have an effect: <b>Anisotropy angle</b> and <b>Anisotropy level</b>.</p></body></html>": "<html><head/><body><p>允许反射沿表面某一方向拉伸。<br/><b>请注意</b>：必须存在<b>各向异性角度</b>和<b>各向异性级别</b>通道，此参数才会生效。</p></body></html>",
    "<html><head/><body><p>Allows specifying the color of light reflections. Affects glancing angles for metallic materials.<br/><b>Please note</b>: The following channel needs to be present for this parameter to have an effect: <b>Specular edge color</b></p></body></html>": "<html><head/><body><p>允许指定光线反射的颜色，并影响金属材质的掠射角。<br/><b>请注意</b>：必须存在<b>高光边缘颜色</b>通道，此参数才会生效。</p></body></html>",
    "<html><head/><body><p>Disable the <b>Subsurface Scattering</b> to use <b>Alpha blending</b>.</p></body></html>": "<html><head/><body><p>请禁用<b>次表面散射</b>以使用 <b>Alpha 混合</b>。</p></body></html>",
    "<html><head/><body><p>Disable the <b>Subsurface Scattering</b> to use <b>Translucency</b>.</p></body></html>": "<html><head/><body><p>请禁用<b>次表面散射</b>以使用<b>半透明</b>。</p></body></html>",
    "<html><head/><body><p>Filters the light that passes through the volume by absorbing certain colors. Affects both translucency and subsurface scattering.<br/><b>Please note</b>: The following channel needs to be present for this parameter to have an effect: <b>Absorption color</b></p></body></html>": "<html><head/><body><p>通过吸收特定颜色来过滤穿过体积的光线，同时影响半透明和次表面散射。<br/><b>请注意</b>：必须存在<b>吸收颜色</b>通道，此参数才会生效。</p></body></html>",
    "<html><head/><body><p>The amount light bends as it passes through the object. Also affects the specular reflection intensity.</p></body></html>": "<html><head/><body><p>光线穿过物体时的弯折程度，同时也会影响高光反射强度。</p></body></html>",
    "<html><head/><body><p>Uses the opacity texture to progressively blend the transparent surface over the background.<br/><b>Please note</b>: The following channel needs to be present for this parameter to have an effect: <b>Opacity</b></p></body></html>": "<html><head/><body><p>使用不透明度纹理将透明表面逐渐混合到背景上。<br/><b>请注意</b>：必须存在<b>不透明度</b>通道，此参数才会生效。</p></body></html>",
    "<html><head/><body><p>When enabled, the surface is visible on both sides, i.e. back-face culling is disabled.</p></body></html>": "<html><head/><body><p>启用后表面两侧均可见，即禁用背面剔除。</p></body></html>",
}

COLLECTIONS = {
    "Kyle's Concept Brushes": "Kyle 概念笔刷", "Kyle's Inkbox": "Kyle 墨线笔刷",
    "Kyle's Paintbox": "Kyle 绘画笔刷", "Kyle's Rakes": "Kyle 耙形笔刷",
    "Kyle's Real Watercolor": "Kyle 真实水彩笔刷", "Kyle's Runny Inkers": "Kyle 流动墨线笔刷",
    "Kyle's Spatter Brushes": "Kyle 飞溅笔刷",
}

PHRASES = {
    "Natural Edge Painter": "自然边缘绘画", "Picture Book": "绘本", "Broken Lines": "断续线",
    "Bubble Burst": "气泡爆裂", "Cartoon Scales Control": "卡通鳞片控制", "Chickenscratch": "凌乱细线",
    "Clouds Chunky": "厚重云块", "Clouds Puffy": "蓬松云朵", "Cracked Earth": "龟裂土地",
    "Crazy Cracks": "疯狂裂纹", "Dragon Scales": "龙鳞", "Fast Grass": "快速草丛",
    "Foliage Small Ground Cover": "小型地被植物", "Foliage Pro": "专业植被", "Fur Animal Left More": "更多左向动物毛发",
    "Fur Animal Right More": "更多右向动物毛发", "Fur Animal Left": "左向动物毛发", "Fur Animal Right": "右向动物毛发",
    "Small Branch Mix": "小树枝混合", "Jungle Build": "丛林构建", "Mike's Ivy Down": "Mike 下垂常春藤",
    "Rain Basic": "基础雨丝", "Raindrops": "雨滴", "Sir Hairy Short": "短毛发先生", "Sir Hairy Sparse": "稀疏毛发先生",
    "Sir Hairy": "毛发先生", "Beta Twister": "Beta 扭曲", "Bone Dry Brush": "极干笔刷", "Flat Tip Marker": "平头马克笔",
    "Big Streak": "大笔触", "Fence Painter": "栅栏绘画", "French Fat Bristle": "法式粗鬃毛",
    "French Point Small": "法式小尖头", "French Sharp Block": "法式锐利方头", "Gouache G Dry Out": "水粉 G 干涸",
    "Gouache Wet Round": "湿润圆头水粉", "Impressionist Chunk": "厚重印象派", "Van Gogh Blocky": "梵高块面",
    "Big Basic No Flow": "大号基础无流量", "Monster Heavy D": "怪兽厚重 D", "Sparse Rough": "稀疏粗糙",
    "Bleeding Edges": "渗化边缘", "Bristle Buddy": "鬃毛伙伴", "Opaque Thicker": "更厚不透明",
    "Pulpy Paper": "纸浆纸", "Salt Course": "粗盐", "Salt Fine": "细盐", "Salt Medium": "中等盐粒",
    "Soft Irregular Wash Variant": "柔和不规则水洗变体", "Sparse Bristle": "稀疏鬃毛", "Spatter Mixed": "混合飞溅",
    "Spatter Spread": "扩散飞溅", "Spider Spread Crisp": "清晰蛛网扩散", "Veiny Vision": "叶脉纹理",
    "Wamazing Basic": "基础水彩晕染", "Asteroid Belt": "小行星带", "Beautiful Mess": "美丽凌乱",
    "Dampy Drip": "湿润滴流", "wc Spatter Spread": "水彩扩散飞溅", "Big Basic": "大号基础",
    "Crystalline": "晶体", "Cubist": "立体派", "Gulls": "海鸥", "Weirdness": "奇异纹理",
    "Chipper": "碎屑", "Crackup": "裂纹", "Chopped": "断续切痕", "Grind": "研磨",
    "Phat": "厚实", "Pressure": "压力", "Variant": "变体", "Opaque": "不透明",
    "Spatter": "飞溅", "Salt Alt": "盐粒变体", "Salt": "盐粒", "Stars": "星点", "Dots": "圆点",
    "Blot Bot": "墨渍机器人", "Sparse Rough": "稀疏粗糙", "Cezanne": "塞尚", "Claude M": "克劳德·莫奈",
    "Monet": "莫奈", "Pissarro": "毕沙罗", "Seurat": "修拉", "Signac": "西涅克", "Gouache Blair": "Blair 水粉",
}

FONT_MARKERS = (
    "Arial", "Almendra", "Archive Inker", "Bahnschrift", "Calibri", "Cambria", "Candara", "Cascadia",
    "Comic Sans", "Consolas", "Constantia", "Corbel", "Courier", "Dancing Script", "Dark Hatcher", "DengXian",
    "Ebrima", "FangSong", "Franklin", "Gabriola", "Gadugi", "Georgia", "Ink Free", "Javanese", "JetBrains",
    "Jura", "KaiTi", "Leelawadee", "Libre Baskerville", "Lucida", "Malgun", "Microsoft", "Mongolian",
    "MV Boli", "Myanmar", "Noto", "Orbitron", "Palatino", "ROGFonts", "Sans Serif", "Segoe", "SimHei",
    "SimSun", "Sitka", "Source Han", "Sylfaen", "Tahoma", "Times New", "Trebuchet", "Verdana",
)

STYLE = {
    "Bold Italic": "粗斜体", "Light Italic": "细斜体", "Black Italic": "特黑斜体",
    "Semibold Italic": "半粗斜体", "Semilight Italic": "半细斜体", "ExtraBold Italic": "特粗斜体",
    "ExtraLight Italic": "特细斜体", "Medium Italic": "中等斜体", "Thin Italic": "极细斜体",
    "BoldItalic": "粗斜体", "ExtraBold": "特粗体", "ExtraLight": "特细体", "Semibold": "半粗体",
    "Semilight": "半细体", "Regular": "常规", "Italic": "斜体", "Bold": "粗体", "Light": "细体",
    "Medium": "中等", "Thin": "极细体", "Black": "特黑体",
}


def font_translation(source):
    special = {"SimHei": "黑体", "FangSong": "仿宋", "KaiTi": "楷体", "DengXian Bold": "等线粗体",
               "DengXian Light": "等线细体", "DengXian Regular": "等线常规", "Noto Sans SC": "Noto 无衬线简体中文",
               "Noto Serif SC": "Noto 衬线简体中文", "Source Han Sans Light": "思源黑体细体",
               "Source Han Serif SC Light": "思源宋体简体中文细体"}
    if source in special:
        return special[source]
    if not any(marker in source for marker in FONT_MARKERS):
        return None
    for suffix in sorted(STYLE, key=len, reverse=True):
        if source.endswith(" " + suffix) or source.endswith("-" + suffix):
            base = source[:-(len(suffix) + 1)]
            return f"{base} {STYLE[suffix]}"
    return f"{source} 字体"


def kyle_translation(source):
    if source.startswith("Kyle Brush Presets alpha "):
        return source.replace("Kyle Brush Presets alpha ", "Kyle 笔刷预设 Alpha ")
    for prefix, translated_prefix in COLLECTIONS.items():
        marker = prefix + " - "
        if source.startswith(marker):
            tail = source[len(marker):]
            for english in sorted(PHRASES, key=len, reverse=True):
                tail = tail.replace(english, PHRASES[english])
            return f"{translated_prefix} - {tail}"
    return None


def numbered(source):
    patterns = (
        (r"Mask (\d+)$", "遮罩 {}"), (r"Material (\d+)$", "材质 {}"),
        (r"Material (\d+) coords$", "材质 {} 坐标"), (r"Normal Intensity (\d+)$", "法线强度 {}"),
        (r"Normal from Mask (\d+) Offset$", "遮罩 {} 法线偏移"),
        (r"Normal from Mask Intensity (\d+)$", "遮罩法线强度 {}"),
    )
    for pattern, output in patterns:
        match = re.fullmatch(pattern, source)
        if match:
            return output.format(match.group(1))
    normal = {"Normal (Combined)": "法线（合并）", "Normal (Masks)": "法线（遮罩）", "Normal (Material)": "法线（材质）"}
    return normal.get(source)


def main():
    payload = json.loads(TARGET.read_text(encoding="utf-8-sig"))
    translations = payload["translations"]
    official = json.loads(OFFICIAL.read_text(encoding="utf-8-sig"))["translations"]
    for source, target in list(translations.items()):
        if not str(target).strip() and str(official.get(source, "")).strip():
            translations[source] = official[source]
    for source, target in list(translations.items()):
        if str(target).strip():
            continue
        replacement = MANUAL.get(source) or numbered(source) or kyle_translation(source) or font_translation(source)
        if replacement:
            translations[source] = replacement

    # Internal snake_case identifiers often duplicate a user-facing asset name.
    # Reuse the reviewed display-name translation instead of translating tokens
    # independently (which produced phrases such as “笔刷 油漆 圆形”).
    def normalized(text):
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    display_targets = {}
    for source, target in translations.items():
        if "_" not in source and HAN.search(str(target)):
            display_targets.setdefault(normalized(source), set()).add(target)
    for source in list(translations):
        if "_" in source:
            matches = display_targets.get(normalized(source), set())
            if len(matches) == 1:
                translations[source] = next(iter(matches))

    # Context corrections: Paint as an action/brush is 绘制/绘画, not 油漆.
    corrections = {
        "Artistic Hairy Paint": "艺术毛绒绘画", "Gradient Paint Brush": "渐变绘画笔刷",
        "Brush Maker Paint Roller (Grayscale)": "绘画滚筒笔刷生成器（灰度）",
        "brush_maker_paint_roller": "绘画滚筒笔刷生成器", "brush_maker_paint_roller_material": "绘画滚筒材质笔刷生成器",
        "Paint Color": "漆面颜色", "Paint Color Variation": "漆面颜色变化", "Paint Density": "漆面密度",
        "Paint Grain": "漆面颗粒", "Paint Intensity": "漆面强度", "Paint Metallic": "漆面金属度",
        "Paint Opacity": "漆面不透明度", "Paint Roughness": "漆面粗糙度", "Paint Roughness Variation": "漆面粗糙度变化",
        "Secondary Paint Color": "次要绘制颜色", "Tertiary Paint Color": "第三绘制颜色",
        "Footprint Paint": "绘制脚印", "Handprint Paint": "绘制手印", "Handprint Paint Erased": "擦除式绘制手印",
        "Handprint Paint Palm": "绘制手掌印", "Handprint Paint Partial": "局部绘制手印", "Handprint Smear Paint": "涂抹式绘制手印",
        "footprint_paint": "绘制脚印", "handprint_paint": "绘制手印", "handprint_paint_erased": "擦除式绘制手印",
        "handprint_paint_palm": "绘制手掌印", "handprint_paint_partial": "局部绘制手印", "handprint_smear_paint": "涂抹式绘制手印",
        "gouache_paint": "水粉颜料", "spray_paint_tag": "喷漆涂鸦标记", "matfx_peeling_paint": "材质效果 - 漆面剥落",
        "Fresh Blue Paint": "新鲜蓝色漆面", "Fresh Paint": "新鲜漆面", "Glossy Dark Brush Paint": "光泽深色绘画笔触",
        "Pale Blue Brush Paint": "淡蓝色绘画笔触", "Random Brush Paint": "随机绘画笔触",
        "Prints - Paint": "印迹 - 绘画", "Prints - Paints": "印迹 - 绘画",
        "Show cross paint edges": "显示交叉绘制边缘", "Scribble Strong Paint Tag": "强力涂写标记",
        "Steel Gun Painted": "涂漆枪械钢材", "Steel Painted": "涂漆钢材", "Steel Painted Rough Damaged": "粗糙破损涂漆钢材",
        "Steel Painted Scraped Dirty": "脏污刮擦涂漆钢材", "Steel Painted Stained": "污渍涂漆钢材",
        "Steel Painted Worn": "磨损涂漆钢材", "Steel Tank Painted": "涂漆钢制坦克",
        "Simulate a Paint Roller to draw a continuous pattern.  How to use: - Load into the Alpha of the Paint tool - Drag and drop an image into the Input - Use rotation parameter to make image point up - Set Brush Spacing to 5 - Enable \"Follow Path\" - Make sure the Angle Parameter is set to 0 - Enable Lazy Mouse (optional)": "模拟绘画滚筒来绘制连续图案。用法：加载到绘画工具的 Alpha；将图像拖放到输入；用旋转参数使图像朝上；将笔刷间距设为 5；启用“跟随路径”；确保角度参数为 0；可按需启用延迟笔迹。",
    }
    for source in list(translations):
        if source.startswith("Brush Paint "):
            current = translations[source]
            translations[source] = current.replace("油漆笔刷", "绘画笔刷")
        elif source.startswith("brush_paint_"):
            display_source = source.replace("brush_paint_", "Brush Paint ").replace("_", " ").title()
            match = translations.get(display_source)
            if match:
                translations[source] = match
    translations.update({k: v for k, v in corrections.items() if k in translations})

    missing = [key for key, value in translations.items() if not str(value).strip()]
    if missing:
        raise SystemExit("仍有空译文：\n" + "\n".join(missing))
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完成：{len(translations)} 条，空译文 0 条")


if __name__ == "__main__":
    main()

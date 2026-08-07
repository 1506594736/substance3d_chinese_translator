"""Complete blank Designer translations using the reviewed local terminology corpus.

Run from the repository root. Existing non-empty translations are never changed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[3]
TARGET = SOURCE_ROOT / "public" / "translations" / "official_assets_zh.json"


TERMS = {
    "spline": "样条曲线", "splines": "样条曲线", "legacy": "旧版", "deprecated": "已弃用",
    "map": "贴图", "maps": "贴图", "mapper": "映射器", "mapping": "映射", "multiplier": "倍增系数",
    "input": "输入", "inputs": "输入", "output": "输出", "enable": "启用", "disable": "禁用",
    "switch": "切换", "use": "使用", "show": "显示", "hide": "隐藏", "preview": "预览",
    "point": "点", "points": "点", "vector": "向量", "matrix": "矩阵", "value": "值",
    "values": "值", "float": "浮点数", "integer": "整数", "boolean": "布尔值", "data": "数据",
    "render": "渲染", "compute": "计算", "sampling": "采样", "sample": "采样", "sampler": "采样器",
    "distribution": "分布", "attenuation": "衰减", "frequencies": "频率", "frequency": "频率",
    "properties": "属性", "property": "属性", "adjustment": "调整", "selection": "选择",
    "select": "选择", "target": "目标", "source": "源", "index": "索引", "id": "ID",
    "path": "路径", "paths": "路径", "bridge": "桥接", "plane": "平面", "sphere": "球体",
    "surface": "表面", "volume": "体积", "mesh": "网格", "vertex": "顶点", "vertices": "顶点",
    "tangent": "切线", "tangents": "切线", "axis": "轴", "pivot": "轴心", "space": "空间",
    "world": "世界", "local": "局部", "global": "全局", "camera": "摄像机", "view": "视图",
    "crop": "裁剪", "resolution": "分辨率", "precision": "精度", "iteration": "迭代",
    "iterations": "迭代次数", "segments": "分段", "section": "截面", "profile": "轮廓",
    "channel": "通道", "channels": "通道", "palette": "调色板", "histogram": "直方图",
    "gamma": "伽马", "exposure": "曝光", "luminance": "亮度", "irradiance": "辐照度",
    "reflectance": "反射率", "diffusion": "扩散", "occlusion": "遮蔽", "shadow": "阴影",
    "shadows": "阴影", "horizon": "地平线", "sun": "太阳", "aperture": "光圈",
    "lens": "镜头", "hotspot": "热点", "parallax": "视差", "relief": "浮雕",
    "extrude": "挤出", "emboss": "浮雕", "displace": "置换", "baked": "烘焙",
    "prelighting": "预照明", "lighting": "照明", "directional": "方向性", "radial": "径向",
    "polar": "极坐标", "cartesian": "笛卡尔坐标", "planar": "平面", "cubic": "立方体",
    "cylinder": "圆柱体", "circular": "圆形", "ring": "环形", "square": "方形",
    "quad": "四边形", "area": "区域", "areas": "区域", "field": "场", "bbox": "边界框",
    "texture": "纹理", "pattern": "图案", "tile": "平铺", "tiles": "平铺块", "atlas": "图集",
    "noise": "噪波", "fractal": "分形", "perlin": "柏林", "worley": "沃利", "voronoi": "沃罗诺伊",
    "simplex": "单纯形", "slope": "坡度", "gradient": "渐变", "curve": "曲线",
    "blur": "模糊", "warp": "扭曲", "splatter": "泼溅", "scatter": "散布", "flood": "漫水填充",
    "filter": "滤镜", "filtering": "过滤", "threshold": "阈值", "clamp": "钳制", "normalize": "归一化",
    "invert": "反转", "quantize": "量化", "upscale": "放大", "downscale": "缩小",
    "transform": "变换", "rotation": "旋转", "position": "位置", "offset": "偏移", "scale": "缩放",
    "size": "尺寸", "distance": "距离", "length": "长度", "width": "宽度", "depth": "深度",
    "thickness": "厚度", "radius": "半径", "angle": "角度", "direction": "方向",
    "intensity": "强度", "amount": "数量", "number": "数量", "level": "级别", "levels": "级别",
    "range": "范围", "minimum": "最小值", "maximum": "最大值", "min": "最小值", "max": "最大值",
    "start": "起始", "end": "结束", "center": "中心", "balance": "平衡", "contrast": "对比度",
    "random": "随机", "uniform": "均匀", "linear": "线性", "smooth": "平滑", "sharp": "锐利",
    "anisotropic": "各向异性", "anisotropy": "各向异性", "symmetry": "对称", "variation": "变化",
    "influence": "影响", "affect": "影响", "override": "覆盖", "optional": "可选", "safe": "安全",
    "color": "颜色", "colour": "颜色", "grayscale": "灰度", "rgb": "RGB", "srgb": "sRGB",
    "alpha": "Alpha", "base": "基础", "ambient": "环境光", "diffuse": "漫反射",
    "specular": "高光", "glossiness": "光泽度", "roughness": "粗糙度", "metallic": "金属度",
    "normal": "法线", "height": "高度", "opacity": "不透明度", "emissive": "自发光",
    "material": "材质", "materials": "材质", "pbr": "PBR", "uv": "UV", "uvs": "UV",
    "hsl": "HSL", "hsi": "HSI", "hsv": "HSV", "hdr": "HDR", "ao": "AO", "hbao": "HBAO",
    "acescg": "ACEScg", "ev": "EV", "ior": "IOR", "f0": "F0", "sdf": "SDF",
    "background": "背景", "foreground": "前景", "black": "黑色", "white": "白色", "bright": "亮部",
    "basecolor": "基础颜色", "bg": "背景", "raw": "原始", "composite": "合成", "composited": "已合成",
    "blend": "混合", "blending": "混合", "merge": "合并", "mask": "遮罩", "fill": "填充",
    "edge": "边缘", "edges": "边缘", "bevel": "倒角", "bent": "弯曲", "skew": "倾斜",
    "twist": "扭转", "peeling": "剥落", "weathering": "风化", "wear": "磨损", "dirt": "污垢",
    "grunge": "污渍", "scratches": "划痕", "cracks": "裂纹", "creases": "褶皱", "stains": "污渍",
    "moss": "苔藓", "snow": "积雪", "water": "水", "fabric": "织物", "cloth": "布料",
    "leather": "皮革", "wood": "木材", "concrete": "混凝土", "metal": "金属", "bricks": "砖块",
    "brick": "砖块", "planks": "木板", "fibers": "纤维", "weave": "编织", "fur": "毛发",
    "function": "函数", "operator": "运算符", "hash": "哈希", "list": "列表", "table": "表格",
    "connection": "连接", "connect": "连接", "extract": "提取", "convert": "转换", "clone": "克隆",
    "helper": "辅助", "generator": "生成器", "engine": "引擎", "startup": "启动",
    "first": "第一个", "last": "最后一个", "only": "仅", "custom": "自定义", "auto": "自动",
    "automatic": "自动", "clear": "清除", "close": "关闭", "cancel": "取消", "debug": "调试",
    "advanced": "高级", "quality": "质量", "hq": "高质量", "mode": "模式", "type": "类型",
    "non": "非", "pre": "预", "post": "后", "with": "带", "without": "不带",
    "from": "来自", "to": "到", "by": "按", "of": "的", "in": "内", "on": "上",
    "per": "每", "and": "和", "or": "或", "not": "非", "equal": "等于", "equality": "相等",
    "sum": "求和", "pow": "幂", "sort": "排序", "make": "生成", "get": "获取",
}

# Designer-specific node and parameter vocabulary not present as standalone
# entries in the Painter dictionary.
TERMS.update({
    "shape": "形状", "shapes": "形状", "patch": "修补", "light": "光照", "out": "输出",
    "panorama": "全景图", "gaussian": "高斯", "glow": "发光", "pavement": "铺装",
    "curvature": "曲率", "details": "细节", "detail": "细节", "disorder": "无序度",
    "flip": "翻转", "image": "图像", "paint": "绘制", "painted": "已绘制", "used": "已使用",
    "projection": "投影", "smoothness": "平滑度", "top": "顶部", "bottom": "底部",
    "circle": "圆形", "temperature": "色温", "count": "数量", "warping": "扭曲",
    "softness": "柔和度", "cartoon": "卡通", "ground": "地面", "grid": "网格",
    "tiling": "平铺", "rock": "岩石", "saturation": "饱和度", "albedo": "反照率",
    "average": "平均", "bullets": "弹孔", "impacts": "冲击", "parametrisation": "参数化",
    "parameterization": "参数化", "equalizer": "均衡器", "cross": "交叉", "sobel": "Sobel",
    "coords": "坐标", "coordinates": "坐标", "coordinate": "坐标", "rust": "锈蚀",
    "displacement": "置换", "high": "高", "low": "低", "line": "线条", "lines": "线条",
    "multiply": "相乘", "simple": "简单", "lightness": "明度", "user": "用户",
    "spread": "扩散", "split": "拆分", "splitter": "拆分器", "alveolus": "蜂窝",
    "mult": "倍增", "chroma": "色度", "fade": "淡化", "dielectric": "电介质",
    "outlines": "轮廓线", "sharpen": "锐化", "sharpening": "锐化", "environment": "环境",
    "tools": "工具", "transformation": "变换", "transformations": "变换", "highpass": "高通",
    "blue": "蓝色", "green": "绿色", "red": "红色", "yellow": "黄色",
    "magenta": "品红色", "cyan": "青色", "left": "左", "right": "右",
    "photo": "照片", "plate": "底板", "mosaic": "马赛克", "multiangle": "多角度",
    "nadir": "天底", "spacing": "间距", "rgba": "RGBA", "caustics": "焦散",
    "brightness": "亮度", "desaturation": "去饱和", "season": "季节", "morph": "形变",
    "trail": "轨迹", "tonemapper": "色调映射器", "add": "添加", "pixel": "像素",
    "pixels": "像素", "kuwahara": "Kuwahara", "detection": "检测", "detect": "检测",
    "bloom": "泛光", "coat": "涂层", "combined": "组合", "combine": "合并",
    "layer": "图层", "layers": "图层", "cube": "立方体", "degrees": "度", "turns": "圈数",
    "dithering": "抖动", "dispertion": "色散", "dispersion": "色散", "disperse": "分散",
    "leaks": "渗漏", "speed": "速度", "jittering": "抖动", "style": "样式",
    "circ": "圆形", "expo": "指数", "quart": "四次", "quint": "五次", "sine": "正弦",
    "scattering": "散射", "extend": "扩展", "extension": "扩展", "fxaa": "FXAA",
    "facets": "切面", "template": "模板", "one": "一", "focus": "焦点", "frost": "霜冻",
    "axial": "轴向", "gravel": "碎石", "than": "比", "hcl": "HCL", "viewer": "查看器",
    "units": "单位", "herb": "草本", "hue": "色相", "premultiplied": "预乘",
    "mid": "中间", "absolute": "绝对值", "luma": "亮度", "cell": "单元格",
    "median": "中值", "adaptive": "自适应", "mirror": "镜像", "factor": "系数",
    "occlude": "遮蔽", "along": "沿", "ordering": "顺序", "bounds": "边界",
    "paper": "纸张", "hardness": "硬度", "up": "向上", "around": "周围",
    "straight": "直线", "reaction": "反应", "recompute": "重新计算", "replace": "替换",
    "rotate": "旋转", "scalar": "标量", "division": "除法", "seams": "接缝",
    "segment": "分段", "sub": "子", "selective": "选择性", "stroke": "笔划",
    "sludge": "污泥", "spiral": "螺旋", "bleach": "漂白", "trapezoid": "梯形",
    "vertical": "垂直", "jump": "跳跃", "ibl": "IBL", "pass": "通道",
    "cancellation": "抵消", "age": "老化", "strength": "强度", "xy": "XY",
    "amplitude": "振幅", "append": "追加", "arc": "圆弧", "previous": "上一个",
    "overlap": "重叠", "converter": "转换器", "bias": "偏差", "bitmap": "位图",
    "bitmap2material": "Bitmap2Material", "bitonic": "双调", "blackbody": "黑体",
    "stretch": "拉伸", "bounding": "边界", "box": "框", "dark": "暗部",
    "cardboard": "纸板", "orientation": "方向", "mixer": "混合器", "chaos": "混沌",
    "chrominance": "色度", "classic": "经典", "brown": "棕色", "closed": "闭合",
    "opened": "开放", "burn": "加深", "dodge": "减淡", "propagation": "传播",
    "sharpness": "锐度", "product": "乘积", "alignment": "对齐", "deep": "深度",
    "dirtiness": "脏污度", "draw": "绘制", "duplicates": "副本", "notch": "缺口",
    "spatter": "飞溅", "speckle": "斑点", "wetness": "湿润度", "effect": "效果",
    "effects": "效果", "gloss": "光泽", "correction": "校正", "joints": "接缝",
    "subsurface": "次表面", "envelope": "包络", "delta": "增量", "facing": "朝向",
    "feather": "羽化", "film": "薄膜", "flatten": "展平", "flow": "流动",
    "format": "格式", "frame": "帧", "greater": "大于", "hald": "Hald",
    "clut": "CLUT", "hard": "硬", "heightmap": "高度图", "settings": "设置",
    "svg": "SVG", "ice": "冰", "ignore": "忽略", "inner": "内部", "tiled": "已平铺",
    "labels": "标签", "label": "标签", "large": "大", "link": "链接", "lower": "较低",
    "soft": "柔和", "liquid": "液体", "seed": "随机种子", "luminosity": "亮度",
    "builder": "构建器", "technique": "技术", "selector": "选择器", "transforms": "变换",
    "medium": "中等", "combiner": "合并器", "warper": "扭曲器", "messy": "凌乱",
    "mipmap": "Mipmap", "multiclone": "多重克隆", "multicrop": "多重裁剪",
    "multidir": "多方向", "multiswitch": "多重切换", "next": "下一个", "accessed": "访问",
    "dir": "方向", "poly": "多边形", "uncombine": "取消合并", "steps": "步数",
    "step": "步长", "old": "旧版", "safety": "安全", "trade": "权衡", "off": "关闭",
    "validate": "验证", "pan": "平移", "parent": "父级", "parquet": "拼花地板",
    "processor": "处理器", "find": "查找", "repeat": "重复", "photon": "光子",
    "physical": "物理", "default": "默认", "polygonal": "多边形", "pole": "极点",
    "aspect": "宽高比", "quincunx": "梅花形", "hexagonal": "六边形", "hexcone": "六角锥",
    "slant": "倾斜", "normals": "法线", "reflection": "反射", "rivets": "铆钉",
    "affects": "影响", "rough": "粗糙", "saturate": "饱和", "wave": "波形",
    "screen": "屏幕", "shading": "着色", "smart": "智能", "cover": "覆盖",
    "special": "特殊", "quadratic": "二次", "spot": "斑点", "starburst": "星芒",
    "straighten": "拉直", "stripes": "条纹", "substance": "Substance", "summed": "累加",
    "brush": "画笔", "swirl": "漩涡", "slice": "切片", "tileable": "可平铺",
    "triplanar": "三平面", "uber": "全能", "vignette": "暗角", "conversion": "转换",
    "floodfill": "漫水填充", "functions": "函数", "pseudo": "伪", "signed": "有符号",
    "textures": "纹理", "aces": "ACES", "materiel": "材质", "absorption": "吸收",
    "agx": "AgX", "matching": "匹配", "align": "对齐", "rtao": "RTAO",
    "blades": "叶片", "diffraction": "衍射", "apply": "应用", "arcs": "圆弧",
    "avoid": "避免", "algorithm": "算法", "beauty": "美观", "shift": "偏移",
    "boundaries": "边界", "buildup": "堆积", "cdf": "CDF", "fov": "视野",
    "weight": "权重", "parameters": "参数", "replacement": "替换", "columns": "列",
    "bounces": "反弹次数", "each": "每个", "init": "初始化", "concavity": "凹度",
    "concrect": "混凝土", "conform": "贴合", "patterns": "图案", "constant": "常量",
    "convexity": "凸度", "copy": "复制", "corner": "角点", "creased": "起皱",
    "create": "创建", "criterion": "判据", "buffers": "缓冲区", "culling": "剔除",
    "cut": "切割", "cutout": "剪切", "damaged": "损坏", "hit": "命中",
    "decimate": "简化", "radians": "弧度", "denim": "牛仔布", "difference": "差值",
    "dilation": "膨胀", "integer1": "整数1", "integer2": "整数2", "integer4": "整数4",
    "blended": "已混合", "anycomputation": "任意计算", "display": "显示", "origin": "原点",
    "metric": "度量", "weights": "权重", "faster": "更快", "drawing": "绘制",
    "dual": "双重", "damages": "损伤", "roundness": "圆度", "highlight": "高光",
    "lod": "LOD", "additional": "附加", "clipping": "裁剪", "control": "控制",
    "even": "偶数", "exclusion": "排除", "fixmirrored": "修复镜像", "flat": "平坦",
    "two": "二", "fluid": "流体", "fresh": "新鲜", "spots": "斑点", "generate": "生成",
    "preprocess": "预处理", "valid": "有效", "reflected": "反射", "filledcells": "已填充单元格",
    "greyscale": "灰度", "guessed": "推测", "handle": "控制柄", "adjust": "调整",
    "hemisphere": "半球", "equalize": "均衡", "smoothing": "平滑", "horizontal": "水平",
    "falloff": "衰减", "smaller": "较小", "infinite": "无限", "inherit": "继承",
    "initial": "初始", "ink": "墨水", "free": "自由", "unused": "未使用",
    "true": "真", "false": "假", "are": "是", "interstice": "间隙", "interstices": "间隙",
    "generated": "已生成", "keep": "保留", "above": "上方", "kernel": "内核",
    "keying": "抠像", "kmeans": "K 均值", "knit": "针织", "beta": "Beta",
    "lut": "LUT", "lab": "Lab", "flares": "光斑", "halo": "光晕", "kelvin": "开尔文",
    "limit": "限制", "thing": "对象", "console": "控制台", "unicode": "Unicode", "lum": "亮度",
})

ACRONYMS = {
    "2d": "2D", "3d": "3D", "rt": "RT", "mg": "MG", "ma": "MA", "px": "px",
    "v2": "V2", "v4": "V4", "vec": "Vec", "vec2": "Vec2", "float1": "Float1",
    "float2": "Float2", "float3": "Float3", "float4": "Float4",
}


def normalized(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.replace("_", " ").casefold()))


def make_local_lexicon(translations: dict[str, str]) -> dict[tuple[str, ...], str]:
    result: dict[tuple[str, ...], str] = {}
    for source, target in translations.items():
        key = normalized(source)
        # English-only values in the source dictionary are untranslated entries,
        # not reviewed terminology. Do not let them leak into generated Chinese.
        cleaned = re.sub(
            r"\b(?:ACEScg|ACES|sRGB|RGB|RGBA|PBR|HBAO|RTAO|AO|UV|HDR|HS[ILV]|"
            r"IOR|BRDF|SDF|EV|F0|Alpha|OpenGL|DirectX)\b",
            "",
            target,
            flags=re.I,
        )
        if (target.strip() and key and re.search(r"[\u4e00-\u9fff]", target)
                and not re.search(r"[A-Za-z]{3,}", cleaned)):
            result[key] = target.strip()
    return result


def translate_label(source: str, lexicon: dict[tuple[str, ...], str]) -> str:
    words = normalized(source)
    if words in lexicon:
        return lexicon[words]

    # Preserve indexed material-channel names exactly, including their # prefix.
    indexed = re.fullmatch(r"#(\d+)\s+(.+)", source.strip())
    if indexed:
        tail = translate_label(indexed.group(2), lexicon)
        return f"#{indexed.group(1)} {tail}"

    parts: list[str] = []
    index = 0
    while index < len(words):
        match = None
        # Existing reviewed phrases take priority over individual terms.
        for width in range(min(6, len(words) - index), 1, -1):
            candidate = words[index:index + width]
            if candidate in lexicon and len(lexicon[candidate]) <= 36:
                match = (width, lexicon[candidate])
                break
        if match:
            parts.append(match[1])
            index += match[0]
            continue
        word = words[index]
        if word in TERMS:
            parts.append(TERMS[word])
        elif word in ACRONYMS:
            parts.append(ACRONYMS[word])
        elif word.isdigit():
            parts.append(word)
        else:
            # Proper names and uncommon algorithm identifiers remain recognizable.
            parts.append(word[:1].upper() + word[1:])
        index += 1

    result = "".join(parts)
    # Common English noun-phrase patterns that need Chinese word order.
    amount = re.match(r"^(Amount|Number) of (.+)$", source, re.I)
    if amount:
        return translate_label(amount.group(2), lexicon) + "数量"
    return result or source


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    translations = payload["translations"]
    lexicon = make_local_lexicon(translations)
    completed = 0
    for source, target in list(translations.items()):
        if not str(target).strip():
            translations[source] = translate_label(source, lexicon)
            completed += 1
    TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Completed {completed} blank translations in {TARGET}")


if __name__ == "__main__":
    main()

"""Apply reviewed terminology corrections to my_assets_zh.json."""

import json
import re
from pathlib import Path


PATH = (Path(__file__).resolve().parents[3] / "public" / "translations"
        / "my_assets_zh.json")


TEXT_REPLACEMENTS = {
    "破斜纹斜纹": "破斜纹",
    "深色蓝色": "深蓝色",
    "浅色蓝色": "浅蓝色",
    "深色绿色": "深绿色",
    "深色棕色": "深棕色",
    "深色红色": "深红色",
    "深色灰色": "深灰色",
    "浅色绿色": "浅绿色",
    "浅色棕色": "浅棕色",
    "浅色灰色": "浅灰色",
    "鼠灰色灰色": "鼠灰色",
    "玫瑰色金色": "玫瑰金",
    "超高高光泽": "超高光泽",
    "波点圆点": "波点",
    "紫菀花花朵": "紫菀花",
    "梵高更": "梵高",
    "皇家蓝牛津纺": "皇家牛津纺",
    "拉绒向下": "向下拉绒",
    "拉绒向上": "向上拉绒",
    "拉绒下": "向下拉绒",
    "拉绒上": "向上拉绒",
    "拉绒左侧": "向左拉绒",
    "拉绒右侧": "向右拉绒",
    "拉绒左": "向左拉绒",
    "拉绒右": "向右拉绒",
    "平纹编织": "平纹组织",
    "斜纹编织": "斜纹组织",
    "缎纹编织": "缎纹组织",
    "方平组织编织": "方平组织",
    "人字纹编织": "人字纹组织",
    "蜂窝编织": "蜂窝组织",
    "绉纹编织": "绉纹组织",
    "罗缎编织": "罗缎组织",
    "横棱纹编织": "横棱纹组织",
    "牛津纺编织": "牛津纺组织",
    "防撕裂布编织": "防撕裂组织",
    "泡泡纱编织": "泡泡纱组织",
    "华夫格编织": "华夫格组织",
    "双布料编织": "双层布组织",
    "贝德福灯芯绒绳纹编织": "贝德福灯芯绒组织",
    "马特拉塞绗缝编织": "马特拉塞组织",
    "珠地布编织": "珠地组织",
    "纱罗 / 纱布编织": "纱罗/纱布组织",
    "蓝蓝色": "蓝",
    "红红色": "红",
    "黄色赭黄色": "赭黄色",
    "什锦什锦果色": "什锦果色",
    "蓝绿色蓝色": "蓝绿色",
    "水绿色绿色": "水绿色",
    "绿色绿色": "绿色",
    "焦橙色橙色": "焦橙色",
    "机织织物": "机织面料",
    "顶部部分": "顶部",
    "底部部分": "底部",
    "中部部分": "中部",
    "定义式编织": "定义式组织",
    "纹理化编织": "纹理化组织",
}


OVERRIDES = {
    "Warp Twist": "经纱捻合",
    "Weft Twist": "纬纱捻合",
    "Warp Twist Height Amount": "经纱捻合高度幅度",
    "Weft Twist Height Amount": "纬纱捻合高度幅度",
    "Fuzz Height Amount": "绒毛高度幅度",
    "Leno Twist Amount": "纱罗捻合量",
    "Crepe Texture Amount": "绉纹纹理强度",
    "Color Under Leather": "皮革底层颜色",
    "Custom Color Under Leather": "自定义皮革底层颜色",
    "Blue On Dark Blue Fabric": "深蓝色织物上的蓝色",
    "Metallic Paint Alcantara": "金属漆阿尔坎塔拉",
    "Bull Large Grain Switch Quilt": "大纹理牛皮交错绗缝",
    "bull_large_grain_switch_quilt": "大纹理牛皮交错绗缝",
    "Alcantara Switch Quilt": "阿尔坎塔拉交错绗缝",
    "alcantara_switch_quilt": "阿尔坎塔拉交错绗缝",
    "Satin Weave 7/1 (8-End, Step 3 MVP)": "7/1 缎纹组织（8 枚，步进 3，MVP）",
    "Satin Weave 8/1 (9-End, Step 4 MVP)": "8/1 缎纹组织（9 枚，步进 4，MVP）",
    "GiottosBlue - DevilsBath (WI17)": "乔托蓝 - 魔鬼浴场（WI17）",
    "nyanneco_fabric_weave_generator": "Nyanneco（喵猫）织物组织生成器",
    "Nyanneco": "Nyanneco（喵猫）",
    "Color Metal": "金属颜色",
    "Color Paint": "漆面颜色",
    "In Cut Color": "切口内侧颜色",
    "Use In Cut Color": "使用切口内侧颜色",
    "Use Pattern In Opacity": "在不透明度中使用图案",
    "Warp Yarn Metallic": "经纱金属度",
    "Warp Yarn Roughness": "经纱粗糙度",
    "Weft Yarn Metallic": "纬纱金属度",
    "Weft Yarn Roughness": "纬纱粗糙度",
    "Yarn Stripe Is Metallic": "纱线条纹使用金属属性",
    "Yarn Twist Metallic 01": "纱线捻合金属度 01",
    "Yarn Twist Metallic 02": "纱线捻合金属度 02",
    "Yarn Twist Metallic 03": "纱线捻合金属度 03",
    "Holes Depth Random": "孔洞深度随机度",
    "Holes Size Random": "孔洞尺寸随机度",
    "Weave Beads Intensity": "织纹珠粒强度",
    "Weave In Lace Color": "嵌织蕾丝颜色",
    "Weave In Striped Knit": "嵌织条纹针织",
    "weave_in_striped_knit": "嵌织条纹针织",
    "Weave In Yarn Color": "嵌织纱线颜色",
    "Weave Strength": "织纹强度",
    "Blue On Blue Stitches": "蓝色底上的蓝色缝线",
    "Brown On Brown Stitches": "棕色底上的棕色缝线",
    "Green On Dark Green Fabric": "深绿色织物上的绿色",
    "Sand On Sand Color Stitches": "沙色底上的同色缝线",
    "End Left": "左端",
    "End Left & Right": "左右两端",
    "End Right": "右端",
    "Matelasse": "马特拉塞绗缝织物",
    "Matelasse Cell Size (threads)": "马特拉塞单元尺寸（线数）",
    "Matelasse Padding Height": "马特拉塞填充高度",
    "Polyester Powder Paint Hammered": "锤纹聚酯粉末涂层",
    "polyester_powder_paint_hammered": "锤纹聚酯粉末涂层",
    "Topstitch Thread Fabric": "明线缝纫线",
    "topstitch_thread_fabric": "明线缝纫线",
    "Weave Amplitude": "织纹振幅",
    "Weave Pattern": "织纹图案",
    "Taurillon Medium Perforated Dots": "中等纹理小牛皮圆点冲孔",
    "Taurillon Medium Perforated X Dots": "中等纹理小牛皮 X 形圆点冲孔",
    "taurillon_medium_perforated_dots": "中等纹理小牛皮圆点冲孔",
    "taurillon_medium_perforated_x_dots": "中等纹理小牛皮 X 形圆点冲孔",
}


METALLIC_PARAMETER_PATTERNS = (
    r"Metallic(?: \d+)?",
    r"Metallic Invert",
    r"(?:Beads|Pattern|Rivet|Silk|Topstitch|Warp Yarn|Weft Yarn|"
    r"Welt Center|Yarn|Custom Pattern) Metallic(?: \d+)?",
)


def is_metallic_parameter(source):
    return any(re.fullmatch(pattern, source) for pattern in METALLIC_PARAMETER_PATTERNS)


def main():
    payload = json.loads(PATH.read_text(encoding="utf-8-sig"))
    translations = payload["translations"]

    # This is the extractor's own output filename, not a Painter label.
    translations.pop("my_assets_zh", None)

    for source, target in list(translations.items()):
        reviewed = str(target)
        for old, new in TEXT_REPLACEMENTS.items():
            reviewed = reviewed.replace(old, new)
        reviewed = re.sub(r"(\d+(?:/|x)\d+) 编织", r"\1 组织", reviewed)
        # "Metallic" is a numeric channel when used as a parameter, while it
        # is an adjective for asset names.
        if "金属感" in reviewed:
            reviewed = reviewed.replace("金属感", "金属质感")
        if is_metallic_parameter(source):
            reviewed = reviewed.replace("金属质感", "金属度")
        translations[source] = reviewed

    translations.update({key: value for key, value in OVERRIDES.items()
                         if key in translations})

    specific = {
        "Reflection Metallic Scale": "反射金属度缩放",
        "Use Metallic": "使用金属度",
        "Cross Stitch Is Metallic": "十字缝线使用金属属性",
        "Lace Stripe Is Metallic": "蕾丝条纹使用金属属性",
    }
    translations.update({key: value for key, value in specific.items()
                         if key in translations})

    payload.setdefault("extraction", {})["term_count"] = len(translations)
    payload["translations"] = dict(
        sorted(translations.items(), key=lambda item: item[0].casefold())
    )
    PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    missing = [key for key, value in translations.items() if not value.strip()]
    if missing:
        raise SystemExit("仍有空译文：" + ", ".join(missing))
    print(f"校对完成：{len(translations)} 条，空译文 0 条")


if __name__ == "__main__":
    main()

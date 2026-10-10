"""
textures.py —— 程序化表面贴图类别

实体球在片元着色器里按「相对自转轴的纬度 / 经度」生成程序化纹理，
无需外部图片，可复现、无随机数（噪声为确定性哈希）。

本模块只负责「哪个天体用哪种纹理」，纹理生成本身在 viewport.py 的 FS_SPHERE。
"""

TEX_PLAIN = 0      # 纯色（默认）
TEX_GAS = 1        # 气态巨行星：纬向条带 + 湍流
TEX_ROCKY = 2      # 岩质/卫星：斑驳噪声 + 暗色月海
TEX_EARTH = 3      # 类地：海洋 + 大陆 + 极冠
TEX_ICE = 4        # 冰质/浓云：柔和带状 + 极冠
TEX_STAR = 5       # 恒星：颗粒 + 暗斑

GAS_NAMES = {"木星", "土星"}
EARTH_NAMES = {"地球"}
ICE_NAMES = {"金星", "天王星", "海王星", "木卫二", "土卫二"}
ROCKY_NAMES = {"火星", "水星", "月球", "冥王星", "木卫一", "木卫三", "木卫四",
               "土卫六", "海卫一", "谷神星", "灶神星"}


def texture_kind(body) -> int:
    """天体 → 程序化纹理类别"""
    bt = getattr(body, "body_type", None)
    name = getattr(body, "name", "") or ""
    if bt in ("star", "host_star"):
        return TEX_STAR
    if bt == "blackhole":
        return TEX_PLAIN       # 黑洞不渲染实体球，纹理无意义
    if name in GAS_NAMES:
        return TEX_GAS
    if name in EARTH_NAMES:
        return TEX_EARTH
    if name in ICE_NAMES:
        return TEX_ICE
    if name in ROCKY_NAMES:
        return TEX_ROCKY
    # 其余太阳系天体：有固体表面按岩质，气体/未知按纯色
    if bt in ("planet_solar", "dwarf", "moon"):
        return TEX_ROCKY
    return TEX_PLAIN
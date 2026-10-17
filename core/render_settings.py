"""render_settings.py —— 渲染性能档位与「天体数量动态适配」参数

本模块只提供纯数据与纯函数（不依赖 Qt / GL），供视口与设置面板共用：

    * 三档性能档位（高性能 / 均衡 / 省电），各自给出天体数量上限、
      动态适配的起步数量、最小数量，以及增减步长；
    * 动态适配策略 next_count()：以「稳定 30 FPS 以上」为目标，
      FPS 偏低则减少渲染数量、偏高则增加（带滞回区间，避免抖动），
      在用户显卡可承受的范围内尽可能多地显示天体，上限 100 万颗。

术语说明：这里的「天体数量」指视口中实例化点精灵渲染的小天体/行星点云数量
（太阳系小天体族群 + 行星标记），全部由 GPU 顶点着色器按开普勒方程实时求解，
CPU 每帧零开销；因此数量可在 5 千 ~ 100 万之间自由伸缩而不重新生成顶点。
"""

# 性能档位键（顺序即设置面板展示顺序：从高性能到省电）
TIERS = ("high", "balanced", "power")

# 档位中文名（供 i18n.tr 翻译）
TIER_LABELS = {
    "high": "高性能",
    "balanced": "均衡",
    "power": "省电",
}

# 动态适配的目标帧率：稳定在该值以上（提示词要求 30 FPS 以上）
TARGET_FPS = 30.0

# 数量硬上限：100 万颗（提示词要求）
PLANET_HARD_CAP = 1_000_000

# 数量硬下限：低于此值画面过空，不再下调
PLANET_HARD_FLOOR = 2_000

# 各档位参数：
#   cap      该档允许的最大天体数量（<= PLANET_HARD_CAP）
#   initial  首次进入 / 切换档位时的起步数量
#   floor    动态下调的下限（>= PLANET_HARD_FLOOR）
#   up/down  上调 / 下调的比例步长
# 上调与下调使用不同阈值，形成滞回区间，避免在临界点反复抖动。
TIER_CONFIG = {
    "high": {
        "cap": PLANET_HARD_CAP,
        "initial": 150_000,
        "floor": 50_000,
        "up": 1.25,
        "down": 0.80,
    },
    "balanced": {
        "cap": 500_000,
        "initial": 60_000,
        "floor": 20_000,
        "up": 1.20,
        "down": 0.82,
    },
    "power": {
        "cap": 120_000,
        "initial": 20_000,
        "floor": 5_000,
        "up": 1.15,
        "down": 0.85,
    },
}

# FPS 判定阈值（相对目标帧率的倍率）：
#   < down_fps : 下调数量
#   > up_fps   : 上调数量
#   介于两者之间：保持（滞回带）
_DOWN_FPS = TARGET_FPS * 0.95          # 28.5 FPS
_UP_FPS = TARGET_FPS * 1.60            # 48.0 FPS


def config(tier: str) -> dict:
    """返回指定档位的参数（未知档位回退均衡）。"""
    return TIER_CONFIG.get(tier, TIER_CONFIG["balanced"])


def initial_count(tier: str) -> int:
    return clamp_count(int(config(tier)["initial"]), tier)


def clamp_count(n: int, tier: str) -> int:
    """把数量夹到 [该档下限, 该档上限] 区间内。"""
    cfg = config(tier)
    lo = max(PLANET_HARD_FLOOR, int(cfg["floor"]))
    hi = min(PLANET_HARD_CAP, int(cfg["cap"]))
    return int(max(lo, min(hi, int(n))))


def max_count(tier: str) -> int:
    """该档位允许的最大数量（不超过 100 万）。"""
    return min(PLANET_HARD_CAP, int(config(tier)["cap"]))


def next_count(tier: str, current: int, fps: float) -> int:
    """动态适配核心：按实测 FPS 计算下一阶段应渲染的天体数量。

    * fps <= 0（尚未测得）或 fps 处于滞回带内 → 不变（返回 -1 表示无需调整）；
    * fps 低于下调阈值 → 按 down 比例减少（不低于该档下限）；
    * fps 高于上调阈值 → 按 up 比例增加（不超过该档上限 = 100 万）。

    返回 -1 表示「本次无需调整」。
    """
    if fps <= 0.0:
        return -1
    cfg = config(tier)
    lo = max(PLANET_HARD_FLOOR, int(cfg["floor"]))
    hi = min(PLANET_HARD_CAP, int(cfg["cap"]))
    cur = int(max(lo, min(hi, current)))
    if fps < _DOWN_FPS:
        new = int(cur * float(cfg["down"]))
        new = max(lo, new)
    elif fps > _UP_FPS:
        new = int(cur * float(cfg["up"]))
        new = min(hi, new)
    else:
        return -1
    return new if new != cur else -1
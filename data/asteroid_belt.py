"""
asteroid_belt.py —— 太阳系小天体点云数据生成（多族群）

按公开的小天体族群统计分布生成点云轨道根数，覆盖从近地到离散盘：
    1. 近地小行星（NEO）        0.8–1.6 AU，偏心率/倾角较大
    2. 主小行星带（Main Belt）  2.06–3.28 AU，挖掉 4:1/3:1/5:2/7:3/2:1 柯克伍德空隙
    3. 希尔达群（Hilda）        3.7–4.2 AU，木星 3:2 共振（a ≈ 3.97 AU）
    4. 木星特洛伊（Trojans）     a ≈ 5.204 AU，聚集在木星前后 60°（L4/L5 两群）
    5. 半人马（Centaurs）        5.5–30 AU，倾角/偏心率大
    6. 柯伊伯带（Kuiper Belt）   38.5–48 AU，含冥族天体（3:2 共振 a ≈ 39.4）与冷/热经典带
    7. 离散盘（Scattered Disk）  30–100 AU，高偏心率稀疏晕

位置不在这里计算：由 GPU 顶点着色器按开普勒方程实时求解，CPU 每帧零开销
（见 scene/viewport.py 的 VS_BELT）。

输出 (N, 10) float32，每行：
    [a, e, i, Ω, ω, M0, r, g, b, size]
    长度单位 AU；角度单位弧度

科学诚实性说明：
  * 各族群的半长轴区间、共振位置、倾角/偏心率分布取自公开的小天体族群统计
    （柯克伍德空隙、木星特洛伊 L4/L5 聚集、柯伊伯带 3:2 共振与 48 AU「柯伊伯断崖」等）；
  * 个体轨道根数为按上述分布的统计采样（固定随机种子，可复现），**非逐颗实测值**，
    故本点云仅用于呈现族群的空间分布形态，不用于个体定位；
  * 木星特洛伊的平黄经以木星 J2000 平黄经为基准偏移 ±60°，半长轴与木星一致，
    因而与木星 1:1 共振同步前进（保持前后 60° 的聚集形态）。
"""
import numpy as np

BELT_MAX = 100000                                  # 预生成上限（全部族群合计）
JUPITER_L0_DEG = 34.39644051                       # 木星 J2000 平黄经（JPL 近似根数 L）
TROJAN_A = 5.2043                                  # 特洛伊群 1:1 共振半长轴（AU）
TROJAN_LIBRATION_DEG = 60.0                        # 距木星平黄经的聚集中心（L4/L5）
KIRKWOOD_GAPS = (2.06, 2.50, 2.82, 2.95, 3.27)     # 4:1 / 3:1 / 5:2 / 7:3 / 2:1 共振
KIRKWOOD_WIDTHS = (0.020, 0.035, 0.030, 0.025, 0.030)
A_MIN, A_MAX = 2.06, 3.28
KUIPER_CLIFF = 48.0                                # 经典柯伊伯带外缘（"柯伊伯断崖"）

# 各族群数量配比：按真实相对数量的粗略比例分配，兼顾视觉均衡
POPULATION_FRACTIONS = (
    ("neo", 0.02),
    ("main", 0.34),
    ("hilda", 0.04),
    ("trojan", 0.20),
    ("centaur", 0.02),
    ("kuiper", 0.31),
    ("scattered", 0.07),
)

# 各族群配色：(S/岩质型, C/暗色型)
_COLORS = {
    "neo": ((0.70, 0.60, 0.46), (0.48, 0.47, 0.50)),
    "main": ((0.72, 0.62, 0.48), (0.46, 0.46, 0.50)),
    "hilda": ((0.68, 0.58, 0.46), (0.44, 0.44, 0.48)),
    "trojan": ((0.48, 0.38, 0.32), (0.36, 0.32, 0.34)),
    "centaur": ((0.46, 0.50, 0.56), (0.38, 0.44, 0.50)),
    "kuiper": ((0.62, 0.48, 0.38), (0.50, 0.42, 0.40)),
    "scattered": ((0.56, 0.42, 0.36), (0.44, 0.38, 0.38)),
}


# ---------- 分布采样工具 ----------
def _semi_major(rng, count: int) -> np.ndarray:
    """主带半长轴采样：区间内均匀分布 + 柯克伍德空隙拒绝采样"""
    out = []
    need = count
    for _ in range(200):
        if need <= 0:
            break
        cand = rng.uniform(A_MIN, A_MAX, max(need * 2, 64))
        keep = np.ones_like(cand)
        for gap, width in zip(KIRKWOOD_GAPS, KIRKWOOD_WIDTHS):
            keep *= 1.0 - 0.95 * np.exp(-((cand - gap) / width) ** 2)
        acc = cand[rng.random(cand.size) < keep]
        if acc.size == 0:
            continue
        out.append(acc[:need])
        need -= int(min(need, acc.size))
    if need > 0:                                   # 极端兜底，保证数量
        out.append(rng.uniform(A_MIN, A_MAX, need))
    return np.concatenate(out)[:count]


def _beta_e(rng, count: int, a: float, b: float, scale: float,
            e_max: float) -> np.ndarray:
    """偏心率：β 分布（多数接近圆轨道），并截断到 e_max（保证开普勒迭代收敛）"""
    return np.clip(rng.beta(a, b, count) * scale, 0.0, e_max)


def _incl(rng, count: int, sigma: float, i_max: float) -> np.ndarray:
    """倾角（度）：以黄道面为中心聚集，上限 i_max"""
    return np.clip(np.abs(rng.normal(0.0, sigma, count)), 0.0, i_max)


def _color(rng, count: int, key: str) -> np.ndarray:
    """族群配色：岩质型与暗色型约各半，叠加少量亮度扰动"""
    rock, dark = _COLORS[key]
    is_rock = rng.random(count)[:, None] < 0.5
    base = np.where(is_rock, np.array(rock), np.array(dark))
    return np.clip(base + rng.normal(0.0, 0.05, (count, 3)), 0.15, 1.0)


def _size(rng, count: int) -> np.ndarray:
    """点大小：幂律分布——绝大多数 1px，极少数更大更亮"""
    return 1.0 + 2.2 * rng.random(count) ** 8


def _angles(rng, count: int):
    """Ω / ω / M0 三组角度：均匀分布"""
    return (rng.uniform(0.0, 2.0 * np.pi, count),
            rng.uniform(0.0, 2.0 * np.pi, count),
            rng.uniform(-np.pi, np.pi, count))


def _elements(rng, key: str, n: int):
    """按族群生成 (a, e, i_deg, Ω, ω, M0)"""
    if key == "neo":
        a = rng.uniform(0.80, 1.60, n)
        e = _beta_e(rng, n, 1.2, 3.0, 0.70, 0.55)
        inc = _incl(rng, n, 10.0, 30.0)
    elif key == "main":
        a = _semi_major(rng, n)
        e = _beta_e(rng, n, 1.6, 5.0, 0.55, 0.32)
        inc = _incl(rng, n, 8.5, 24.0)
    elif key == "hilda":
        a = np.clip(3.97 + rng.normal(0.0, 0.12, n), 3.70, 4.20)
        e = _beta_e(rng, n, 1.5, 4.0, 0.40, 0.35)
        inc = _incl(rng, n, 7.0, 20.0)
    elif key == "trojan":
        a = TROJAN_A + rng.normal(0.0, 0.012, n)
        e = _beta_e(rng, n, 1.4, 4.5, 0.40, 0.22)
        inc = _incl(rng, n, 10.0, 40.0)
    elif key == "centaur":
        a = 10.0 ** rng.uniform(np.log10(5.5), np.log10(30.0), n)
        e = _beta_e(rng, n, 1.2, 2.5, 0.65, 0.50)
        inc = _incl(rng, n, 12.0, 35.0)
    elif key == "kuiper":
        # 冥族天体（3:2 共振）: 经典带（冷/热）≈ 3 : 7
        n_pl = int(round(n * 0.30))
        n_hot = int(round(n * 0.25))
        n_cold = n - n_pl - n_hot
        a = np.concatenate([
            np.clip(39.4 + rng.normal(0.0, 0.35, n_pl), 38.5, 40.5),
            np.clip(rng.normal(44.3, 1.2, n_cold), 42.0, KUIPER_CLIFF),
            np.clip(rng.normal(45.0, 2.0, n_hot), 42.0, KUIPER_CLIFF),
        ])
        e = np.concatenate([
            _beta_e(rng, n_pl, 1.5, 4.0, 0.35, 0.30),
            _beta_e(rng, n_cold, 1.2, 5.0, 0.22, 0.12),
            _beta_e(rng, n_hot, 1.4, 3.5, 0.35, 0.28),
        ])
        inc = np.concatenate([
            _incl(rng, n_pl, 10.0, 30.0),
            _incl(rng, n_cold, 2.2, 5.0),                       # 冷经典带：近黄道面
            np.clip(np.abs(rng.normal(0.0, 9.0, n_hot)), 5.0, 32.0),
        ])
    elif key == "scattered":
        a = 10.0 ** rng.uniform(np.log10(30.0), np.log10(100.0), n)
        e = _beta_e(rng, n, 1.3, 2.2, 0.75, 0.55)
        inc = _incl(rng, n, 12.0, 40.0)
    else:
        raise ValueError(f"未知族群: {key}")

    Om, om, M0 = _angles(rng, n)
    if key == "trojan":
        # 平黄经 λ = Ω + ω + M 落在木星前后 60° 附近（L4 / L5 两个群）
        side = np.where(rng.random(n) < 0.5, 1.0, -1.0)
        lam = (np.radians(JUPITER_L0_DEG) + side * np.radians(TROJAN_LIBRATION_DEG)
               + rng.normal(0.0, np.radians(12.0), n))
        M0 = lam - Om - om
    return a, e, inc, Om, om, M0


def generate_belt(count: int = BELT_MAX, seed: int = 20261008) -> np.ndarray:
    """生成太阳系小天体点云轨道根数（可复现：固定随机种子）

    输出顺序已按固定种子打散，因此密度档位取前 N 个点时，
    各族群仍按配比等比保留（而不是只剩排在前面的族群）。
    """
    rng = np.random.default_rng(seed)

    edges = np.cumsum([0.0] + [f for _, f in POPULATION_FRACTIONS])
    parts = []
    for i, (key, _frac) in enumerate(POPULATION_FRACTIONS):
        n = int(round(count * edges[i + 1])) - int(round(count * edges[i]))
        if n <= 0:
            continue
        a, e, inc_deg, Om, om, M0 = _elements(rng, key, n)
        row = np.empty((n, 10), dtype=np.float64)
        row[:, 0] = a
        row[:, 1] = e
        row[:, 2] = np.radians(inc_deg)
        row[:, 3] = Om
        row[:, 4] = om
        row[:, 5] = M0
        row[:, 6:9] = _color(rng, n, key)
        row[:, 9] = _size(rng, n)
        parts.append(row)

    data = np.concatenate(parts, axis=0)
    rng.shuffle(data, axis=0)
    return data.astype(np.float32)

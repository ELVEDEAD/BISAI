"""
viewport.py —— 三维主视口（模块 A）

渲染管线（QtOpenGL 3.3 Core）：
    程序化星空（真实亮星）→ 黄道网格 → 轨道线（真实三维曲线，单次 draw call）
    → 天体点精灵 → QPainter 叠加层（标签 + HUD）

精度策略（见 3.3 节）：
    - 浮点原点偏移：CPU 端以相机眼点为局部原点（float64），相对坐标转 float32 上传
    - 对数缩放：视距 1e-8 ~ 1e10 AU 跨 18 个数量级
    - 动态 near/far：随视距自适应，避免深度缓冲精度爆炸

科学诚实性：
    - 可视化比例模式：天体半径放大 N 倍，HUD 明确标注"半径已放大，距离为真实值"
    - 真实比例模式：半径按真实值（天体为亚像素，以最小标记点显示）
"""
import math
import time as _time
import numpy as np

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import (QSurfaceFormat, QOpenGLShaderProgram, QOpenGLShader,
                         QOpenGLBuffer, QOpenGLVertexArrayObject, QMatrix4x4,
                         QPainter, QFont, QColor, QVector3D)
from PyQt5.QtWidgets import QOpenGLWidget, QMenu, QAction

from scene.camera import OrbitCamera, FOV_DEG, MIN_DIST
from scene import glfuncs
from scene.view_gizmo import ViewGizmo
from core.time_system import SimulationClock
from core.constants import (AU_KM, J2000_JD, format_distance, scale_tier_name,
                            GRADE_DESCRIPTION, format_light_time)
from core.kepler import exo_relative_positions_vec
from core.sun_evolution import (SUN_NOW_AGE_GYR, age_from_jd, blackbody_rgb,
                                orbit_expansion, sun_state,
                                max_radius_au_between, SOLAR_RADIUS_AU)
from core.star_evolution import star_state_vec, rgb_duration_gyr, PHASE_MS
from core.physics import roche_limit_km, roche_limit_fluid_km, mean_density_gcm3
from core.constants import R_SUN_KM, M_SUN_PER_EARTH
from core import render_settings
from scene.textures import texture_kind
from data.solar_system import EPHEMERIS_VALID_YEARS, RINGS, POLES, saturn_ring_alpha

STAR_SPHERE_RADIUS = 5e8   # 背景亮星天球半径（AU，深度关闭，仅装饰定位）

# 轴向视角（View Gizmo / Numpad 1·3·7）是否切正交投影（需求 3.2）：
# 默认 False —— 切轴向视角保持软件当前的透视投影，不像 Blender 自动切正交。
# 预留开关供以后启用正交轴向视角（需在 _compute_matrices 增加正交投影路径）。
AXIS_VIEW_ORTHO = False

# ---------- 远距标记点尺寸（点精灵直径，像素）----------
# 按真实半径做幂律缩放：指数 0=等大，1=严格等比。
# 取 0.5 使木星/地球/水星的相对大小肉眼可辨，又不会让小天体小到看不见。
MARKER_REF_KM = 6371.0     # 参考半径（地球）
MARKER_REF_PX = 6.0        # 地球对应的标记点直径
MARKER_EXP = 0.5           # 幂律指数
MARKER_MIN_PX = 2.5
MARKER_MAX_PX = 40.0
# 系外行星位于秒差距级距离：远看应为细小光点，不按半径放大
EXO_MARKER_PX = 2.2

# 母行星视直径超过该值（像素）才绘制其行星环与卫星轨道（拉近到行星系才可见）
NEAR_DIAM_PX = 14.0

# ---------- 自转轴可视化配色 ----------
AXIS_COLOR = (0.55, 0.87, 0.98)     # 自转极轴（青）
EQ_COLOR = (0.95, 0.76, 0.30)       # 赤道面圆环（琥珀）
MER_COLOR = (0.80, 0.82, 0.88)      # 子午线（浅灰，随自转转动）
AXIS_LEN = 1.45                     # 极轴延伸长度（以行星半径为单位）
RING_R = 1.004                      # 赤道环/子午线半径（略高于球面，避免 z-fighting）
AXIS_SEG = 72                       # 赤道环/子午线采样点数

# ---------- 着色器 ----------
VS_POINT = """
#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_color;
layout(location=2) in float a_size;
uniform mat4 u_mvp;
out vec3 v_color;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    gl_PointSize = a_size;
    v_color = a_color;
}
"""
FS_POINT = """
#version 330 core
in vec3 v_color;
uniform float u_alpha;
out vec4 frag;
void main() {
    vec2 d = gl_PointCoord - vec2(0.5);
    float r = length(d) * 2.0;
    if (r > 1.0) discard;
    float glow = smoothstep(1.0, 0.35, r);
    frag = vec4(v_color * (0.55 + 0.75 * glow), u_alpha * (0.25 + 0.75 * glow));
}
"""
VS_LINE = """
#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_color;
uniform mat4 u_mvp;
out vec3 v_color;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    v_color = a_color;
}
"""
FS_LINE = """
#version 330 core
in vec3 v_color;
uniform float u_alpha;
out vec4 frag;
void main() { frag = vec4(v_color, u_alpha); }
"""

# 太阳系小天体（近地/主带/特洛伊/半人马/柯伊伯带/离散盘）：
# 轨道根数在顶点着色器里按开普勒方程实时求解（CPU 每帧零开销）
VS_BELT = """
#version 330 core
layout(location=0) in vec3 a_elem;     // a, e, i
layout(location=1) in vec3 a_ang;      // Omega, omega, M0
layout(location=2) in vec3 a_color;
layout(location=3) in float a_size;
uniform mat4 u_mvp;
uniform vec3 u_eye;
uniform float u_t;                     // 自 J2000 起的天数
out vec3 v_color;
const float PI = 3.14159265358979;

void main() {
    float a = a_elem.x, e = a_elem.y, inc = a_elem.z;
    float Om = a_ang.x, om = a_ang.y, M0 = a_ang.z;

    float n = 2.0 * PI / (365.25 * pow(a, 1.5));       // 平均运动 rad/天
    float M = M0 + n * u_t;
    M = mod(M + PI, 2.0 * PI) - PI;

    float E = M + e * sin(M);                          // 牛顿迭代解开普勒方程
    for (int k = 0; k < 6; ++k) {                      // 初值取 M+e·sinM，高偏心率下更稳
        E -= (E - e * sin(E) - M) / (1.0 - e * cos(E));
    }

    float xv = a * (cos(E) - e);
    float yv = a * sqrt(max(1.0 - e * e, 0.0)) * sin(E);

    float cw = cos(om), sw = sin(om);
    float cO = cos(Om), sO = sin(Om);
    float ci = cos(inc), si = sin(inc);

    vec3 p1 = vec3(cw * xv - sw * yv, sw * xv + cw * yv, 0.0);   // 绕 z 转 ω
    vec3 p2 = vec3(p1.x, ci * p1.y, si * p1.y);                  // 绕 x 转 i
    vec3 pos = vec3(cO * p2.x - sO * p2.y, sO * p2.x + cO * p2.y, p2.z);  // 绕 z 转 Ω

    gl_Position = u_mvp * vec4(pos - u_eye, 1.0);
    gl_PointSize = a_size;
    v_color = a_color;
}
"""
FS_BELT = """
#version 330 core
in vec3 v_color;
uniform float u_alpha;
out vec4 frag;
void main() { frag = vec4(v_color, u_alpha); }
"""

# 天体实体球：单位球顶点按「中心 + 半径 × 方向」展开，光照按球面法线计算
# 表面纹理由片元着色器按「相对自转轴的纬度/经度」程序化生成（无外部贴图）
VS_SPHERE = """
#version 330 core
layout(location=0) in vec3 a_pos;      // 眼点相对坐标
layout(location=1) in vec3 a_normal;
layout(location=2) in vec3 a_color;
layout(location=3) in vec3 a_light;    // 指向光源的单位向量（世界系）
layout(location=4) in float a_emis;    // 1=自发光恒星
layout(location=5) in float a_tex;     // 程序化纹理类别
layout(location=6) in vec3 a_axis;     // 自转极轴（世界系单位向量）
layout(location=7) in float a_rot;     // 自转相位（弧度，随时间推进）
uniform mat4 u_mvp;
out vec3 v_pos;
out vec3 v_n;
out vec3 v_c;
out vec3 v_l;
out float v_e;
out float v_tex;
out vec3 v_axis;
out float v_rot;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    v_pos = a_pos;
    v_n = a_normal;
    v_c = a_color;
    v_l = a_light;
    v_e = a_emis;
    v_tex = a_tex;
    v_axis = a_axis;
    v_rot = a_rot;
}
"""
FS_SPHERE = """
#version 330 core
in vec3 v_pos;
in vec3 v_n;
in vec3 v_c;
in vec3 v_l;
in float v_e;
in float v_tex;
in vec3 v_axis;
in float v_rot;
uniform float u_alpha;
out vec4 frag;

// ---- 确定性值噪声（无随机数，可复现）----
float hash31(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float vnoise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash31(i + vec3(0,0,0)), hash31(i + vec3(1,0,0)), f.x),
                   mix(hash31(i + vec3(0,1,0)), hash31(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash31(i + vec3(0,0,1)), hash31(i + vec3(1,0,1)), f.x),
                   mix(hash31(i + vec3(0,1,1)), hash31(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 5; ++i) { s += a * vnoise(p); p *= 2.03; a *= 0.5; }
    return s;
}

// 球面局部坐标（相对自转轴）：经度随自转相位推进
void sphere_uv(vec3 n, vec3 axis, float rot, out float lat, out vec3 sp) {
    vec3 ax = normalize(axis);
    vec3 ref = abs(ax.z) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 0.0, 1.0);
    vec3 t1 = normalize(cross(ax, ref));
    vec3 t2 = cross(ax, t1);
    lat = asin(clamp(dot(n, ax), -1.0, 1.0));
    float lon = atan(dot(n, t2), dot(n, t1)) + rot;
    sp = vec3(cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat));
}

vec3 apply_texture(vec3 base, vec3 n, vec3 axis, float rot, float kind) {
    int k = int(kind + 0.5);
    if (k == 0) return base;                       // 纯色
    float lat; vec3 sp;
    sphere_uv(n, axis, rot, lat, sp);
    float al = abs(lat);
    if (k == 1) {                                  // 气态：纬向条带 + 湍流
        float turb = fbm(sp * 3.0) - 0.5;
        float band = sin(lat * 16.0 + turb * 2.4);
        float s = smoothstep(-0.9, 0.9, band);
        vec3 belt = vec3(0.60, 0.50, 0.40);        // 暗带
        vec3 zone = vec3(1.20, 1.14, 1.00);        // 亮区
        vec3 tint = mix(belt, zone, s);
        float fine = 1.0 + 0.05 * sin(lat * 46.0); // 细纹
        return base * tint * fine * (1.0 + 0.10 * turb);
    }
    if (k == 2) {                                  // 岩质：斑驳 + 暗色月海
        float m = fbm(sp * 3.4);
        vec3 col = base * (0.74 + 0.52 * m);
        float mare = smoothstep(0.42, 0.30, m);    // 低洼处更暗
        col *= (1.0 - 0.34 * mare);
        float crater = smoothstep(0.62, 0.70, fbm(sp * 9.0));
        col = mix(col, col * 0.80, crater);        // 小陨击坑的阴影斑
        return col;
    }
    if (k == 3) {                                  // 类地：海洋 + 大陆 + 极冠
        float c = fbm(sp * 2.3) + 0.08 * fbm(sp * 6.0);
        float land = smoothstep(0.48, 0.56, c);
        vec3 ocean = vec3(0.05, 0.18, 0.42);
        vec3 shore = vec3(0.28, 0.42, 0.20);
        vec3 arid = vec3(0.52, 0.44, 0.26);
        vec3 terra = mix(shore, arid, smoothstep(0.56, 0.72, c));
        vec3 col = mix(ocean, terra, land);
        float cap = smoothstep(1.18, 1.40, al);    // 极冠
        col = mix(col, vec3(0.92, 0.95, 0.98), cap);
        return col;
    }
    if (k == 4) {                                  // 冰质/浓云：柔和带状 + 极冠
        float soft = 0.92 + 0.10 * sin(lat * 6.0 + fbm(sp * 2.0) * 1.5);
        vec3 col = base * soft;
        float cap = smoothstep(1.15, 1.45, al);
        return mix(col, vec3(0.90, 0.94, 0.98), cap * 0.55);
    }
    // k == 5 恒星：颗粒 + 暗斑
    float g = fbm(sp * 7.0);
    vec3 col = base * (0.82 + 0.42 * g);
    float spot = smoothstep(0.34, 0.24, g);
    return mix(col, col * 0.62, spot);
}

void main() {
    vec3 n = normalize(v_n);
    vec3 v = normalize(-v_pos);                 // 片元 → 眼点
    float mu = max(dot(n, v), 0.0);
    vec3 base = apply_texture(v_c, n, v_axis, v_rot, v_tex);
    vec3 col;
    if (v_e > 0.001) {
        // 自发光恒星：v_e 为亮度倍率（太阳=1.0，宿主恒星≈0.18）
        col = base * v_e * (0.82 + 0.5 * mu);   // 临边昏暗效应保留
    } else {
        vec3 l = normalize(v_l);
        float diff = max(dot(n, l), 0.0);
        float fill = max(dot(n, v), 0.0) * 0.14;     // 微弱补光，夜面不至于全黑
        vec3 h = normalize(l + v);
        float spec = pow(max(dot(n, h), 0.0), 28.0) * 0.12;
        col = base * (0.16 + 1.02 * diff + fill) + vec3(spec);
    }
    frag = vec4(col, u_alpha);
}

"""

# 行星环：平面圆环，顶点已烘焙径向透明度（土星按真实环带结构）
VS_RING = """
#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_color;
layout(location=2) in float a_alpha;
uniform mat4 u_mvp;
out vec3 v_color;
out float v_alpha;
void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    v_color = a_color;
    v_alpha = a_alpha;
}
"""
FS_RING = """
#version 330 core
in vec3 v_color;
in float v_alpha;
uniform float u_alpha;
out vec4 frag;
void main() { frag = vec4(v_color, v_alpha * u_alpha); }
"""

# ---------- 星云：全屏四边形 + 程序化体积云 ----------
# 轻量：单次 draw call、纯 GPU 计算、零纹理、零 CPU 每帧开销
VS_NEBULA = """
#version 330 core
layout(location=0) in vec2 a_pos;
uniform mat4 u_inv_proj;
uniform mat4 u_inv_view;
out vec3 v_ray;
void main() {
    vec4 clip = vec4(a_pos, -1.0, 1.0);
    vec4 view = u_inv_proj * clip;
    view.w = 0.0;
    v_ray = mat3(u_inv_view) * view.xyz;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

FS_NEBULA = """
#version 330 core
in vec3 v_ray;
uniform float u_time;
out vec4 frag;

float hash31(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float vnoise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash31(i + vec3(0,0,0)), hash31(i + vec3(1,0,0)), f.x),
                   mix(hash31(i + vec3(0,1,0)), hash31(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash31(i + vec3(0,0,1)), hash31(i + vec3(1,0,1)), f.x),
                   mix(hash31(i + vec3(0,1,1)), hash31(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 5; ++i) { s += a * vnoise(p); p *= 2.03; a *= 0.5; }
    return s;
}

void main() {
    vec3 dir = normalize(v_ray);
    float n1 = fbm(dir * 1.4 + vec3(0.0, 0.0, u_time * 0.002));
    float n2 = fbm(dir * 4.2);
    float n3 = fbm(dir * 10.0);
    float gal = exp(-pow(dir.z * 2.8, 2.0));
    float density = n1 * 0.48 + gal * (0.32 + n2 * 0.42) + n3 * 0.10;
    density = pow(max(density, 0.0), 1.75);
    vec3 col_refl     = vec3(0.22, 0.28, 0.55);
    vec3 col_emission = vec3(0.55, 0.18, 0.28);
    vec3 col_dark     = vec3(0.06, 0.05, 0.07);
    float refl_mask   = smoothstep(0.22, 0.48, n2);
    float emit_mask   = smoothstep(0.36, 0.58, n1 + n2 * 0.25);
    float dark_mask   = smoothstep(0.55, 0.30, n1);
    vec3 color = col_refl * refl_mask * 0.55
               + col_emission * emit_mask * 0.75
               + col_dark * dark_mask * 0.28;
    float alpha = density * 0.32;
    frag = vec4(color * alpha, alpha);
}
"""


def make_ring_mesh(inner_r: float, outer_r: float, color, alpha_fn=None,
                   radial: int = 36, seg: int = 96) -> np.ndarray:
    """行星环模板：以母行星半径为单位的平面圆环（环面 z=0）。

    返回 (K,7) float64 顶点 [x, y, z, r, g, b, alpha]；绘制时按
    「母行星中心 + 半径 × 环面基」逐帧展开，径向透明度已烘焙进顶点。
    """
    verts = []
    cr, cg, cb = color
    for k in range(radial):
        r0 = inner_r + (outer_r - inner_r) * k / radial
        r1 = inner_r + (outer_r - inner_r) * (k + 1) / radial
        a = float(alpha_fn(0.5 * (r0 + r1))) if alpha_fn else 1.0
        for i in range(seg):
            p0 = 2.0 * math.pi * i / seg
            p1 = 2.0 * math.pi * (i + 1) / seg
            c0, s0 = math.cos(p0), math.sin(p0)
            c1, s1 = math.cos(p1), math.sin(p1)
            A = (r0 * c0, r0 * s0, 0.0)
            B = (r1 * c0, r1 * s0, 0.0)
            C = (r1 * c1, r1 * s1, 0.0)
            D = (r0 * c1, r0 * s1, 0.0)
            for p in (A, B, C, A, C, D):
                verts.append((p[0], p[1], p[2], cr, cg, cb, a))
    return np.asarray(verts, dtype=np.float64)


def _loop_to_pairs(pts: np.ndarray) -> np.ndarray:
    """闭合折线 (K,3) → 显式线段对 (2K,3)（GL_LINES 每两点成一段）"""
    closed = np.vstack([pts, pts[:1]])
    return np.stack([closed[:-1], closed[1:]], axis=1).reshape(-1, 3)


def make_ring_bands_mesh(bands, color, seg: int = 96, max_sub: int = 8) -> np.ndarray:
    """由离散环带列表构建行星环网格（环面 z=0，半径以母行星半径为单位）。

    bands = [(r_inner, r_outer, alpha), ...]，每条环带按宽度自适应细分
    （窄环细分少、宽带细分多，上限 max_sub），环缝处不生成面片，
    从而能真实呈现天王星窄环、海王星环弧、木星薄纱环等结构。

    返回 (K,7) float64 顶点 [x, y, z, r, g, b, alpha]。
    """
    verts = []
    cr, cg, cb = color
    for r0, r1, a in bands:
        if r1 <= r0 or a <= 0.0:
            continue
        sub = max(1, min(max_sub, int(round((r1 - r0) / 0.003))))
        for k in range(sub):
            ra = r0 + (r1 - r0) * k / sub
            rb = r0 + (r1 - r0) * (k + 1) / sub
            for i in range(seg):
                p0 = 2.0 * math.pi * i / seg
                p1 = 2.0 * math.pi * (i + 1) / seg
                c0, s0 = math.cos(p0), math.sin(p0)
                c1, s1 = math.cos(p1), math.sin(p1)
                A = (ra * c0, ra * s0, 0.0)
                B = (rb * c0, rb * s0, 0.0)
                C = (rb * c1, rb * s1, 0.0)
                D = (ra * c1, ra * s1, 0.0)
                for p in (A, B, C, A, C, D):
                    verts.append((p[0], p[1], p[2], cr, cg, cb, a))
    if not verts:
        return np.zeros((0, 7), dtype=np.float64)
    return np.asarray(verts, dtype=np.float64)


def make_unit_sphere(seg: int = 24, ring: int = 16) -> np.ndarray:
    """单位球三角面片顶点表（非索引，GL_TRIANGLES 直接绘制）；法线 = 位置"""
    verts = []
    for j in range(ring):
        t0 = math.pi * j / ring
        t1 = math.pi * (j + 1) / ring
        st0, ct0 = math.sin(t0), math.cos(t0)
        st1, ct1 = math.sin(t1), math.cos(t1)
        for i in range(seg):
            p0 = 2.0 * math.pi * i / seg
            p1 = 2.0 * math.pi * (i + 1) / seg
            cp0, sp0 = math.cos(p0), math.sin(p0)
            cp1, sp1 = math.cos(p1), math.sin(p1)
            a = (st0 * cp0, st0 * sp0, ct0)
            b = (st0 * cp1, st0 * sp1, ct0)
            c = (st1 * cp1, st1 * sp1, ct1)
            d = (st1 * cp0, st1 * sp0, ct1)
            verts += [a, b, c, a, c, d]
    return np.asarray(verts, dtype=np.float64)


def perspective_matrix(fov_deg, aspect, near, far) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at_matrix(eye, center, up) -> np.ndarray:
    fwd = np.asarray(center) - np.asarray(eye)
    n = np.linalg.norm(fwd)
    fwd = fwd / n if n > 1e-15 else np.array([0.0, 1.0, 0.0])
    right = np.cross(fwd, up)
    n = np.linalg.norm(right)
    if n < 1e-12:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / n
    upv = np.cross(right, fwd)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = right, upv, -fwd
    m[0, 3] = -np.dot(right, eye)
    m[1, 3] = -np.dot(upv, eye)
    m[2, 3] = np.dot(fwd, eye)
    return m


class Viewport(QOpenGLWidget):
    """三维主视口：渲染 + Blender 式交互"""
    bodySelected = pyqtSignal(object)      # 单击选中
    compareToggled = pyqtSignal(object)    # 加入/退出对比
    focusChanged = pyqtSignal(str)         # 焦点变化
    followChanged = pyqtSignal(bool)       # 锁定跟随状态变化
    planetCountChanged = pyqtSignal(int)   # 当前渲染天体数量变化（动态适配上报）
    engulfChanged = pyqtSignal(list)       # 被吞噬天体名列表变化（树/面板同步）

    def __init__(self, parent=None):
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(fmt)
        super().__init__(parent)
        self.setFormat(fmt)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(False)

        self.camera = OrbitCamera()
        self.clock = SimulationClock()
        self.bodies = []
        self.stars = []                       # 背景亮星 (pos_unit, size, color)
        self.selected_name = None
        self.locked_name = None               # F键锁定：锁定后点击其他天体不切换选中
        self.compare_names = []               # 对比选择（最多2颗）
        self.measure_names = []               # 测距 A/B（最多2个，主视口画连线）
        self.focus_body = None
        self.follow_body = None               # 锁定跟随的天体（None=不跟随）

        # 显示开关
        self.show_orbits = True
        self.show_labels = True
        self.show_grid = True
        self.show_stars = True
        self.show_trails = True               # 历史尾迹（选中/对比天体）
        self.trail_mode = "clear"             # 尾迹模式：clear 自动清除（保留最近一段并渐隐）| persist 一直显示
        self.show_belt = True                 # 主带小行星点云
        self.belt_count = render_settings.initial_count("high")   # 实际绘制的小天体数量
        # 渲染性能档位与天体数量动态适配（详见 core/render_settings.py）
        #   高性能：上限 100 万；均衡：50 万；省电：12 万。auto 时按实测 FPS 自动伸缩。
        self.perf_tier = "high"               # high / balanced / power
        self.planet_auto = True               # 自动适配（目标 30 FPS 以上）
        # 比例模式：False 可视化比例（标记点按真实半径缩放，相对大小可辨），True 真实比例
        self.real_scale = False
        self.show_solid = True                # 实体球渲染（近距天体按真实半径绘制球体）
        self.show_moons = True                # 天然卫星
        self.show_satellites = True           # 人造卫星（地球轨道）
        self.show_rings = True                # 行星环
        self.show_axes = True                 # 自转轴（极轴 + 赤道环 + 旋转子午线）
        self.show_nebula = True               # 星云背景（程序化体积云，零 CPU 开销）
        # 引力系统模式：黄道面网格按天体 M/r 引力势下陷（时空弯曲示意）
        self.gravity_mode = False             # 是否启用引力网格（由「引力系统」窗口开启）
        self.gravity_scale = 1.0              # 凹陷强度倍率
        self.gravity_names = None             # 参与下陷的天体名集合（None = 全部有质量天体）
        self.gravity_cells = 96               # 网格分辨率（每轴格数，越大越平滑）
        self.gravity_soften = 3.0             # 软化长度（以网格格距为单位），越大井壁越平滑
        self.gravity_depth_cells = 2.6        # 最深凹陷的视觉深度（以网格格距为单位）
        # 轨迹筛选（阶段5 UI 接入）
        self.filter_solar = True              # 显示太阳系轨道
        self.filter_exo = True                # 显示系外行星轨道
        self.filter_year = (0, 2100)          # 发现年份范围

        # 内部渲染状态
        self._prog_point = None
        self._prog_line = None
        self._prog_belt = None
        self._prog_sphere = None
        self._prog_ring = None
        self._prog_nebula = None
        self._gl_ok = True                    # GL 3.3 可用性（initializeGL 中判定）
        self._gl_msg = ""                     # 不可用时展示给用户的说明
        self._vbo_point = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_line = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_grid = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_star = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_trail = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_belt = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_sphere = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_ring = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_nebula = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self._vao = QOpenGLVertexArrayObject()
        self._n_point = 0
        self._n_line = 0
        self._n_grid = 0
        self._n_star = 0
        self._star_data = np.zeros((0, 7), dtype=np.float32)
        self._star_max_dist = 0.0             # 最远背景恒星距离（AU）
        self._mvp_star = None                 # 背景恒星专用 MVP（独立远裁剪面）
        self._belt_max = 0                    # 预生成的小行星总数
        self._sphere_dirs = None              # 单位球方向模板 (S,3)
        self._sphere_idx = np.zeros(0, dtype=np.int64)   # 本帧画实体球的天体索引
        self._body_rvis = np.zeros(0)         # 各天体实体球半径（AU）
        self._body_diam = np.zeros(0)         # 各天体真实视直径（像素）
        self._body_floor = np.zeros(0)        # 各天体标记点下限（像素）
        self._body_colors = None              # (n,3) 天体颜色
        self._body_lights = None              # (n,3) 指向光源的单位向量
        self._body_emis = None                # (n,)  自发光标记
        self._trail_data = np.zeros((0, 6), dtype=np.float32)
        self._trails = {}                     # {name: (N,3) float64 绝对坐标}
        self._trail_last = 0.0
        self._body_pos = None                 # (n,3) float64 绝对坐标
        self._index_of = {}                   # {name: 索引}
        self._ring_tpl = {}                   # {行星名: (环模板(K,3), 环面基u, 环面基v, 透明度)}
        self._moon_orbits = {}                # {卫星名: (相对母行星轨道点(N,3), 颜色)}
        self._sat_orbits = {}                 # {人造卫星名: (相对地球轨道点(N,3), 颜色)}

        # ---------- 太阳物理演化 ----------
        self._sun_state_cache = None          # 当前帧太阳状态（SunState）
        self._evo_active = False              # 演化激活（深未来）
        self._engulfed = {}                 # 被太阳吞噬的天体 {索引: 吞噬时刻 jd}
        self._vanished_emitted = []         # 上次 engulfChanged 发出的名列表（去重）
        self._engulf_dirty = False          # 本帧吞噬状态有变化（待重建/发信号）
        self._evo_last_jd = None            # 上帧 jd（检测时间跳转→先重算位置再判吞噬）
        # —— 系外宿主恒星演化（star_evolution 模型） ——
        self._star_evo_idx = None           # 参与演化的宿主恒星索引（load 时构建）
        self._star_evo_last_jd = None       # 上次演化计算的 jd（限频 + 推进检测）
        self._star_evo_last_t = 0.0
        self._star_evo_applied = False      # 已应用演化半径/颜色（主序恢复用）
        self._star_evo_lum_idx = None       # 演化中恒星的索引（emis 光度调节）
        self._star_evo_lum = None
        self._shattered = {}                  # 被潮汐撕裂的天体名 → (碎片点(N,3), t0)
        self._shatter_hidden = set()          # 本体已隐藏的撕裂天体索引
        self.evolution_events = []            # [(jd, 太阳年龄Gyr, 事件文本)]
        self._engulf_flash = 0.0              # 吞噬闪光时刻（perf_counter）
        self._orbit_scale_applied = 1.0       # 轨道线已应用的轨道外移因子
        self._sun_mass_applied = 1.0          # 轨道线重建时用的太阳质量（M☉）
        self._last_orbit_rebuild = 0.0        # 轨道线限频重建时刻
        self.show_roche = False               # 洛希极限圈显示开关（选中天体）
        self._demo_shatter = None             # 潮汐撕裂演示状态
        self._axis_basis = {}                 # {行星名: (极轴n, 赤道面基e1, 赤道面基e2)}
        self._proj = None
        self._view = None
        self._mvp = None                      # 绝对坐标用（轨道线/星空/标签投影）
        self._mvp_rel = None                  # 眼点相对坐标用（天体/网格/尾迹/连线）
        self._eye = np.zeros(3)

        # 交互状态
        self._dragging = False
        self._drag_pan = False
        self._last_pos = None
        self._keys = set()
        self._fly_captured = False
        self._center_pos = None

        # 按需渲染（省算力）：空闲时降帧率，交互/聚焦远处天体时恢复满帧。
        # 运动本身仍按真实 dt 推进（clock.update 用真实经过时间），降帧只是
        # 降低重绘频率，天体的运动速度不受影响。
        self.on_demand = True                 # 总开关（默认开启）
        self.render_fps_active = 60           # 交互/聚焦时帧率
        self.render_fps_idle = 15             # 空闲时帧率
        self.fps_limit = 90                   # 帧率上限（0 = 无限制）
        self._active_until = 0.0              # 满帧保持到该时刻（perf_counter）
        self._far_stride = 4                  # 远处天体位置重算间隔（帧）
        self._far_tick = 0
        self._far_pos = None                  # 远处天体位置缓存
        self._far_idx = None                  # 远处天体索引（系外行星 + 宿主恒星 + 黑洞）
        self._near_idx = None                 # 近处天体索引（太阳系 + 卫星）
        self._far_small_idx = None            # 远处天体中的非向量化部分（宿主恒星 + 黑洞）

        # FPS
        self._fps = 0.0
        self._fps_frames = 0
        self._fps_t0 = _time.perf_counter()
        self._last_tick = _time.perf_counter()
        self._adapt_last = 0.0                # 上次天体数量动态适配时刻

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

        # Blender 风格视角导航轴（View Gizmo）：右上角叠加层，
        # 显隐由设置「显示 3D 视角导航轴」控制（默认开；隐藏后快捷键仍可用）
        try:
            from core import app_settings
            _gizmo_on = app_settings.get_show_view_gizmo()
        except Exception:
            _gizmo_on = True
        self._view_gizmo = ViewGizmo(self)
        self._view_gizmo.axisClicked.connect(self._gizmo_view)
        self._view_gizmo.set_shown(_gizmo_on)

    def showEvent(self, ev):
        # 窗口隐藏时停表（切换 3D/2D 模式时避免不可见视口空转）
        self._last_tick = _time.perf_counter()
        if not self._timer.isActive():
            self._timer.start(16)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    # ---------- 数据 ----------
    def load_bodies(self, bodies, stars):
        self.bodies = bodies
        self.stars = stars
        self._index_of = {b.name: i for i, b in enumerate(bodies)}
        self._prepare_arrays()
        self._prepare_gravity()
        self._build_ring_templates()
        self._build_axis_basis()
        self._rebuild_orbits()

    def _prepare_gravity(self):
        """预取各天体质量（M☉），供引力网格按 M/r 计算下陷深度。

        系外行星距太阳系为秒差距量级，不参与太阳系引力网格；
        宿主恒星与黑洞质量计入（黑洞质量极大，凹陷极深）。
        质量缺失者按 0 处理。
        """
        n = len(self.bodies)
        mass = np.zeros(n, dtype=np.float64)
        for i, b in enumerate(self.bodies):
            if b.body_type == "planet_exo":
                continue
            ms = getattr(b, "mass_solar", None)
            if ms is None:
                me = getattr(b, "mass_earth", None)
                ms = (me / 333000.0) if me else None
            if ms and ms > 0:
                mass[i] = float(ms)
        self._grav_mass = mass

    def _prepare_arrays(self):
        """预计算逐帧更新所需的 numpy 数组（系外行星可达数千颗，需向量化）。

        把「系外行星」与「太阳系天体/卫星/恒星」分开：前者用向量化批量计算，
        后者数量少、逐个解析计算；同时预取半径、颜色、宿主星位置等常量数组。
        """
        n = len(self.bodies)
        idx_exo, idx_small, idx_moon, idx_sat = [], [], [], []
        for i, b in enumerate(self.bodies):
            if b.body_type == "planet_exo":
                idx_exo.append(i)
            else:
                idx_small.append(i)
            if b.body_type == "moon":
                idx_moon.append(i)
            elif b.body_type == "satellite":
                idx_sat.append(i)
        self._exo_idx = np.array(idx_exo, dtype=np.int64)
        self._small_idx = idx_small
        self._moon_idx = np.array(idx_moon, dtype=np.int64)
        self._sat_idx = np.array(idx_sat, dtype=np.int64)

        # 按需渲染分组：
        #   近处 = 太阳系天体 + 天然卫星 + ETNO（数量少，每帧解析计算）
        #   远处 = 系外行星（向量化）+ 宿主恒星 + 黑洞 + 近邻恒星 + 星际天体
        #          （秒差距级距离，屏幕上几乎不动，可降频重算）
        _far_types = ("host_star", "blackhole", "nearby_star", "interstellar")
        self._near_idx = [i for i in idx_small
                          if self.bodies[i].body_type not in _far_types]
        self._far_small_idx = [i for i in idx_small
                               if self.bodies[i].body_type in _far_types]
        self._far_idx = np.array(sorted(set(idx_exo) | set(self._far_small_idx)),
                                 dtype=np.int64)
        self._far_pos = None
        self._far_tick = 0

        m = len(self._exo_idx)
        a = np.zeros(m)
        e = np.zeros(m)
        i_deg = np.zeros(m)
        period = np.zeros(m)
        host = np.zeros((m, 3))
        host_has = np.zeros(m, dtype=bool)
        for k, i in enumerate(self._exo_idx):
            b = self.bodies[i]
            a[k] = b.a_au if b.a_au else 0.0
            e[k] = min(max(b.e if b.e is not None else 0.0, 0.0), 0.999)
            i_deg[k] = b.incl_deg if b.incl_deg is not None else 0.0
            period[k] = b.period_days if b.period_days else 0.0
            if b.host_pos is not None:
                host[k] = b.host_pos
                host_has[k] = True
        # 无周期者按开普勒第三定律近似（绕 1 M☉），与标量实现一致
        need_p = period <= 0.0
        period[need_p] = 365.25 * np.power(np.maximum(a[need_p], 0.0), 1.5)
        self._exo_a, self._exo_e, self._exo_i = a, e, i_deg
        self._exo_period, self._exo_host, self._exo_host_has = period, host, host_has

        # 常量数组：半径（nan=无数据）、颜色、恒星/系外行星掩码
        radius = np.full(n, np.nan)
        colors = np.zeros((n, 3))
        is_star = np.zeros(n, dtype=bool)        # 太阳 + 宿主恒星（均自发光）
        is_solar_star = np.zeros(n, dtype=bool)  # 仅太阳（亮度最高）
        is_host_star = np.zeros(n, dtype=bool)   # 宿主恒星（微亮）
        is_blackhole = np.zeros(n, dtype=bool)   # 黑洞（不可见，但参与引力）
        is_exo = np.zeros(n, dtype=bool)
        for i, b in enumerate(self.bodies):
            if b.radius_km:
                radius[i] = b.radius_km
            colors[i] = b.color
            if b.body_type == "star":
                is_star[i] = True
                is_solar_star[i] = True
            elif b.body_type in ("host_star", "nearby_star"):
                is_star[i] = True
                is_host_star[i] = True
            elif b.body_type == "blackhole":
                is_blackhole[i] = True
            elif b.body_type == "planet_exo":
                is_exo[i] = True
        self._radius_km = radius
        self._colors_arr = colors
        self._is_star = is_star
        self._is_solar_star = is_solar_star
        self._is_host_star = is_host_star
        self._is_blackhole = is_blackhole
        self._is_exo = is_exo

        # —— 系外宿主恒星演化数组（core/star_evolution.py 演化模型） ——
        # 参与演化：host_star 且有质量数据、0.5–8 M☉（更大质量需超新星模型，
        # 超出演示范围，保持主序）。年龄缺省按与太阳同龄（4.58 Gyr）。
        star_slot = {}
        s_idx, s_mass, s_age0, s_r0, s_teff0 = [], [], [], [], []
        for i in range(n):
            b = self.bodies[i]
            if b.body_type != "host_star":
                continue
            m_s = b.host_mass_solar
            if not m_s or not (0.5 <= m_s <= 8.0):
                continue
            star_slot[b.name] = len(s_idx)
            s_idx.append(i)
            s_mass.append(m_s)
            s_age0.append(b.host_age if b.host_age else SUN_NOW_AGE_GYR)
            s_r0.append(b.host_radius_solar if b.host_radius_solar else 1.0)
            s_teff0.append(b.host_teff if b.host_teff else 5772.0)
        self._star_evo_idx = np.array(s_idx, dtype=np.int64)
        self._star_evo_mass = np.array(s_mass, dtype=np.float64)
        self._star_evo_age0 = np.array(s_age0, dtype=np.float64)
        self._star_evo_r0 = np.array(s_r0, dtype=np.float64)
        self._star_evo_teff0 = np.array(s_teff0, dtype=np.float64)
        # 系外行星 → 宿主演化槽位（-1 = 宿主不参与演化）
        self._exo_star_slot = (np.full(len(self._exo_idx), -1, dtype=np.int64)
                               if len(self._exo_idx)
                               else np.zeros(0, dtype=np.int64))
        for k in range(len(self._exo_idx)):
            host = self.bodies[int(self._exo_idx[k])].host
            self._exo_star_slot[k] = star_slot.get(host, -1)
        # 原值备份：演化恢复主序时写回（半径影响标记点尺寸，颜色影响渲染）
        self._radius_km0 = radius.copy()
        self._colors_arr0 = colors.copy()
        # 演化基准时刻 = 数据加载完成时的仿真时刻：首次时间跳转即可
        # 启用区间吞噬判定（跳过 RGB 窗口也不漏吞）
        self._evo_last_jd = self.clock.jd
        self._star_evo_last_jd = self.clock.jd

        # 程序化贴图：纹理类别 + 自转极轴（世界系单位向量）+ 自转周期（天，带符号）
        tex = np.zeros(n)
        pole = np.zeros((n, 3))
        pole[:, 2] = 1.0                     # 缺极轴者以黄道法线为轴（条带水平）
        rot_p = np.zeros(n)
        for i, b in enumerate(self.bodies):
            tex[i] = texture_kind(b)
            if getattr(b, "pole_ecl", None) is not None:
                v = np.asarray(b.pole_ecl, dtype=np.float64)
                nn = float(np.linalg.norm(v))
                if nn > 1e-15:
                    pole[i] = v / nn
            rp = getattr(b, "rot_period_days", None)
            if rp:
                rot_p[i] = rp
        self._body_tex = tex
        self._body_pole = pole
        self._rot_period = rot_p
        self._body_rot = np.zeros(n)         # 自转相位（弧度，逐帧更新）

    def _exo_positions(self, jd: float) -> np.ndarray:
        """系外行星位置（向量化）：宿主星位置 + 相对开普勒轨道（AU，绝对坐标）"""
        m = len(self._exo_idx)
        if m == 0:
            return np.zeros((0, 3))
        M = (2.0 * math.pi / np.maximum(self._exo_period, 1e-9)) * (jd - J2000_JD)
        rel = exo_relative_positions_vec(self._exo_a, self._exo_e, self._exo_i, M)
        return self._exo_host + rel

    def _marker_floor_vec(self, r_km: np.ndarray) -> np.ndarray:
        """远距标记点最小直径（向量化版，语义同 _marker_floor）"""
        if self.real_scale:
            return np.full(len(r_km), 2.0)
        r = np.where(np.isnan(r_km) | (r_km <= 0), MARKER_REF_KM, r_km)
        r = np.maximum(r, 1.0)
        px = MARKER_REF_PX * np.power(r / MARKER_REF_KM, MARKER_EXP)
        return np.clip(px, MARKER_MIN_PX, MARKER_MAX_PX)

    def _build_axis_basis(self):
        """预生成各天体自转轴正交基（极轴 n + 赤道面基 e1/e2，J2000 黄道系）。

        极轴取自 Body.pole_ecl（IAU WGCCRE 极轴转入黄道系），赤道面基由极轴
        正交化得到，用于绘制赤道环与随时间转动的子午线。"""
        self._axis_basis = {}
        for b in self.bodies:
            if b.pole_ecl is None or not b.radius_km:
                continue
            n = np.asarray(b.pole_ecl, dtype=np.float64)
            nn = float(np.linalg.norm(n))
            if nn < 1e-15:
                continue
            n = n / nn
            ref = np.array([0.0, 0.0, 1.0])
            if abs(float(np.dot(n, ref))) > 0.9:
                ref = np.array([1.0, 0.0, 0.0])
            e1 = np.cross(ref, n)
            e1 = e1 / max(float(np.linalg.norm(e1)), 1e-15)
            e2 = np.cross(n, e1)
            self._axis_basis[b.name] = (n, e1, e2)

    def _build_ring_templates(self):
        """预生成行星环模板（环面基由母行星真实极轴定向）。

        土星用连续径向剖面（D/C/B/卡西尼环缝/A）；木星/天王星/海王星用离散
        环带列表（晕环、薄纱环、13 条窄环、环弧等），真实呈现环缝与窄环结构。
        """
        from data.loader import _equatorial_to_ecliptic
        from data.solar_system import ring_bands_for
        self._ring_tpl = {}
        for name, cfg in RINGS.items():
            if name not in self._index_of:
                continue
            pole = POLES.get(name)
            if pole is None:
                continue
            n = _equatorial_to_ecliptic(pole[0], pole[1])
            n = n / max(float(np.linalg.norm(n)), 1e-15)
            ref = np.array([0.0, 0.0, 1.0])
            if abs(float(np.dot(n, ref))) > 0.9:
                ref = np.array([1.0, 0.0, 0.0])
            u = np.cross(ref, n)
            u = u / max(float(np.linalg.norm(u)), 1e-15)
            v = np.cross(n, u)
            bands = ring_bands_for(name)
            if bands:
                # 每条环带内 alpha 恒定，径向再细分不产生任何视觉差异，
                # 故不做径向细分（max_sub=1），仅为环向铺足够分段表现曲率
                tpl = make_ring_bands_mesh(bands, cfg["color"], seg=96, max_sub=1)
            elif cfg.get("profile") == "saturn":
                tpl = make_ring_mesh(cfg["inner"], cfg["outer"], cfg["color"],
                                     saturn_ring_alpha, radial=64, seg=128)
            else:
                continue
            if len(tpl):
                self._ring_tpl[name] = (tpl, u, v, float(cfg["alpha"]))

    def _build_moon_orbits(self):
        """预采样卫星轨道（只存相对母天体的形状，母天体位置每帧变化）。

        天然卫星挂母行星；人造卫星挂地球（轨道面含真实倾角，形状各异）。
        """
        self._moon_orbits = {}
        self._sat_orbits = {}
        for b in self.bodies:
            if b.body_type == "moon":
                if b.parent is None or not b.a_au:
                    continue
                u, v = b._moon_plane_basis()
                pts = self._sample_rel_orbit(b, u, v)
                self._moon_orbits[b.name] = (pts, np.array(b.color, dtype=np.float64))
            elif b.body_type == "satellite":
                if b.parent is None or not b.a_au:
                    continue
                u, v = b._satellite_plane_basis()
                pts = self._sample_rel_orbit(b, u, v)
                self._sat_orbits[b.name] = (pts, np.array(b.color, dtype=np.float64))

    @staticmethod
    def _sample_rel_orbit(b, u, v, n: int = 128) -> np.ndarray:
        """相对母天体的开普勒椭圆采样（AU），轨道面由 (u, v) 定向"""
        e = b.e if b.e is not None else 0.0
        E = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        xv = b.a_au * (np.cos(E) - e)
        yv = b.a_au * math.sqrt(max(1.0 - e * e, 0.0)) * np.sin(E)
        return xv[:, None] * u[None, :] + yv[:, None] * v[None, :]

    def _rebuild_orbits(self):
        """预采样全部轨道（真实轨道根数，一次 VBO；应用轨迹筛选与轨道外移）"""
        chunks = []
        idx_chunks = []
        offset = 0
        self._orbit_ranges = {}
        y_lo, y_hi = self.filter_year
        # 太阳质量损失 → 轨道外移：按天体名逐个计算（地球 escape 模式
        # k=1.2，其余 k=1.0），与 position_at_jd 的本体位置保持一致
        m_sun = getattr(self, "_sun_mass_applied", 1.0)
        from core.sun_evolution import orbit_expansion as _oe
        for b in self.bodies:
            bi = self._index_of.get(b.name) if self._index_of else None
            if bi is not None and (bi in self._engulfed or
                                   bi in self._shatter_hidden):
                continue   # 被吞噬/撕裂的天体不再绘制轨道线
            if b.body_type in ("star", "host_star", "blackhole", "moon",
                               "nearby_star", "interstellar"):
                continue
            is_solar = b.body_type in ("planet_solar", "dwarf", "etno")
            if is_solar and not self.filter_solar:
                continue
            if not is_solar and not self.filter_exo:
                continue
            if b.disc_year is not None and not (y_lo <= b.disc_year <= y_hi):
                continue
            from core.kepler import sample_orbit
            if is_solar:
                el = b.elements
                fac = (_oe(m_sun, b.name) if m_sun < 1.0 else 1.0)
                pts = sample_orbit(el.a * fac, el.e, el.i, el.Omega,
                                   el.varpi - el.Omega, 256, closed=True)
            elif b.a_au:
                e = b.e if b.e is not None else 0.0
                i = b.incl_deg if b.incl_deg is not None else 0.0
                pts = sample_orbit(b.a_au, e, i, 0.0, 0.0, 128, closed=True)
            else:
                continue
            # 系外行星轨道挂在宿主星上
            if b.body_type == "planet_exo" and b.host_pos is not None:
                pts = pts + b.host_pos[None, :]
            col = np.tile(np.array(b.color, dtype=np.float64), (len(pts), 1))
            seg = np.hstack([pts, col])
            chunks.append(seg)
            # closed=True 时数组末点 == 首点，相邻索引对即天然闭环
            # （段数 = len(pts)-1，无零长退化段）
            idx = np.arange(offset, offset + len(pts) - 1)
            idx_chunks.append(np.column_stack([
                idx, idx + 1]).ravel())
            self._orbit_ranges[b.name] = (offset, len(pts))
            offset += len(pts)
        if chunks:
            self._orbit_data = np.vstack(chunks).astype(np.float32)
            self._orbit_index = np.concatenate(idx_chunks).astype(np.uint32)
        else:
            self._orbit_data = np.zeros((0, 6), dtype=np.float32)
            self._orbit_index = np.zeros(0, dtype=np.uint32)
        self._build_moon_orbits()
        if self._prog_line is not None:
            self._upload_orbits()

    def set_orbit_filter(self, solar=True, exo=True, year_range=None):
        """轨迹筛选（阶段5 UI 接入）：按类型与发现年份过滤轨道线"""
        self.filter_solar = solar
        self.filter_exo = exo
        if year_range is not None:
            self.filter_year = year_range
        self._rebuild_orbits()

    def set_belt(self, enabled=None, count=None):
        """小行星带开关与密度：count 只改绘制数量（点云已预生成，不重新生成）"""
        if enabled is not None:
            self.show_belt = bool(enabled)
        if count is not None:
            self._apply_planet_count(int(count))
        self.update()

    # ---------- 渲染性能档位 / 天体数量动态适配 ----------
    def set_perf_tier(self, tier: str):
        """切换性能档位（high / balanced / power）：调整数量上限并按档位重置起步数量。"""
        if tier not in render_settings.TIERS:
            return
        self.perf_tier = tier
        self._apply_planet_count(render_settings.initial_count(tier))

    def set_planet_auto(self, enabled: bool):
        """开关天体数量自动适配（关：使用手动设定的固定数量）。"""
        self.planet_auto = bool(enabled)

    def set_planet_count(self, count: int, auto: bool = None):
        """手动设置渲染天体数量；auto 非空时同时切换自动/手动模式。"""
        if auto is not None:
            self.planet_auto = bool(auto)
        self._apply_planet_count(int(count))

    def _apply_planet_count(self, count: int):
        """夹取到当前档位区间并应用；数量变化时发信号（供状态栏显示）。"""
        new = render_settings.clamp_count(count, self.perf_tier)
        if new != self.belt_count:
            self.belt_count = new
            try:
                self.planetCountChanged.emit(new)
            except Exception:
                pass

    def _adapt_planet_count(self, now: float):
        """自动适配：每 1.5s 依实测 FPS 增减渲染天体数量（目标 30 FPS 以上）。"""
        if not self.planet_auto or self.belt_count <= 0:
            return
        if now - self._adapt_last < 1.5:
            return
        self._adapt_last = now
        nxt = render_settings.next_count(self.perf_tier, self.belt_count, self._fps)
        if nxt > 0:
            self._apply_planet_count(nxt)

    def set_solid(self, enabled):
        """实体球开关（关：全部退化为点精灵标记）"""
        self.show_solid = bool(enabled)
        self.update()

    def set_axes(self, enabled):
        """自转轴显示开关（极轴 + 赤道环 + 旋转子午线）"""
        self.show_axes = bool(enabled)
        self.update()

    # ---------- GL 生命周期 ----------
    def initializeGL(self):
        f = glfuncs
        f.glEnable(f.GL_DEPTH_TEST)
        f.glEnable(f.GL_MULTISAMPLE)
        f.glEnable(f.GL_PROGRAM_POINT_SIZE)

        self._prog_point = QOpenGLShaderProgram(self)
        self._prog_point.addShaderFromSourceCode(QOpenGLShader.Vertex, VS_POINT)
        self._prog_point.addShaderFromSourceCode(QOpenGLShader.Fragment, FS_POINT)
        self._prog_point.bindAttributeLocation("a_pos", 0)
        self._prog_point.bindAttributeLocation("a_color", 1)
        self._prog_point.bindAttributeLocation("a_size", 2)
        self._prog_point.link()

        self._prog_line = QOpenGLShaderProgram(self)
        self._prog_line.addShaderFromSourceCode(QOpenGLShader.Vertex, VS_LINE)
        self._prog_line.addShaderFromSourceCode(QOpenGLShader.Fragment, FS_LINE)
        self._prog_line.bindAttributeLocation("a_pos", 0)
        self._prog_line.bindAttributeLocation("a_color", 1)
        self._prog_line.link()

        self._prog_belt = QOpenGLShaderProgram(self)
        self._prog_belt.addShaderFromSourceCode(QOpenGLShader.Vertex, VS_BELT)
        self._prog_belt.addShaderFromSourceCode(QOpenGLShader.Fragment, FS_BELT)
        self._prog_belt.bindAttributeLocation("a_elem", 0)
        self._prog_belt.bindAttributeLocation("a_ang", 1)
        self._prog_belt.bindAttributeLocation("a_color", 2)
        self._prog_belt.bindAttributeLocation("a_size", 3)
        self._prog_belt.link()

        self._prog_sphere = QOpenGLShaderProgram(self)
        self._prog_sphere.addShaderFromSourceCode(QOpenGLShader.Vertex, VS_SPHERE)
        self._prog_sphere.addShaderFromSourceCode(QOpenGLShader.Fragment, FS_SPHERE)
        self._prog_sphere.bindAttributeLocation("a_pos", 0)
        self._prog_sphere.bindAttributeLocation("a_normal", 1)
        self._prog_sphere.bindAttributeLocation("a_color", 2)
        self._prog_sphere.bindAttributeLocation("a_light", 3)
        self._prog_sphere.bindAttributeLocation("a_emis", 4)
        self._prog_sphere.bindAttributeLocation("a_tex", 5)
        self._prog_sphere.bindAttributeLocation("a_axis", 6)
        self._prog_sphere.bindAttributeLocation("a_rot", 7)
        self._prog_sphere.link()
        self._sphere_dirs = make_unit_sphere()
        self._build_ring_templates()
        self._build_axis_basis()
        self._axis_phi = np.linspace(0.0, 2.0 * math.pi, AXIS_SEG, endpoint=False)

        self._prog_ring = QOpenGLShaderProgram(self)
        self._prog_ring.addShaderFromSourceCode(QOpenGLShader.Vertex, VS_RING)
        self._prog_ring.addShaderFromSourceCode(QOpenGLShader.Fragment, FS_RING)
        self._prog_ring.bindAttributeLocation("a_pos", 0)
        self._prog_ring.bindAttributeLocation("a_color", 1)
        self._prog_ring.bindAttributeLocation("a_alpha", 2)
        self._prog_ring.link()

        # 星云着色器
        self._prog_nebula = QOpenGLShaderProgram(self)
        self._prog_nebula.addShaderFromSourceCode(QOpenGLShader.Vertex, VS_NEBULA)
        self._prog_nebula.addShaderFromSourceCode(QOpenGLShader.Fragment, FS_NEBULA)
        self._prog_nebula.bindAttributeLocation("a_pos", 0)
        self._prog_nebula.link()
        # 全屏四边形 VBO（两个三角形，6 顶点，2 分量）
        _quad = np.array([
            [-1.0, -1.0], [ 1.0, -1.0], [-1.0,  1.0],
            [-1.0,  1.0], [ 1.0, -1.0], [ 1.0,  1.0],
        ], dtype=np.float32)
        self._vbo_nebula.create()
        self._vbo_nebula.bind()
        self._vbo_nebula.allocate(_quad.tobytes(), _quad.nbytes)
        self._vbo_nebula.release()

        _cf = self.context().format()
        print("[GL] profile=%d ver=%d.%d  point_linked=%s  line_linked=%s" % (
            _cf.profile(), _cf.majorVersion(), _cf.minorVersion(),
            self._prog_point.isLinked(), self._prog_line.isLinked()))

        self._vao.create()
        self._ibo.create()
        self._vbo_point.create()
        self._vbo_line.create()
        self._vbo_grid.create()
        self._vbo_star.create()
        self._vbo_trail.create()
        self._vbo_belt.create()
        self._vbo_sphere.create()
        self._vbo_ring.create()
        self._rebuild_orbits()
        self._upload_stars()
        self._upload_belt()

        # ---- GL 能力判定：必须是桌面 OpenGL 3.3+，且五个着色器程序全部链接成功 ----
        # 若设备只提供 ANGLE(GLES) / 软件 1.1 或着色器编译失败，GL 画面会全黑，
        # 此处显式标记，交给 paintGL 画一段可读说明，避免用户看到「空白界面」。
        _failed = [n for n, p in (("点", self._prog_point), ("线", self._prog_line),
                                  ("小行星", self._prog_belt), ("实体球", self._prog_sphere),
                                  ("行星环", self._prog_ring), ("星云", self._prog_nebula))
                   if not p.isLinked()]
        _ver_ok = (_cf.majorVersion() > 3 or
                   (_cf.majorVersion() == 3 and _cf.minorVersion() >= 3))
        if _failed or not _ver_ok:
            self._gl_ok = False
            _prof = "Core" if _cf.profile() == QSurfaceFormat.CoreProfile else "兼容/ES"
            self._gl_msg = (
                f"当前设备未提供可用的 OpenGL 3.3 渲染环境\n"
                f"（实际得到 {_cf.majorVersion()}.{_cf.minorVersion()} {_prof}"
                + (f"，着色器链接失败：{'、'.join(_failed)}" if _failed else "") + "）。\n\n"
                "三维视图无法绘制。请改用「2D 平面视图」，\n"
                "或更新显卡驱动 / 在独立显卡上运行后重试。")
            print("[GL] 不可用：ver=%d.%d profile=%d 失败程序=%s"
                  % (_cf.majorVersion(), _cf.minorVersion(), _cf.profile(), _failed))
        else:
            self._gl_ok = True
            self._gl_msg = ""

    def _upload_orbits(self):
        self._vbo_line.bind()
        _b = self._orbit_data.tobytes()
        self._vbo_line.allocate(len(_b))
        self._vbo_line.write(0, _b, len(_b))
        self._vbo_line.release()
        self._ibo.bind()
        _ib = self._orbit_index.tobytes()
        self._ibo.allocate(len(_ib))
        if len(_ib):
            self._ibo.write(0, _ib, len(_ib))
        self._ibo.release()

    def _upload_belt(self):
        """生成并上传主带小行星轨道根数点云（一次性，位置由 GPU 求解）"""
        from data.asteroid_belt import generate_belt
        data = generate_belt()
        self._belt_max = len(data)
        _b = data.tobytes()
        self._vbo_belt.bind()
        self._vbo_belt.allocate(len(_b))
        self._vbo_belt.write(0, _b, len(_b))
        self._vbo_belt.release()

    def _upload_stars(self):
        """背景恒星：优先用稠密 Hipparcos 星场（真实三维位置），否则回退内置亮星。

        稠密星场由 data.loader.load_hipparcos 提供 (N,7)：x,y,z(AU)+r,g,b+size(px)，
        坐标为 J2000 黄道系真实位置；内置亮星表仅有单位方向，则按固定天球半径展开。
        """
        data, max_dist = self._load_galaxy_field()
        if data is not None and len(data):
            self._star_data = data
            self._star_max_dist = max_dist
        elif self.stars:
            rows = []
            for name, pos_unit, size, color in self.stars:
                p = np.asarray(pos_unit, dtype=np.float64) * STAR_SPHERE_RADIUS
                rows.append(np.concatenate([p, color, [size]]))
            self._star_data = np.vstack(rows).astype(np.float32)
            self._star_max_dist = STAR_SPHERE_RADIUS
        else:
            self._star_data = np.zeros((0, 7), dtype=np.float32)
            self._star_max_dist = 0.0
        self._n_star = len(self._star_data)
        if self._prog_point is not None:
            self._vbo_star.bind()
            _b = self._star_data.tobytes()
            self._vbo_star.allocate(len(_b))
            self._vbo_star.write(0, _b, len(_b))
            self._vbo_star.release()

    @staticmethod
    def _load_galaxy_field():
        """读取稠密背景星场（Hipparcos）；不可用时返回 (None, 0.0)。"""
        try:
            from data.loader import load_hipparcos
            return load_hipparcos()
        except Exception:
            return None, 0.0

    def resizeGL(self, w, h):
        # Gizmo 始终贴视口右上角（跟随视口而非主窗口，需求 2.1）
        self._view_gizmo.reposition()

    # ---------- 每帧 ----------
    def _tick(self):
        now = _time.perf_counter()
        # dt 上限放宽到 0.25s：按需渲染空闲档最低约 15fps（dt≈0.067s），
        # 若沿用旧的 0.05s 上限会把仿真时间推进压成 0.75 倍速（天体运动变慢）。
        # 0.25s 仍足以挡住卡顿/断点造成的异常大跳。
        dt = min(0.25, now - self._last_tick)
        self._last_tick = now
        self.clock.update(dt)
        # 飞行模式持续移动（Shift 加速 ×5 / Ctrl 减速 ×0.2，按当前修饰键状态）
        if self.camera.fly_mode:
            from PyQt5.QtGui import QGuiApplication
            mods = QGuiApplication.queryKeyboardModifiers()
            mult = 5.0 if (mods & Qt.ShiftModifier) else (
                0.2 if (mods & Qt.ControlModifier) else 1.0)
            if "w" in self._keys:
                self.camera.fly_move(1, "x", mult)
            if "s" in self._keys:
                self.camera.fly_move(-1, "x", mult)
            if "a" in self._keys:
                self.camera.fly_move(-1, "y", mult)
            if "d" in self._keys:
                self.camera.fly_move(1, "y", mult)
            if "q" in self._keys:
                self.camera.fly_move(-1, "z", mult)
            if "e" in self._keys:
                self.camera.fly_move(1, "z", mult)
        self.camera.update(dt)
        # Gizmo 姿态同步：姿态变化才局部重绘自身（不触发主场景重绘）
        self._view_gizmo.sync_pose(self.camera)
        self._apply_follow()
        self._record_trail()
        self._fps_frames += 1
        if now - self._fps_t0 >= 0.5:
            self._fps = self._fps_frames / (now - self._fps_t0)
            self._fps_frames = 0
            self._fps_t0 = now
        self._adapt_planet_count(now)
        self._update_cadence(now)
        self.update()

    # ---------- 按需渲染（帧率调节） ----------
    def _mark_active(self, seconds: float = 3.0):
        """标记「正在交互/关注远处天体」，在给定时间内保持满帧渲染。

        鼠标拖拽/滚轮/键盘、选中天体、锁定跟随都会触发；空闲超过该时间后
        自动回落到低帧率，减少重绘次数以省算力。"""
        if self.on_demand:
            self._active_until = max(self._active_until, _time.perf_counter() + seconds)

    def _update_cadence(self, now: float):
        """根据「是否活跃」动态调整定时器间隔（满帧 / 空闲低帧）。

        降帧只改变重绘频率，仿真时间仍按真实 dt 推进，天体运动速度不变。
        fps_limit 为全局上限（0 = 无限制），优先于按需渲染档位。"""
        if not self.on_demand:
            fps = self.render_fps_active
        else:
            busy = (now < self._active_until
                    or self.camera.fly_mode
                    or self.camera._anim_active
                    or self.camera.view_anim_active
                    or self._dragging
                    or self.follow_body is not None)
            fps = self.render_fps_active if busy else self.render_fps_idle
        if self.fps_limit > 0:
            fps = min(fps, self.fps_limit)
        interval = max(1, int(round(1000.0 / max(1, fps))))
        if interval != self._timer.interval():
            self._timer.setInterval(interval)

    def set_on_demand(self, enabled: bool):
        """开关「按需渲染」；关闭即恢复持续满帧。"""
        self.on_demand = bool(enabled)
        if self.on_demand:
            self._mark_active(3.0)
        else:
            self._timer.setInterval(max(1, int(round(1000.0 / self.render_fps_active))))

    def set_fps_limit(self, fps: int):
        """设置帧率上限（0 = 无限制），即时生效。"""
        self.fps_limit = max(0, int(fps))
        self._update_cadence(_time.perf_counter())

    def invalidate_far(self):
        """使远处天体位置缓存失效（时间跳转后强制下一帧重算，避免残留旧位置）"""
        self._far_pos = None
        self._far_tick = 0

    # ---------- 锁定跟随 ----------
    def _apply_follow(self):
        """每帧把相机焦点锁定到被跟随天体的当前位置。

        飞入动画期间改写动画终点（目标持续移动也能平滑追上）；
        动画结束后直接写焦点。飞行模式下不跟随。"""
        b = self.follow_body
        if b is None or self.camera.fly_mode:
            return
        pos = np.asarray(b.position_at_jd(self.clock.jd), dtype=np.float64)
        if self.camera._anim_active:
            self.camera._anim_focus_to = pos
        else:
            self.camera.focus = pos

    def set_follow(self, enabled, body=None):
        """开启/关闭锁定跟随；开启时优先用 body，其次当前聚焦/选中天体"""
        target = body if enabled else None
        if enabled and target is None:
            target = self.focus_body or next(
                (x for x in self.bodies if x.name == self.selected_name), None)
        if target is self.follow_body:
            if enabled and target is None:
                self.followChanged.emit(False)   # 无聚焦天体，无法跟随 → 复位开关
            return
        self.follow_body = target
        self.followChanged.emit(target is not None)

    def _release_follow(self):
        if self.follow_body is not None:
            self.follow_body = None
            self.followChanged.emit(False)

    def paintGL(self):
        if not self._gl_ok:
            # GL 不可用：不提交任何 GL 绘制，改用 QPainter 画出可读说明，
            # 避免用户只看到一片黑（误以为"界面没跳转/卡死"）
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0x1d, 0x1d, 0x1d))
            p.setPen(QColor(0xe8, 0x7d, 0x0d))
            ft = p.font()
            ft.setPointSize(15)
            ft.setBold(True)
            p.setFont(ft)
            p.drawText(self.rect().adjusted(50, 0, -50, 0),
                       Qt.AlignCenter | Qt.TextWordWrap, self._gl_msg)
            p.end()
            return
        f = glfuncs
        self._vao.bind()
        f.glClearColor(0.02, 0.02, 0.04, 1.0)
        f.glClear(f.GL_COLOR_BUFFER_BIT | f.GL_DEPTH_BUFFER_BIT)
        f.glEnable(f.GL_BLEND)
        f.glBlendFunc(f.GL_SRC_ALPHA, f.GL_ONE_MINUS_SRC_ALPHA)

        self._compute_matrices()
        # Gizmo 姿态同步（双保险：_tick 已同步一次；外部触发的 repaint
        # ——如 resize/叠加刷新——也能拿到最新姿态，allclose 内部去重）
        self._view_gizmo.sync_pose(self.camera)
        self._update_body_positions(f)

        if self.show_nebula:
            self._draw_nebula(f)
        if self.show_stars:
            self._draw_stars(f)
        if self.show_grid:
            self._draw_grid(f)
        if self.show_orbits:
            self._draw_orbits(f)
            self._draw_moon_orbits(f)
            self._draw_sat_orbits(f)
        self._draw_belt(f)
        self._draw_trails(f)
        self._draw_shatter(f)
        self._draw_pn_shell(f)
        self._draw_roche_limits(f)
        self._draw_compare_link(f)
        self._draw_measure_link(f)
        self._draw_spheres(f)
        self._draw_rings(f)
        self._draw_rotation_axes(f)
        self._draw_bodies(f)

        self._vao.release()

        # QPainter 叠加层（标签 + HUD）
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._draw_labels(painter)
        self._draw_hud(painter)
        painter.end()

    def _compute_matrices(self):
        w = max(1, self.width())
        h = max(1, self.height())
        self._eye = self.camera.eye_position()
        dist = self.camera.distance if not self.camera.fly_mode else max(
            self.camera.distance, 1e-6)
        near = max(dist * 1e-4, 1e-10)
        far = max(dist * 2e3, 1e7)
        proj = perspective_matrix(FOV_DEG, w / h, near, far)
        origin = np.zeros(3)
        up = np.array([0.0, 0.0, 1.0])
        if self.camera.fly_mode:
            fwd = self.camera.forward_dir()
            view = look_at_matrix(self._eye, self._eye + fwd, up)
            view_rel = look_at_matrix(origin, fwd, up)
        else:
            view = look_at_matrix(self._eye, self.camera.focus, up)
            view_rel = look_at_matrix(origin, self.camera.focus - self._eye, up)
        self._proj, self._view = proj, view
        self._mvp = proj @ view               # 绝对世界坐标 → 裁剪空间
        self._mvp_rel = proj @ view_rel       # 眼点相对坐标 → 裁剪空间（无平移）
        # 背景恒星专用投影：Hipparcos 真实位置可达数十万 AU，远超主场景远裁剪面
        # （far≈视距×2e3），沿用主投影会被整体裁掉。这里单独给一个覆盖最远恒星
        # 的远裁剪面，深度关闭、最先绘制，仅作背景天幕，不影响主场景深度精度。
        if self._star_max_dist > 0.0:
            star_far = self._star_max_dist * 1.25
            star_near = max(star_far * 1e-6, 1e-3)
            proj_star = perspective_matrix(FOV_DEG, w / h, star_near, star_far)
            self._mvp_star = proj_star @ view
        else:
            self._mvp_star = self._mvp

    def _marker_floor(self, r_km) -> float:
        """远距标记点的最小直径（像素）。

        可视化比例：按真实半径做幂律缩放（指数 MARKER_EXP=0.5），使木星、
        地球、水星等**相对大小肉眼可辨**，又不至于让小天体小到看不见。
        真实比例：统一 2px 点（真实尺度下天体本就近乎不可见）。
        """
        if self.real_scale:
            return 2.0
        r = max(float(r_km) if r_km else MARKER_REF_KM, 1.0)
        px = MARKER_REF_PX * (r / MARKER_REF_KM) ** MARKER_EXP
        return max(MARKER_MIN_PX, min(px, MARKER_MAX_PX))

    # ---------- 太阳物理演化 ----------
    def _update_sun_evolution(self, jd: float):
        """每帧更新太阳演化状态：半径/光度/温度/质量 + 吞噬判定 + 轨道外移联动

        吞噬判定（机制一）：太阳光球半径 ≥ 天体日心距 → 吞噬（隐藏本体 + 闪光 + 事件）。
        天体位置由 loader.position_at_jd 按质量损失外移（机制二），与膨胀速率竞争。
        本帧使用上一帧位置缓存，误差一帧（演化时间尺度下可忽略）。
        """
        jd_prev = self._evo_last_jd
        jd_jump = (jd_prev is None or abs(jd - jd_prev) > 365.0)
        self._evo_last_jd = jd
        age = age_from_jd(jd)
        st = sun_state(age)
        self._sun_state_cache = st
        self._evo_active = age > SUN_NOW_AGE_GYR + 0.05
        # —— 吞噬的时间一致性 ——
        # 吞噬是时间轴上的事件（记录发生时刻 jd0）：当前时间早于 jd0 →
        # 天体尚未被吞（跳回过去则恢复显示）；晚于 jd0 → 永久消失——
        # 即使太阳已收缩成白矮星也不复活（物质已并入恒星/抛入行星状星云）。
        # （旧实现按「距离 > 光球半径」复活，白矮星期光球极小导致全部错误复活）
        if self._engulfed:
            revived = [i for i, jd0 in self._engulfed.items()
                       if jd < jd0 - 0.5]
            if revived:
                for i in revived:
                    del self._engulfed[i]
                self._engulf_dirty = True
        # 系外宿主恒星演化（含其行星的吞噬判定；内部限频 + 主序恢复）
        self._update_stellar_evolution(jd)
        if not self._evo_active:
            # 跳回现在/过去：被撕裂天体一并恢复（演示性质，无时刻记录）
            if self._shatter_hidden and self.clock.speed < 0:
                self._shatter_hidden.clear()
            if self._engulf_dirty:
                self._engulf_dirty = False
                self._rebuild_orbits()
                self._emit_engulf_changed()
            return
        sun_r_au = st.radius_au
        # 前进跳转（亿年轴节点）：区间 [上一帧, 本帧] 内光球最大半径——
        # 直接跳到白矮星期会越过 RGB tip 时刻，曾入光球的行星仍应被吞。
        # 倒退跳转不启用（回到吞噬时刻之前 = 天体尚在，由 revived 逻辑恢复）。
        r_judge = sun_r_au
        if jd_jump and jd_prev is not None and jd > jd_prev + 0.5:
            r_judge = max(sun_r_au,
                          max_radius_au_between(age_from_jd(jd_prev),
                                                age_from_jd(jd)))
        if (self._body_pos is not None and r_judge > SOLAR_RADIUS_AU * 1.5
                and self._near_idx is not None):
            # 时间跳转（亿年轴节点/手动拖拽）：上一帧位置缓存对应跳转前的时刻
            # （主序轨道，未含质量损失外移），直接判定会把贴边掠过的天体误吞
            # （地球主序 1.0 AU vs 外移后 1.21 AU）。先按当前 jd 重算再判定。
            if jd_jump:
                self._refresh_near_positions(jd)
            idxs = np.asarray(self._near_idx, dtype=np.int64)
            d = np.linalg.norm(self._body_pos[idxs], axis=1)
            for i in idxs[d < r_judge * 0.98]:
                if i in self._engulfed or i in self._shatter_hidden:
                    continue
                b = self.bodies[i]
                if b.body_type == "star":
                    continue
                self._engulfed[i] = jd
                # 卫星随母行星一起坠入光球（贴边掠过时卫星可能差一点点
                # 距离，母行星消失后卫星不应孤悬轨道）
                for j in self._near_idx:
                    m = self.bodies[j]
                    if (m.body_type in ("moon", "satellite")
                            and j not in self._engulfed
                            and getattr(m.parent, "name", None) == b.name):
                        self._engulfed[j] = jd
                self._engulf_flash = _time.perf_counter()
                self._log_evolution_event(f"「{b.name}」被膨胀的太阳吞噬（{st.phase}）")
                self._engulf_dirty = True
                # 跟随/选中指向被吞天体时立即解除（避免跟随幽灵位置）
                if self.follow_body is not None \
                        and getattr(self.follow_body, "name", "") == b.name:
                    self._release_follow()
        if self._shatter_hidden and self.clock.speed < 0:
            self._shatter_hidden.clear()   # 倒放时恢复被撕裂天体本体
        if self._engulf_dirty:
            self._engulf_dirty = False
            self._rebuild_orbits()          # 吞噬的天体不再画轨道线
            self._emit_engulf_changed()
        # 轨道外移因子变化 → 限频重建轨道线（贴合外移后的行星位置）。
        # 存太阳质量而非单一因子：地球（escape k=1.2）与一般行星（k=1.0）
        # 外移倍数不同，_rebuild_orbits 按天体名逐个计算。
        scale = orbit_expansion(st.mass_solar) if st.mass_solar < 1.0 else 1.0
        now = _time.perf_counter()
        if abs(scale - self._orbit_scale_applied) > 0.01:
            if now - self._last_orbit_rebuild > 0.5:
                self._orbit_scale_applied = scale
                self._sun_mass_applied = (st.mass_solar
                                          if st.mass_solar < 1.0 else 1.0)
                self._last_orbit_rebuild = now
                self._rebuild_orbits()

    def _refresh_near_positions(self, jd: float):
        """时间跳转后按当前时刻重算近距天体位置（含轨道外移，供吞噬判定）"""
        if self._near_idx is None or not self.bodies:
            return
        pos = (self._body_pos.copy() if self._body_pos is not None
               else np.zeros((len(self.bodies), 3), dtype=np.float64))
        for i in self._near_idx:
            pos[i] = self.bodies[i].position_at_jd(jd)
        self._body_pos = pos

    def _log_evolution_event(self, text: str):
        self.evolution_events.append((_time.perf_counter(),
                                      age_from_jd(self.clock.jd), text))
        if len(self.evolution_events) > 400:
            del self.evolution_events[:200]

    def _emit_engulf_changed(self):
        """吞噬状态变化 → 通知外部（左侧树同步隐藏/恢复）"""
        names = [self.bodies[i].name for i in self._engulfed]
        if names != self._vanished_emitted:
            self._vanished_emitted = list(names)
            self.engulfChanged.emit(list(names))

    def _update_stellar_evolution(self, jd: float):
        """系外宿主恒星演化：半径/颜色/光度随仿真时间变化 + 吞噬其行星。

        时间推进对全部恒星一致（Δ = age_from_jd(jd) − 太阳当前年龄），
        各自出生时间不同由观测年龄 st_age 区分——快进数十亿年后大质量
        宿主星先变红巨星，其行星落入膨胀光球即被吞噬（与太阳吞噬同一
        `_engulfed` 字典 / engulfChanged 信号 / 左侧树同步通道）。
        演化模型为演示级标度关系（core/star_evolution.py）。
        限频 0.5 s 且仅时间推进时重算；跳回主序恢复原值。
        """
        if self._star_evo_idx is None or not len(self._star_evo_idx):
            return
        now = _time.perf_counter()
        if (self._star_evo_last_jd is not None
                and abs(jd - self._star_evo_last_jd) < 1.0
                and now - self._star_evo_last_t < 0.5):
            return
        star_prev = self._star_evo_last_jd
        self._star_evo_last_jd = jd
        self._star_evo_last_t = now
        delta = age_from_jd(jd) - SUN_NOW_AGE_GYR
        if abs(delta) <= 0.05:
            # 主序（含跳回现在）：恢复原半径/颜色/亮度
            if self._star_evo_applied:
                self._radius_km[self._star_evo_idx] = \
                    self._radius_km0[self._star_evo_idx]
                self._colors_arr[self._star_evo_idx] = \
                    self._colors_arr0[self._star_evo_idx]
                self._star_evo_lum_idx = None
                self._star_evo_lum = None
                self._star_evo_applied = False
            return
        ages = self._star_evo_age0 + delta
        r_s, teff, lum, _mass, code = star_state_vec(
            self._star_evo_mass, ages, self._star_evo_r0, self._star_evo_teff0)
        # 仅对演化中的恒星应用（主序保持观测值/原调色）
        evolved = code != PHASE_MS
        idx_ev = self._star_evo_idx[evolved]
        if len(idx_ev):
            self._radius_km[idx_ev] = r_s[evolved] * R_SUN_KM
            cols = np.empty((int(evolved.sum()), 3), dtype=np.float64)
            for k, tk in enumerate(teff[evolved]):
                cols[k] = blackbody_rgb(float(tk))
            self._colors_arr[idx_ev] = cols
            self._star_evo_lum_idx = idx_ev
            self._star_evo_lum = lum[evolved]
        else:
            self._star_evo_lum_idx = None
            self._star_evo_lum = None
        self._star_evo_applied = True
        # —— 吞噬判定：行星-宿主距离 < 演化光球半径（与太阳判定同阈值） ——
        if self._body_pos is None or not len(self._exo_idx):
            return
        slot = self._exo_star_slot
        if not np.any(slot >= 0):
            return
        r_star_au = r_s * R_SUN_KM / AU_KM
        # 前进跳转：区间内光球最大半径（演化期相交 → AGB tip）+ 行星近点距
        # （轨道相位在区间内不确定，取最近可能距离）；直接跳到白矮星期
        # 也会越过红巨星阶段，曾入光球的行星仍应被吞。
        if (star_prev is not None and jd > star_prev + 0.5
                and abs(jd - star_prev) > 365.0):
            delta_prev = age_from_jd(star_prev) - SUN_NOW_AGE_GYR
            a_lo = self._star_evo_age0 + min(delta_prev, delta)
            a_hi = self._star_evo_age0 + max(delta_prev, delta)
            t_ms = 10.0 * self._star_evo_mass ** -2.5
            t_end = t_ms + rgb_duration_gyr(self._star_evo_mass) + 0.2
            inter = (a_hi >= t_ms) & (a_lo <= t_end)
            r_star_au = np.maximum(
                r_star_au,
                np.where(inter, 1.15 * 256.0
                         * self._star_evo_mass ** 0.2, 0.0)
                * R_SUN_KM / AU_KM)
            d = self._exo_a * (1.0 - self._exo_e)   # 近点距
        else:
            M = (2.0 * math.pi / np.maximum(self._exo_period, 1e-9)) \
                * (jd - J2000_JD)
            rel = exo_relative_positions_vec(self._exo_a, self._exo_e,
                                             self._exo_i, M)
            d = np.linalg.norm(rel, axis=1)
        safe = np.where(slot >= 0, slot, 0)
        hit = (slot >= 0) & (d < r_star_au[safe] * 0.98)
        newly = [int(self._exo_idx[k]) for k in np.nonzero(hit)[0]
                 if int(self._exo_idx[k]) not in self._engulfed]
        if not newly:
            return
        # 按宿主分组记录事件（批量吞噬时避免日志刷屏）
        by_host = {}
        for i in newly:
            b = self.bodies[i]
            self._engulfed[i] = jd
            by_host.setdefault(b.host, []).append(b.name)
        for host, names in by_host.items():
            shown = "、".join(names[:8]) + ("…" if len(names) > 8 else "")
            self._log_evolution_event(f"「{host}」演化膨胀吞噬行星：{shown}")
        self._engulf_dirty = True
        if (self.follow_body is not None
                and getattr(self.follow_body, "name", "") in
                {self.bodies[i].name for i in newly}):
            self._release_follow()

    def start_shatter_demo(self):
        """潮汐撕裂演示：选中天体沿轨道旋进（τ ∝ (R/d)^6 的指数近似），

        进入 primary 流体洛希极限后被撕成碎片链（参考苏梅克-列维 9 号碎裂形态）。
        演示性质：轨道衰减速率参数化，非逐项潮汐积分。
        """
        name = self.selected_name
        if not name or self._index_of is None:
            return False
        i = self._index_of.get(name)
        if i is None:
            return False
        b = self.bodies[i]
        if b.body_type in ("star", "host_star", "blackhole", "planet_exo",
                           "nearby_star", "interstellar"):
            return False
        self._demo_shatter = {"name": name, "factor": 1.0}
        self._log_evolution_event(f"潮汐撕裂演示开始：「{b.name}」轨道旋进中")
        self._mark_active(30.0)
        return True

    def _update_demo_shatter(self, pos):
        """演示轨道旋进：相对 primary 的位置向心收缩，直到进入流体洛希极限"""
        demo = getattr(self, "_demo_shatter", None)
        if not demo or self._body_pos is None:
            return
        i = self._index_of.get(demo["name"])
        if i is None:
            self._demo_shatter = None
            return
        b = self.bodies[i]
        if b.body_type in ("moon", "satellite") and b.parent is not None:
            p_i = self._index_of.get(b.parent.name)
            base = pos[p_i] if p_i is not None else np.zeros(3)
            r_p_km = b.parent.radius_km or 6371.0
            m_p_earth = b.parent.mass_earth or 1.0
        else:
            base = np.zeros(3)
            st = self._sun_state_cache
            if st is not None and self._evo_active:
                r_p_km = R_SUN_KM * st.radius_solar
                m_p_earth = M_SUN_PER_EARTH * st.mass_solar
            else:
                r_p_km = R_SUN_KM
                m_p_earth = M_SUN_PER_EARTH
        rel = self._body_pos[i] - base
        demo["factor"] *= 0.9985      # 轨道衰减（演示参数化）
        new_rel = rel * demo["factor"]
        rho_p = mean_density_gcm3(r_p_km, m_p_earth)
        rho_s = mean_density_gcm3(b.radius_km, b.mass_earth) if \
            (b.radius_km and b.mass_earth) else 3.0
        roche_au = roche_limit_fluid_km(r_p_km, rho_p, rho_s) / AU_KM
        if float(np.linalg.norm(new_rel)) <= roche_au:
            self._trigger_shatter(i, b, base)
            self._demo_shatter = None
        else:
            pos[i] = base + new_rel

    def _trigger_shatter(self, i, b, base):
        """潮汐撕裂：本体隐藏，沿轨道散布碎片链（径向抖动模拟解体）"""
        rng = np.random.default_rng(7)
        if b.body_type in ("moon", "satellite"):
            pts = (self._moon_orbits.get(b.name) or
                   self._sat_orbits.get(b.name) or ([np.zeros((0, 3))]))[0]
        else:
            rng_or = self._orbit_ranges.get(b.name)
            pts = (self._orbit_data[rng_or[0]:rng_or[0] + rng_or[1], :3]
                   if rng_or is not None else None)
        if pts is None or len(pts) < 8:
            self._engulfed[i] = self.clock.jd
            self._log_evolution_event(f"「{b.name}」被潮汐力瓦解")
            return
        n = 48
        sel = pts[::max(1, len(pts) // n)][:n]
        spread = 0.06 + 0.02 * rng.random((len(sel), 1))
        radial = sel / np.maximum(np.linalg.norm(sel, axis=1,
                                                 keepdims=True), 1e-9)
        frag = sel + radial * spread * np.linalg.norm(sel, axis=1,
                                                      keepdims=True)
        self._shattered[b.name] = (frag + base[None, :],
                                   _time.perf_counter())
        self._shatter_hidden.add(i)
        self._log_evolution_event(
            f"「{b.name}」进入流体洛希极限，被潮汐力撕裂成 {len(sel)} 块碎片链")

    def _draw_shatter(self, f):
        """碎片链绘制（撕裂后 8 秒渐隐；红橙色，模拟炽热碎片）"""
        if not self._shattered:
            return
        prog = self._prog_line
        if prog is None:
            return
        now = _time.perf_counter()
        f.glDisable(f.GL_DEPTH_TEST)
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        stride = 6 * 4
        self._vbo_trail.bind()
        for name in list(self._shattered.keys()):
            pts, t0 = self._shattered[name]
            dt = now - t0
            if dt > 8.0:
                del self._shattered[name]
                continue
            alpha = 0.85 * (1.0 - dt / 8.0)
            arr = np.asarray(pts) - self._eye[None, :]
            col = np.tile(np.array([1.0, 0.45, 0.25]), (len(arr), 1))
            data = np.hstack([arr, col]).astype(np.float32)
            _b = data.tobytes()
            self._vbo_trail.allocate(len(_b))
            self._vbo_trail.write(0, _b, len(_b))
            prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
            prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
            prog.enableAttributeArray(0)
            prog.enableAttributeArray(1)
            prog.setUniformValue("u_alpha", float(alpha))
            f.glDrawArrays(f.GL_LINE_STRIP, 0, len(data))
        self._vbo_trail.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    def _draw_pn_shell(self, f):
        """行星状星云壳（可视化近似）：AGB 抛射后 0.3 Gyr 内膨胀的半透明壳

        以三个正交圆环近似球壳（OIII 青绿色）；膨胀速度为数十 km/s 量级的
        可视化缩放，非严格辐射流体力学。
        """
        st = self._sun_state_cache
        if st is None or not (12.40 <= st.age_gyr <= 12.70):
            return
        prog = self._prog_line
        if prog is None:
            return
        w = (st.age_gyr - 12.40) / 0.30
        r_au = 1.0 + w * 45.0
        alpha = 0.5 * (1.0 - w)
        if alpha <= 0.01:
            return
        ang = np.linspace(0.0, 2.0 * math.pi, 96, endpoint=False)
        circ = np.stack([np.cos(ang), np.sin(ang)], axis=1)
        # 三个正交平面（xy / yz / xz）的大圆近似球壳；u、v 必须同为 3 维，
        # 否则 (96,2)+(96,3) 广播失败（白矮星跳转崩溃根因）
        _U = np.array([1.0, 0.0, 0.0])
        _V = np.array([0.0, 1.0, 0.0])
        _Z = np.array([0.0, 0.0, 1.0])
        rings = []
        for u, v in ((_U, _V), (_V, _Z), (_U, _Z)):
            rings.append(circ[:, 0:1] * u[None, :] * r_au
                         + circ[:, 1:2] * v[None, :] * r_au)
        pts = np.vstack(rings) - self._eye[None, :]
        col = np.tile(np.array([0.35, 0.9, 0.8]), (len(pts), 1))
        data = np.hstack([pts, col]).astype(np.float32)
        _b = data.tobytes()
        f.glDisable(f.GL_DEPTH_TEST)
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", float(alpha))
        stride = 6 * 4
        self._vbo_trail.bind()
        self._vbo_trail.allocate(len(_b))
        self._vbo_trail.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        for k in range(3):
            f.glDrawArrays(f.GL_LINE_LOOP, k * 96, 96)
        self._vbo_trail.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    def _draw_roche_limits(self, f):
        """洛希极限圈（选中天体相对其 primary）：刚体（橙）与流体（红）

        行星 → 以太阳为 primary（演化时半径/质量实时联动，红巨星阶段圈外扩）；
        卫星 → 以母行星为 primary。
        公式：刚体 d = 1.26·R·(ρ_p/ρ_s)^{1/3}，流体 d = 2.44·R·(ρ_p/ρ_s)^{1/3}。
        """
        if not self.show_roche or self._body_pos is None:
            return
        name = self.selected_name
        if not name or self._index_of is None:
            return
        i = self._index_of.get(name)
        if i is None:
            return
        b = self.bodies[i]
        st = self._sun_state_cache
        if b.body_type in ("planet_solar", "dwarf", "etno"):
            center = np.zeros(3)
            if st is not None and self._evo_active:
                r_p_km = R_SUN_KM * st.radius_solar
                m_p_earth = M_SUN_PER_EARTH * st.mass_solar
            else:
                r_p_km = R_SUN_KM
                m_p_earth = M_SUN_PER_EARTH
        elif b.body_type in ("moon", "satellite") and b.parent is not None:
            p_i = self._index_of.get(b.parent.name)
            if p_i is None:
                return
            center = self._body_pos[p_i]
            r_p_km = b.parent.radius_km or 6371.0
            m_p_earth = b.parent.mass_earth or 1.0
        else:
            return
        rho_p = mean_density_gcm3(r_p_km, m_p_earth)
        rho_s = (mean_density_gcm3(b.radius_km, b.mass_earth)
                 if (b.radius_km and b.mass_earth) else 3.0)
        d_rigid = roche_limit_km(r_p_km, rho_p, rho_s) / AU_KM
        d_fluid = roche_limit_fluid_km(r_p_km, rho_p, rho_s) / AU_KM
        ang = np.linspace(0.0, 2.0 * math.pi, 128, endpoint=False)
        prog = self._prog_line
        if prog is None:
            return
        f.glDisable(f.GL_DEPTH_TEST)
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        stride = 6 * 4
        self._vbo_trail.bind()
        for d_au, col in ((d_rigid, (1.0, 0.72, 0.2)),
                          (d_fluid, (1.0, 0.35, 0.30))):
            pts = np.stack([center[0] + d_au * np.cos(ang),
                            center[1] + d_au * np.sin(ang),
                            np.full(len(ang), center[2])], axis=1)
            rel = pts - self._eye[None, :]
            colors = np.tile(np.array(col), (len(rel), 1))
            data = np.hstack([rel, colors]).astype(np.float32)
            _b = data.tobytes()
            self._vbo_trail.allocate(len(_b))
            self._vbo_trail.write(0, _b, len(_b))
            prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
            prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
            prog.enableAttributeArray(0)
            prog.enableAttributeArray(1)
            prog.setUniformValue("u_alpha", 0.75)
            f.glDrawArrays(f.GL_LINE_LOOP, 0, len(data))
        self._vbo_trail.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    def _update_body_positions(self, f):
        """CPU double 精度计算天体位置 → 相对相机坐标 float32（浮点原点）

        近距天体（视直径 ≥ 标记点下限）改用**实体球**按真实半径绘制；
        远距天体退化为点精灵标记，标记点直径按真实半径幂律缩放，
        因此远看也能分辨天体相对大小。二者切换阈值与标记点下限一致，
        过渡无跳变。

        性能：系外行星可达数千颗，位置与尺寸计算全部向量化（numpy 批量），
        太阳系天体/卫星/恒星数量少，仍逐个解析计算。
        """
        n = len(self.bodies)
        jd = self.clock.jd
        self._update_sun_evolution(jd)
        if self._near_idx is None:
            # 数据尚未 load_bodies（启动/模式切换时序）：本帧无物可画。
            # _body_pos 保持 None，各绘制函数按各自守卫跳过。
            return
        pos = np.empty((n, 3), dtype=np.float64)

        # 近处天体（太阳系 + 卫星）：每帧解析计算（数量少，开销可忽略）
        for i in self._near_idx:
            pos[i] = self.bodies[i].position_at_jd(jd)

        # 远处天体（系外行星 + 宿主恒星 + 黑洞）：距离为秒差距~千秒差距量级，
        # 屏幕上位移远小于 1px，无需逐帧重算。按需渲染开启且处于空闲时，
        # 每 _far_stride 帧重算一次，其余帧复用缓存，省下逐帧的向量化/解析开销；
        # 交互或聚焦（满帧）时仍逐帧重算，保证点击/跟随时轨迹实时。
        now = _time.perf_counter()
        busy = (not self.on_demand) or (now < self._active_until) or \
            self.camera.fly_mode or self._dragging or self.follow_body is not None
        if busy or self._far_pos is None or (self._far_tick % self._far_stride == 0):
            if len(self._exo_idx):
                pos[self._exo_idx] = self._exo_positions(jd)
            for i in self._far_small_idx:
                pos[i] = self.bodies[i].position_at_jd(jd)
            if len(self._far_idx):
                self._far_pos = pos[self._far_idx].copy()
        elif len(self._far_idx):
            pos[self._far_idx] = self._far_pos
        self._far_tick += 1
        self._update_demo_shatter(pos)
        self._body_pos = pos
        rel = pos - self._eye[None, :]

        h = max(1, self.height())
        px_per_rad = h / math.radians(FOV_DEG)

        # —— 尺寸（向量化）——
        dist = np.linalg.norm(rel, axis=1)
        np.maximum(dist, 1e-12, out=dist)
        has_r = ~np.isnan(self._radius_km)
        r_au = np.where(has_r, self._radius_km / AU_KM, 0.0)
        # 太阳演化：半径按当前阶段缩放（红巨星膨胀 / 白矮星收缩）
        sun_i = self._index_of.get("太阳")
        st = self._sun_state_cache
        if self._evo_active and sun_i is not None and st is not None:
            r_au[sun_i] *= st.radius_solar
        diams = np.where(has_r, r_au / dist * px_per_rad * 2.0, 0.0)
        floors = self._marker_floor_vec(self._radius_km)
        # 系外行星（秒差距级距离）：远看一律细小光点，不按半径放大成圆球；
        # 拉近到行星系（视直径超过该点）时仍按真实半径切换为实体球。
        if len(self._exo_idx):
            floors[self._exo_idx] = EXO_MARKER_PX

        # 宿主恒星：远看也是细小光点（与系外行星同级），靠近时按真实半径成球
        # 亮度远低于太阳，避免"满屏炸弹"效果
        host_star_idx = np.nonzero(self._is_host_star)[0]
        if len(host_star_idx):
            floors[host_star_idx] = EXO_MARKER_PX

        # 黑洞：完全不可见（点大小=0，实体球=False），仅参与引力网格下陷
        bh_idx = np.nonzero(self._is_blackhole)[0]
        if len(bh_idx):
            floors[bh_idx] = 0.0

        if self.show_solid:
            sphere_flag = has_r & (diams >= floors) & ~self._is_blackhole
            sizes = np.where(sphere_flag, 0.0, floors)     # 画球体的不给点尺寸
        else:
            sphere_flag = np.zeros(n, dtype=bool)
            sizes = np.where(has_r,
                             np.clip(diams, floors, 96.0), floors)
        rvis = np.where(has_r, r_au, 0.0)

        # 卫星开关（关闭时隐藏点标记与实体球）
        if not self.show_moons and len(self._moon_idx):
            sizes[self._moon_idx] = 0.0
            sphere_flag[self._moon_idx] = False
            rvis[self._moon_idx] = 0.0

        # 人造卫星开关：关闭、或尚未拉近到地球（地球视直径不足）时隐藏
        if len(self._sat_idx):
            earth_i = self._index_of.get("地球")
            earth_near = (earth_i is not None and diams[earth_i] >= NEAR_DIAM_PX)
            if not (self.show_satellites and earth_near):
                sizes[self._sat_idx] = 0.0
                sphere_flag[self._sat_idx] = False
                rvis[self._sat_idx] = 0.0

        # 演化隐藏：被吞噬 / 被潮汐撕裂的天体不再绘制本体
        if self._evo_active:
            hidden = list(self._engulfed) + list(self._shatter_hidden)
            if hidden:
                hidden = np.asarray(hidden, dtype=np.int64)
                sizes[hidden] = 0.0
                sphere_flag[hidden] = False
                rvis[hidden] = 0.0

        # —— 光源方向（球面光照用；系外行星以宿主星为光源，其余以太阳/原点）——
        src = np.where(self._exo_host_has[:, None], self._exo_host, 0.0)
        light_src = np.zeros((n, 3))
        if len(self._exo_idx):
            light_src[self._exo_idx] = src
        L = light_src - pos
        ln = np.linalg.norm(L, axis=1)
        lights = np.where(ln[:, None] > 1e-15, L / np.maximum(ln, 1e-15)[:, None],
                          np.array([1.0, 0.0, 0.0]))

        # —— 自发光强度（分级亮度，避免宿主恒星"满屏炸弹"）——
        # 太阳：1.0（全亮）；演化时随光度调节（红巨星更亮、白矮星变暗）
        # 宿主恒星：0.18（微亮，刚能看出是恒星但不刺眼）
        # 其余：0.0（漫反射光照）
        emis = np.where(self._is_solar_star, 1.0,
                 np.where(self._is_host_star, 0.18, 0.0))
        # 宿主恒星演化：自发光随演化光度调节（红巨星/AGB 显著增亮，白矮星变暗）
        if self._star_evo_lum_idx is not None and len(self._star_evo_lum_idx):
            emis[self._star_evo_lum_idx] = np.clip(
                self._star_evo_lum ** 0.12, 0.18, 3.0)
        if self._evo_active and sun_i is not None and st is not None:
            emis[sun_i] = float(np.clip(st.luminosity_solar ** 0.12, 0.30, 3.0))
            # 吞噬闪光：事件后 2 秒内附加渐隐脉冲
            dt_flash = _time.perf_counter() - self._engulf_flash
            if 0.0 <= dt_flash < 2.0:
                emis[sun_i] += 1.6 * (1.0 - dt_flash / 2.0)

        colors = self._colors_arr
        # 太阳演化：颜色随黑体温度变化（红巨星偏红、白矮星偏蓝）
        if self._evo_active and sun_i is not None and st is not None:
            colors = colors.copy()
            colors[sun_i] = blackbody_rgb(st.teff_k)
        self._sphere_idx = np.nonzero(sphere_flag)[0]
        self._body_rvis = rvis
        self._body_diam = diams
        self._body_floor = floors
        self._body_colors = colors
        self._body_lights = lights
        self._body_emis = emis

        # 自转相位：随仿真时间推进（周期带符号，负值即逆行），取模避免大数精度损失
        t = jd - J2000_JD
        with np.errstate(divide="ignore", invalid="ignore"):
            phase = np.where(np.abs(self._rot_period) > 1e-9,
                             2.0 * math.pi * t / self._rot_period, 0.0)
        self._body_rot = np.mod(phase, 2.0 * math.pi)

        # 视锥剔除（相机后方）
        fwd = self.camera.forward_dir()
        vis = rel @ fwd > -0.01
        data = np.zeros((n, 7), dtype=np.float32)
        data[:, :3] = rel
        data[:, 3:6] = colors
        data[:, 6] = np.where(vis, sizes, 0.0)
        self._n_point = n
        self._vbo_point.bind()
        _b = data.tobytes()
        self._vbo_point.allocate(len(_b))
        self._vbo_point.write(0, _b, len(_b))
        self._vbo_point.release()

    def _bind_attribs(self, prog, vbo, stride):
        vbo.bind()
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)          # GL_FLOAT
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)

    def _draw_nebula(self, f):
        """星云背景：全屏四边形 + 程序化 fBm 体积云（零 CPU 每帧开销）"""
        if self._prog_nebula is None or not self._prog_nebula.isLinked():
            return
        f.glDisable(f.GL_DEPTH_TEST)
        f.glEnable(f.GL_BLEND)
        f.glBlendFunc(f.GL_SRC_ALPHA, f.GL_ONE)       # 加性混合，更像自发光的云雾
        prog = self._prog_nebula
        prog.bind()
        inv_proj = np.linalg.inv(self._proj)
        inv_view = np.linalg.inv(self._view)
        prog.setUniformValue("u_inv_proj", self._qmat(inv_proj))
        prog.setUniformValue("u_inv_view", self._qmat(inv_view))
        prog.setUniformValue("u_time", float(self.clock.days_since_j2000()))
        self._vbo_nebula.bind()
        prog.setAttributeBuffer(0, 0x1406, 0, 2, 8)   # GL_FLOAT, 2分量, stride=8
        prog.enableAttributeArray(0)
        f.glDrawArrays(f.GL_TRIANGLES, 0, 6)
        prog.disableAttributeArray(0)
        self._vbo_nebula.release()
        prog.release()
        f.glBlendFunc(f.GL_SRC_ALPHA, f.GL_ONE_MINUS_SRC_ALPHA)
        f.glEnable(f.GL_DEPTH_TEST)

    def _draw_stars(self, f):
        if self._n_star == 0:
            return
        f.glDisable(f.GL_DEPTH_TEST)
        prog = self._prog_point
        prog.bind()
        mvp = self._mvp_star if self._mvp_star is not None else self._mvp
        prog.setUniformValue("u_mvp", self._qmat(mvp))
        prog.setUniformValue("u_alpha", 0.9)
        stride = 7 * 4
        self._vbo_star.bind()
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.setAttributeBuffer(2, 0x1406, 24, 1, stride)
        for i in range(3):
            prog.enableAttributeArray(i)
        f.glDrawArrays(f.GL_POINTS, 0, self._n_star)
        prog.disableAttributeArray(2)
        self._vbo_star.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    def _draw_orbits(self, f):
        n_pts = len(self._orbit_data)
        if n_pts == 0:
            return
        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp))
        prog.setUniformValue("u_alpha", 0.55)
        stride = 6 * 4
        self._vbo_line.bind()
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        # Core Profile 下索引缓冲绑定属于 VAO 状态；上传时已 release，
        # 绘制前必须重新绑定，否则 glDrawElements 取不到索引、画不出轨道线
        self._ibo.bind()
        f.glDrawElements(f.GL_LINES, len(self._orbit_index), f.GL_UNSIGNED_INT,
                         None)
        self._ibo.release()
        self._vbo_line.release()
        prog.release()

    def _draw_belt(self, f):
        """主带小行星：轨道根数送进顶点着色器，位置每帧在 GPU 上按开普勒方程求解"""
        if not self.show_belt or self._belt_max == 0 or self._prog_belt is None:
            return
        count = min(int(self.belt_count), self._belt_max)
        if count <= 0:
            return
        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_belt
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_eye", QVector3D(float(self._eye[0]),
                                                float(self._eye[1]),
                                                float(self._eye[2])))
        prog.setUniformValue("u_t", float(self.clock.days_since_j2000()))
        prog.setUniformValue("u_alpha", 0.85)
        stride = 10 * 4
        self._vbo_belt.bind()
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)     # a, e, i
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)    # Ω, ω, M0
        prog.setAttributeBuffer(2, 0x1406, 24, 3, stride)    # 颜色
        prog.setAttributeBuffer(3, 0x1406, 36, 1, stride)    # 点大小
        for i in range(4):
            prog.enableAttributeArray(i)
        f.glDrawArrays(f.GL_POINTS, 0, count)
        prog.disableAttributeArray(3)
        self._vbo_belt.release()
        prog.release()

    def _record_trail(self):
        """历史尾迹记录（选中/对比天体）。

        低倍速：约每 0.15s 真实时间采样一点，尾迹随时间自然生长；
        高倍速：0.15s 内天体已转过数圈，逐帧采样会退化为穿心的乱直线，
        改为按预采样轨道几何直接生成 0.75 圈平滑弧（_trail_geo_arc）。
        """
        watch = set(self.compare_names or [])
        if self.selected_name:
            watch.add(self.selected_name)
        if not watch or self._body_pos is None:
            return
        speed = abs(self.clock.speed)
        name_to_idx = {b.name: i for i, b in enumerate(self.bodies)}
        now = _time.perf_counter()
        for name in list(watch):
            b = next((x for x in self.bodies if x.name == name), None)
            if b is None:
                continue
            period = b.period or 0.0   # period property：含开普勒第三定律 fallback（行星无 period_days 字段）
            if period > 0 and speed * 0.15 > period / 600.0:
                self._trail_geo_arc(name, b, name_to_idx)
                continue
            if now - self._trail_last < 0.15:
                continue
            self._trail_last = now
            if name not in self._trails:
                self._trails[name] = []
            lst = self._trails[name]
            lst.append(self._body_pos[name_to_idx[name]].copy())
            cap = 20000 if self.trail_mode == "persist" else 600   # 保留上限（persist 保留完整历史）
            if len(lst) > cap:
                del lst[:len(lst) - cap]

    def _trail_geo_arc(self, name, b, name_to_idx):
        """高倍速尾迹：沿预采样轨道几何回溯 0.75 圈，生成平滑弧线。

        点序为「旧 → 新」（末点贴当前天体位置），与逐帧采样尾迹方向一致；
        倒放时取反方向；逆行轨道（倾角 > 90°）采样序与运动序相反，需翻转。
        """
        center = np.zeros(3)
        if b.body_type == "moon" and name in self._moon_orbits:
            pts = self._moon_orbits[name][0]
            p_idx = name_to_idx.get(getattr(b.parent, "name", ""), None)
            if p_idx is None:
                return
            center = self._body_pos[p_idx]
        elif b.body_type == "satellite" and name in self._sat_orbits:
            pts = self._sat_orbits[name][0]
            p_idx = name_to_idx.get(getattr(b.parent, "name", ""), None)
            if p_idx is None:
                return
            center = self._body_pos[p_idx]
        else:
            rng = self._orbit_ranges.get(name)
            if rng is None:
                return
            off, ln = rng
            pts = self._orbit_data[off:off + ln, :3].astype(np.float64)
        cur = self._body_pos[name_to_idx[name]] - center
        k = int(np.argmin(((pts - cur) ** 2).sum(axis=1)))
        n_arc = min(96, max(len(pts) // 2, 8))
        sgn = -1 if self.clock.direction > 0 else 1
        incl = getattr(b, "incl_deg", None)
        if incl is None:
            el = getattr(b, "elements", None)
            incl = getattr(el, "i", 0.0) if el is not None else 0.0
        if (incl or 0.0) > 90.0:
            sgn = -sgn
        back = np.arange(n_arc - 1, -1, -1)
        idxs = (k + sgn * back) % len(pts)
        self._trails[name] = list(pts[idxs] + center)

    def _draw_trails(self, f):
        """尾迹绘制（真实三维曲线，随视角正确变换）

        trail_mode == "clear"   ：只保留最近一段并向后渐隐（分块降 alpha，随时间自动消失）
        trail_mode == "persist" ：保留完整历史轨迹，整段恒定 alpha
        """
        if not self.show_trails or not self._trails:
            return
        names = {b.name for b in self.bodies}
        prog = self._prog_line
        f.glDisable(f.GL_DEPTH_TEST)
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        stride = 6 * 4
        self._vbo_trail.bind()
        for name, pts in self._trails.items():
            if len(pts) < 2 or name not in names:
                continue
            b = next((x for x in self.bodies if x.name == name), None)
            if b is None:
                continue
            arr = np.asarray(pts)
            rel = arr - self._eye[None, :]
            col = np.tile(np.array(b.color, dtype=np.float64), (len(arr), 1))
            data = np.hstack([rel, col]).astype(np.float32)
            _b = data.tobytes()
            self._vbo_trail.allocate(len(_b))
            self._vbo_trail.write(0, _b, len(_b))
            prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
            prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
            prog.enableAttributeArray(0)
            prog.enableAttributeArray(1)
            n = len(data)
            if self.trail_mode == "persist" or n <= 9:
                prog.setUniformValue("u_alpha", 0.8)
                f.glDrawArrays(f.GL_LINE_STRIP, 0, n)
            else:
                # 分块绘制：越旧的一段 alpha 越低，形成「不断消除」的渐隐尾迹
                k_chunks = 8
                step = (n - 1) / k_chunks
                for k in range(k_chunks):
                    s = int(round(k * step))
                    e = min(n, int(round((k + 1) * step)) + 1)
                    if e - s < 2:
                        continue
                    prog.setUniformValue("u_alpha", 0.9 * (k + 1) / k_chunks)
                    f.glDrawArrays(f.GL_LINE_STRIP, s, e - s)
        self._vbo_trail.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    def _draw_compare_link(self, f):
        """对比连线：选中的两颗对比天体之间连线（相对运动主视口直观化）"""
        if len(self.compare_names) < 2 or self._body_pos is None:
            return
        idxs = []
        names = list(map(lambda x: x.name, self.bodies))
        for nm in self.compare_names:
            if nm in names:
                idxs.append(names.index(nm))
        if len(idxs) < 2:
            return
        rel_a = self._body_pos[idxs[0]] - self._eye
        rel_b = self._body_pos[idxs[1]] - self._eye
        data = np.array([
            [*rel_a, 0.91, 0.49, 0.05],
            [*rel_b, 0.91, 0.49, 0.05],
        ], dtype=np.float32)
        f.glDisable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 0.6)
        stride = 6 * 4
        self._vbo_trail.bind()
        _b = data.tobytes()
        self._vbo_trail.allocate(len(_b))
        self._vbo_trail.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        f.glDrawArrays(f.GL_LINES, 0, 2)
        self._vbo_trail.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    def _draw_measure_link(self, f):
        """测距连线：A/B 两天体之间连线（青蓝色，区别于对比连线的橙色）"""
        if len(self.measure_names) < 2 or self._body_pos is None:
            return
        i = self._index_of.get(self.measure_names[0])
        j = self._index_of.get(self.measure_names[1])
        if i is None or j is None:
            return
        rel_a = self._body_pos[i] - self._eye
        rel_b = self._body_pos[j] - self._eye
        data = np.array([
            [*rel_a, 0.30, 0.72, 0.95],
            [*rel_b, 0.30, 0.72, 0.95],
        ], dtype=np.float32)
        f.glDisable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 0.75)
        stride = 6 * 4
        self._vbo_trail.bind()
        _b = data.tobytes()
        self._vbo_trail.allocate(len(_b))
        self._vbo_trail.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        f.glDrawArrays(f.GL_LINES, 0, 2)
        self._vbo_trail.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    def set_measure_pair(self, name_a, name_b):
        """设置测距 A/B（None 或空表示清除连线）"""
        self.measure_names = [n for n in (name_a, name_b) if n]
        self.update()

    def _draw_grid(self, f):
        """黄道面网格（多层 LOD：主网格 + 随缩放淡入的细分网格）。

        主格距取「1/2/5×10^k」中不大于 dist/6 的最大整齐值，使任意缩放级别
        视野内始终保持约 6~12 格；这修掉了固定十倍档在档位边界（如视距 5、
        格距 10）整片网格"消失"的问题。细分网格为主格的 1/5，仅当放得足够
        大（视野内格数不过密）时按密度淡入，形成"大网格里套小网格"的层次。
        """
        if self.gravity_mode:
            self._draw_grid_gravity(f)
            return
        dist = max(self.camera.distance, 1e-9)
        half = 12                                   # 主网格半宽（格数）
        major = self._nice_step(dist / 6.0)
        minor = major / 5.0

        lines = []
        cols = []
        # 中性灰、低对比度：比纯黑背景略亮以便在黑暗宇宙中可见，但亮度克制，
        # 不会盖住行星/轨道等主体。主网格稍亮，细分网格更淡并随缩放淡入淡出。
        MAJOR_SHADE = 0.42
        MINOR_SHADE = 0.24
        # 细分网格：随视野内格数淡入淡出，过密（>55 格）时完全隐去
        cells_minor = dist / minor
        fade = min(1.0, max(0.0, (55.0 - cells_minor) / 20.0))
        if fade > 0.01:
            self._emit_grid(lines, cols, minor, half * 5, MINOR_SHADE * fade)
        self._emit_grid(lines, cols, major, half, MAJOR_SHADE)

        arr = np.array(lines, dtype=np.float64) - self._eye[None, :]
        color = np.array(cols, dtype=np.float64)
        data = np.hstack([arr, color]).astype(np.float32)
        self._n_grid = len(lines)
        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 0.38)
        stride = 6 * 4
        self._vbo_grid.bind()
        _b = data.tobytes()
        self._vbo_grid.allocate(len(_b))
        self._vbo_grid.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        f.glDrawArrays(f.GL_LINES, 0, self._n_grid)
        self._vbo_grid.release()
        prog.release()

    @staticmethod
    def _nice_step(x):
        """不大于 x 的最大「1/2/5 × 10^k」整齐步长（用于网格格距）。"""
        e = math.floor(math.log10(max(x, 1e-300)))
        b = 10.0 ** e
        for m in (5.0, 2.0, 1.0):
            if b * m <= x:
                return b * m
        return b

    @staticmethod
    def _emit_grid(lines, cols, step, half, shade):
        """向顶点/颜色列表追加一层网格（half 为单侧格数）。"""
        span = half * step
        for k in range(-half, half + 1):
            v = k * step
            for x0, y0, x1, y1 in ((-span, v, span, v), (v, -span, v, span)):
                lines.append([x0, y0, 0.0])
                lines.append([x1, y1, 0.0])
                cols.append((shade, shade, shade))
                cols.append((shade, shade, shade))

    def _gravity_depth(self, xs, ys, eps):
        """网格顶点的引力势 Σ M/r（供引力网格下陷使用）。

        返回 (X, Y, depth)：X/Y 为网格坐标，depth 为各顶点的势（越大越深）。
        gravity_names 为 None 时计入全部有质量天体，否则只计入其中列出的天体。
        """
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        depth = np.zeros_like(X)
        pos = self._body_pos
        mass = self._grav_mass
        if pos is None or mass is None:
            return X, Y, depth
        names = self.gravity_names
        if names is None:
            sel = mass > 0
        else:
            sel = np.array([b.name in names for b in self.bodies]) & (mass > 0)
        bx, by, bz, bm = pos[sel, 0], pos[sel, 1], pos[sel, 2], mass[sel]
        for k in range(len(bm)):
            dx = X - bx[k]
            dy = Y - by[k]
            depth += bm[k] / np.sqrt(dx * dx + dy * dy + bz[k] * bz[k] + eps * eps)
        return X, Y, depth

    def _draw_grid_gravity(self, f):
        """引力网格：黄道面网格按各天体 M/r 引力势下陷（时空弯曲示意）。

        相对深度严格遵循真实 M/r（质量越大、距离越近，凹陷越深），
        整体深度按当前网格格距自动归一化，保证任意缩放级别都清晰可见；
        gravity_names 可限定只由选中天体产生凹陷（此时该天体的凹陷自动放大）。

        网格中心跟随相机焦点：聚焦到黑洞/宿主恒星时，网格也会移到该天体处，
        便于观察其引力井。
        """
        dist = max(self.camera.distance, 1e-9)
        step = 10 ** round(math.log10(dist))
        half = 12
        cells = max(8, int(self.gravity_cells))
        # 网格中心跟随相机焦点（便于观察任意天体的引力井）
        cx = float(self.camera.focus[0])
        cy = float(self.camera.focus[1])
        xs = np.linspace(-half * step, half * step, cells + 1) + cx
        ys = np.linspace(-half * step, half * step, cells + 1) + cy

        # 软化长度：既避免天体正中心出现无穷深尖刺，又要保证井壁跨越多格、
        # 在相邻顶点间平滑过渡（软化长度不足时井壁只落在一两格内，会呈折棱/锯齿）
        cell = 2.0 * half * step / cells
        eps = max(0.25 * step, self.gravity_soften * cell)
        X, Y, depth = self._gravity_depth(xs, ys, eps)
        dmax = float(depth.max()) if depth.size else 0.0

        if dmax > 0:
            t = depth / dmax
            zz = -t * (self.gravity_depth_cells * step * self.gravity_scale)
        else:
            t = np.zeros_like(depth)
            zz = np.zeros_like(depth)

        # 颜色随深度：平地（蓝灰）→ 深井（橙）
        base = np.array([0.20, 0.23, 0.30])
        deep = np.array([0.98, 0.58, 0.16])
        vcol = base[None, None, :] + (deep - base)[None, None, :] * t[:, :, None]

        A = np.stack([X, Y, zz], axis=-1)                          # (nx, ny, 3)
        row_seg = np.stack([A[:-1, :, :], A[1:, :, :]], axis=2)    # 沿 x 的线段
        row_col = np.stack([vcol[:-1, :, :], vcol[1:, :, :]], axis=2)
        col_seg = np.stack([A[:, :-1, :], A[:, 1:, :]], axis=2)    # 沿 y 的线段
        col_col = np.stack([vcol[:, :-1, :], vcol[:, 1:, :]], axis=2)
        verts = np.concatenate([row_seg.reshape(-1, 3),
                                col_seg.reshape(-1, 3)], axis=0)
        colors = np.concatenate([row_col.reshape(-1, 3),
                                 col_col.reshape(-1, 3)], axis=0)

        arr = verts - self._eye[None, :]
        data = np.hstack([arr, colors]).astype(np.float32)
        self._n_grid = len(data)
        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 0.9)
        stride = 6 * 4
        self._vbo_grid.bind()
        _b = data.tobytes()
        self._vbo_grid.allocate(len(_b))
        self._vbo_grid.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        f.glDrawArrays(f.GL_LINES, 0, self._n_grid)
        self._vbo_grid.release()
        prog.release()

    def _draw_spheres(self, f):
        """天体实体球：单位球模板按「中心 + 半径 × 方向」逐帧展开，一次 draw call。

        使用**真实半径**，靠近时球体自然放大直至填满视野（贴脸）；
        光照按球面法线做漫反射，恒星为自发光。"""
        idx = self._sphere_idx
        if not self.show_solid or idx is None or len(idx) == 0 or self._sphere_dirs is None:
            return
        dirs = self._sphere_dirs                       # (S,3)
        B = len(idx)
        S = len(dirs)
        centers = self._body_pos[idx] - self._eye[None, :]   # (B,3) 眼点相对
        radii = self._body_rvis[idx][:, None, None]          # (B,1,1)
        colors = self._body_colors[idx]
        lights = self._body_lights[idx]
        emis = self._body_emis[idx]
        tex = self._body_tex[idx]
        poles = self._body_pole[idx]
        rots = self._body_rot[idx]

        pos = centers[:, None, :] + radii * dirs[None, :, :]
        nrm = np.broadcast_to(dirs[None, :, :], (B, S, 3))
        col = np.broadcast_to(colors[:, None, :], (B, S, 3))
        lit = np.broadcast_to(lights[:, None, :], (B, S, 3))
        em = np.broadcast_to(emis[:, None, None], (B, S, 1))
        tx = np.broadcast_to(tex[:, None, None], (B, S, 1))
        ax = np.broadcast_to(poles[:, None, :], (B, S, 3))
        ro = np.broadcast_to(rots[:, None, None], (B, S, 1))
        data = np.concatenate([pos, nrm, col, lit, em, tx, ax, ro], axis=2).reshape(-1, 18)
        data = data.astype(np.float32)

        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_sphere
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 1.0)
        stride = 18 * 4
        self._vbo_sphere.bind()
        _b = data.tobytes()
        self._vbo_sphere.allocate(len(_b))
        self._vbo_sphere.write(0, _b, len(_b))
        for loc, off, ncomp in ((0, 0, 3), (1, 12, 3), (2, 24, 3), (3, 36, 3),
                                (4, 48, 1), (5, 52, 1), (6, 56, 3), (7, 68, 1)):
            prog.setAttributeBuffer(loc, 0x1406, off, ncomp, stride)
            prog.enableAttributeArray(loc)
        f.glDrawArrays(f.GL_TRIANGLES, 0, len(data))
        for loc in range(8):
            prog.disableAttributeArray(loc)
        self._vbo_sphere.release()
        prog.release()

    def _near_planets(self) -> dict:
        """本帧视直径足够大（可分辨行星系）的天体索引 → 视直径/阈值 比值。

        用于行星环与卫星轨道的淡入：比值 1.0 时刚开始出现，1.6 时完全显现。"""
        d = self._body_diam
        if d is None or len(d) == 0:
            return {}
        idx = np.nonzero(d >= NEAR_DIAM_PX)[0]
        return {int(i): float(d[i]) / NEAR_DIAM_PX for i in idx}

    def _draw_moon_orbits(self, f):
        """卫星轨道：相对母行星的椭圆（母行星位置每帧变化，动态上传）。

        仅在母行星视直径足够大（拉近到行星系）时绘制，避免远景杂乱。"""
        if not (self.show_orbits and self.show_moons and self._moon_orbits):
            return
        if self._body_pos is None:
            return
        near = self._near_planets()
        chunks = []
        for name, (pts, col) in self._moon_orbits.items():
            i = self._index_of.get(name)
            if i is None:
                continue
            b = self.bodies[i]
            pi = self._index_of.get(b.parent_name)
            if pi is None or pi not in near:
                continue
            if i in self._engulfed or i in self._shatter_hidden \
                    or pi in self._engulfed or pi in self._shatter_hidden:
                continue   # 卫星或母行星已被吞噬/撕裂
            base = (self._body_pos[pi] - self._eye)[None, :]
            # 闭合折线 → 显式线段对（GL_LINES 每两个顶点成一段，避免折线被打断成虚线）
            closed = np.vstack([pts, pts[:1]])
            pairs = np.stack([closed[:-1], closed[1:]], axis=1).reshape(-1, 3)
            chunks.append(np.hstack([pairs + base, np.tile(col, (len(pairs), 1))]))
        if not chunks:
            return
        data = np.vstack(chunks).astype(np.float32)
        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 0.5)
        stride = 6 * 4
        self._vbo_trail.bind()
        _b = data.tobytes()
        self._vbo_trail.allocate(len(_b))
        self._vbo_trail.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        f.glDrawArrays(f.GL_LINES, 0, len(data))
        self._vbo_trail.release()
        prog.release()

    def _draw_sat_orbits(self, f):
        """人造卫星轨道：相对地球的开普勒椭圆（含真实倾角与升交点经度）。

        仅当开关开启且已拉近到地球（地球视直径足够大）时绘制，
        避免远景杂乱与额外算力开销。"""
        if not (self.show_orbits and self.show_satellites and self._sat_orbits):
            return
        if self._body_pos is None:
            return
        near = self._near_planets()
        earth_i = self._index_of.get("地球")
        if earth_i is None or earth_i not in near:
            return
        base = (self._body_pos[earth_i] - self._eye)[None, :]
        chunks = []
        for name, (pts, col) in self._sat_orbits.items():
            i = self._index_of.get(name)
            if i is None:
                continue
            closed = np.vstack([pts, pts[:1]])
            pairs = np.stack([closed[:-1], closed[1:]], axis=1).reshape(-1, 3)
            chunks.append(np.hstack([pairs + base, np.tile(col, (len(pairs), 1))]))
        if not chunks:
            return
        data = np.vstack(chunks).astype(np.float32)
        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 0.45)
        stride = 6 * 4
        self._vbo_trail.bind()
        _b = data.tobytes()
        self._vbo_trail.allocate(len(_b))
        self._vbo_trail.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        f.glDrawArrays(f.GL_LINES, 0, len(data))
        self._vbo_trail.release()
        prog.release()

    def _draw_rings(self, f):
        """行星环：以母行星真实极轴定向的平面圆环，透明度随视直径淡入。

        半透明环关闭深度写入（glDepthMask(0)）避免自遮挡条纹；
        深度测试仍开启，因此环被行星本体正确遮挡（前半可见、后半隐藏）。"""
        if not (self.show_rings and self.show_solid and self._ring_tpl):
            return
        if self._body_pos is None:
            return
        near = self._near_planets()
        chunks = []
        for name, (tpl, u, v, alpha0) in self._ring_tpl.items():
            i = self._index_of.get(name)
            if i is None or i not in near:
                continue
            fade = min(1.0, max(0.0, (near[i] - 1.0) / 0.6))
            if fade <= 0.0:
                continue
            R = float(self._body_rvis[i])
            if R <= 0.0:
                continue
            c = self._body_pos[i] - self._eye
            world = c[None, :] + R * (tpl[:, 0:1] * u[None, :] +
                                      tpl[:, 1:2] * v[None, :])
            a = tpl[:, 6:7] * (alpha0 * fade)
            chunks.append(np.hstack([world, tpl[:, 3:6], a]))
        if not chunks:
            return
        data = np.vstack(chunks).astype(np.float32)
        f.glEnable(f.GL_DEPTH_TEST)
        f.glDepthMask(0)
        prog = self._prog_ring
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 1.0)
        stride = 7 * 4
        self._vbo_ring.bind()
        _b = data.tobytes()
        self._vbo_ring.allocate(len(_b))
        self._vbo_ring.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.setAttributeBuffer(2, 0x1406, 24, 1, stride)
        for loc in range(3):
            prog.enableAttributeArray(loc)
        f.glDrawArrays(f.GL_TRIANGLES, 0, len(data))
        for loc in range(3):
            prog.disableAttributeArray(loc)
        self._vbo_ring.release()
        prog.release()
        f.glDepthMask(1)

    def _draw_rotation_axes(self, f):
        """自转轴可视化：极轴 + 赤道面圆环 + 随自转转动的子午线。

        极轴与赤道环反映真实转轴倾角（由 IAU 极轴定向），子午线按真实自转
        周期随时间转动（逆行自转反向）。仅在行星视直径足够大（拉近到行星系）
        时绘制；深度测试开启，球体背面一侧的子午线被球体正确遮挡。"""
        if not (self.show_axes and self.show_solid and self._axis_basis):
            return
        if self._body_pos is None or getattr(self, "_axis_phi", None) is None:
            return
        jd = self.clock.jd
        phi = self._axis_phi
        cosphi = np.cos(phi)[:, None]
        sinphi = np.sin(phi)[:, None]
        chunks = []
        col_axis = np.array(AXIS_COLOR)
        col_eq = np.array(EQ_COLOR)
        col_mer = np.array(MER_COLOR)
        for name, (n, e1, e2) in self._axis_basis.items():
            i = self._index_of.get(name)
            if i is None or self._body_diam[i] < NEAR_DIAM_PX:
                continue
            R = float(self._body_rvis[i])
            if R <= 0.0:
                continue
            th = self.bodies[i].spin_angle_at_jd(jd)
            c, s = math.cos(th), math.sin(th)
            e1r = c * e1 + s * e2              # 随自转转动的赤道面基
            e2r = -s * e1 + c * e2
            center = self._body_pos[i] - self._eye

            # 极轴（两端各 AXIS_LEN × R）
            axis = np.array([center - AXIS_LEN * R * n, center + AXIS_LEN * R * n])
            chunks.append(np.hstack([axis, np.tile(col_axis, (2, 1))]))

            # 赤道面圆环
            eq = cosphi * e1r[None, :] + sinphi * e2r[None, :]
            eqp = center[None, :] + (R * RING_R) * _loop_to_pairs(eq)
            chunks.append(np.hstack([eqp, np.tile(col_eq, (len(eqp), 1))]))

            # 两条子午线（含极轴的大圆，随自转转动）
            m1 = sinphi * e1r[None, :] + cosphi * n[None, :]
            m2 = sinphi * e2r[None, :] + cosphi * n[None, :]
            for m in (m1, m2):
                mp = center[None, :] + (R * RING_R) * _loop_to_pairs(m)
                chunks.append(np.hstack([mp, np.tile(col_mer, (len(mp), 1))]))
        if not chunks:
            return
        data = np.vstack(chunks).astype(np.float32)
        f.glEnable(f.GL_DEPTH_TEST)
        prog = self._prog_line
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 0.95)
        stride = 6 * 4
        self._vbo_ring.bind()
        _b = data.tobytes()
        self._vbo_ring.allocate(len(_b))
        self._vbo_ring.write(0, _b, len(_b))
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.enableAttributeArray(0)
        prog.enableAttributeArray(1)
        f.glDrawArrays(f.GL_LINES, 0, len(data))
        self._vbo_ring.release()
        prog.release()

    def _draw_bodies(self, f):
        if self._n_point == 0:
            return
        f.glDisable(f.GL_DEPTH_TEST)
        prog = self._prog_point
        prog.bind()
        prog.setUniformValue("u_mvp", self._qmat(self._mvp_rel))
        prog.setUniformValue("u_alpha", 1.0)
        stride = 7 * 4
        self._vbo_point.bind()
        prog.setAttributeBuffer(0, 0x1406, 0, 3, stride)
        prog.setAttributeBuffer(1, 0x1406, 12, 3, stride)
        prog.setAttributeBuffer(2, 0x1406, 24, 1, stride)
        for i in range(3):
            prog.enableAttributeArray(i)
        f.glDrawArrays(f.GL_POINTS, 0, self._n_point)
        prog.disableAttributeArray(2)
        self._vbo_point.release()
        prog.release()
        f.glEnable(f.GL_DEPTH_TEST)

    @staticmethod
    def _qmat(m: np.ndarray) -> QMatrix4x4:
        return QMatrix4x4(*[float(x) for x in m.ravel()])

    # ---------- 投影 / 拾取 ----------
    def project(self, world_pos: np.ndarray):
        """世界坐标 → (像素x, 像素y, 可见性)"""
        p = np.append(np.asarray(world_pos, dtype=np.float64), 1.0)
        clip = self._mvp @ p
        if clip[3] <= 1e-12:
            return None
        ndc = clip[:3] / clip[3]
        if abs(ndc[0]) > 1.2 or abs(ndc[1]) > 1.2:
            return None
        x = (ndc[0] * 0.5 + 0.5) * self.width()
        y = (1.0 - (ndc[1] * 0.5 + 0.5)) * self.height()
        return x, y

    def pick(self, x: int, y: int, radius_px: int = 24):
        """屏幕空间拾取最近天体"""
        if self._body_pos is None:
            return None
        best, best_d = None, radius_px
        for i, b in enumerate(self.bodies):
            if i in self._engulfed or i in self._shatter_hidden:
                continue
            pr = self.project(self._body_pos[i])
            if pr is None:
                continue
            d = math.hypot(pr[0] - x, pr[1] - y)
            if d < best_d:
                best, best_d = b, d
        return best

    # ---------- 叠加层 ----------
    def _draw_labels(self, painter: QPainter):
        """名称标注：默认仅太阳系恒星/行星/矮行星与卫星（数量少）。

        系外行星与宿主恒星上万颗，全部标注会铺满视口，仅在选中/加入对比时显示；
        黑洞不可见，仅选中时标名。只遍历近处天体索引（数十个），避免每帧
        扫描上万个远处天体做无用判断。
        """
        if not self.show_labels or self._body_pos is None:
            return
        near = self._near_planets()
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        extra = set(self.compare_names or [])
        if self.selected_name:
            extra.add(self.selected_name)
        for i in self._near_idx:
            b = self.bodies[i]
            if b.body_type == "moon":
                pi = self._index_of.get(b.parent_name)
                want = (b.name in extra or
                        (self.show_moons and pi is not None and pi in near))
            elif b.body_type in ("star", "planet_solar"):
                want = True
            else:
                want = b.name in extra
            if want:
                self._draw_one_label(painter, i, b)
        # 选中/对比的远处天体（任意类型，含宿主恒星、系外行星）
        for name in extra:
            i = self._index_of.get(name)
            if i is None:
                continue
            b = self.bodies[i]
            if b.body_type == "moon" or b.body_type in ("planet_solar", "dwarf", "etno", "star"):
                continue                       # 已在上面的近处循环处理
            if b.body_type == "blackhole" and b.name != self.selected_name:
                continue                       # 黑洞不可见，仅选中时标名
            self._draw_one_label(painter, i, b)

    def _draw_one_label(self, painter: QPainter, i: int, b):
        if i in self._engulfed or i in self._shatter_hidden:
            return   # 被吞噬/撕裂的天体不再标注
        pr = self.project(self._body_pos[i])
        if pr is None:
            return
        x, y = pr
        is_sel = b.name == self.selected_name
        if is_sel:
            painter.setPen(QColor(232, 125, 13))
            painter.drawEllipse(int(x - 9), int(y - 9), 18, 18)
        painter.setPen(QColor("#e87d0d") if is_sel else QColor.fromRgbF(*b.color))
        painter.drawText(int(x + 7), int(y - 6), b.name)

    def _draw_hud(self, painter: QPainter):
        """HUD：焦点 / 视距 / 尺度层级 / 比例提示 / FPS / 精度警告"""
        w, h = self.width(), self.height()
        painter.setFont(QFont("Consolas", 9))
        y = 16
        focus_name = self.focus_body.name if self.focus_body else "太阳系原点"
        if self.follow_body is not None:
            focus_name += "  [锁定跟随中]"
        lines = [
            f"焦点: {focus_name}",
            f"视距: {format_distance(self.camera.distance)}",
            f"当前视野: {scale_tier_name(self.camera.distance)}",
        ]
        if self.locked_name is not None:
            lines.append(f"已锁定: {self.locked_name}（F键解锁）")
        if self.real_scale:
            lines.append("比例: 真实比例（实体球按真实半径，靠近即为真实大小）")
        else:
            lines.append("比例: 可视化（远距以放大标记点显示，近距自动切换实体球）")
        if self.show_solid and len(self._sphere_idx):
            lines.append(f"实体球: {len(self._sphere_idx)} 个天体（真实半径）")
        if self.show_axes and self._axis_basis:
            lines.append("自转轴: 极轴 + 赤道环 + 子午线（随自转转动）")
        if self.camera.fly_mode:
            lines.append("飞行模式: WASD 移动 | QE 上下 | 中键转向 | Shift+~ 退出")
        # 星历适用范围警告
        year = self.clock.now_ymd()[0]
        if year < EPHEMERIS_VALID_YEARS[0] or year > EPHEMERIS_VALID_YEARS[1]:
            lines.append("警告: 已超出 JPL 近似星历适用范围（1800-2050），误差随时间累积")
        # 太阳演化状态
        st = self._sun_state_cache
        if self._evo_active and st is not None:
            lines.append(
                f"太阳: {st.phase}｜R={st.radius_solar:.4g} R☉ "
                f"L={st.luminosity_solar:.4g} L☉ T={st.teff_k:.0f} K "
                f"M={st.mass_solar:.3f} M☉")
        for line in lines:
            painter.setPen(QColor(224, 224, 224))
            painter.drawText(12, y, line)
            y += 16
        painter.setPen(QColor(160, 160, 160))
        n_planets = min(int(self.belt_count), self._belt_max) if (self.show_belt and self._belt_max) else 0
        _tier = render_settings.TIER_LABELS.get(self.perf_tier, self.perf_tier)
        _mode = "自动" if self.planet_auto else "手动"
        _num = f"天体 {n_planets:,}（{_tier}·{_mode}）"
        if self.on_demand:
            busy = _time.perf_counter() < self._active_until
            painter.drawText(w - 320, h - 12,
                             f"{_num}   {'满帧' if busy else '低帧'}   FPS {self._fps:.0f}")
        else:
            painter.drawText(w - 240, h - 12, f"{_num}   FPS {self._fps:.0f}")
        # 快捷键提示（小字浮层）
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.setPen(QColor(130, 130, 130))
        painter.drawText(12, h - 12,
                         "中键旋转 | Shift+中键平移 | 滚轮缩放 | 右键菜单 | F1 帮助")
        # 演化事件横幅：最近一条 8 秒渐隐（吞噬/撕裂/阶段转换）
        if self.evolution_events:
            t0, _age, text = self.evolution_events[-1]
            dt_ev = _time.perf_counter() - t0
            if 0.0 <= dt_ev < 8.0:
                alpha = 1.0 if dt_ev < 6.0 else (8.0 - dt_ev) / 2.0
                painter.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
                painter.setPen(QColor(255, 130, 100, int(230 * alpha)))
                painter.drawText(QRectF(0, h * 0.16, w, 44),
                                 Qt.AlignCenter | Qt.TextWordWrap, text)

    # ---------- 交互 ----------
    # ---------- 轴向视角（View Gizmo / Numpad 视图键共用） ----------
    # 软件世界系约定（J2000 黄道系，Z=黄道北极；az 自 +X 起量，el=0 黄道面）：
    #   +X → az=0（YZ 平面侧视）   -X → az=180
    #   +Y → az=90（XZ 平面侧视）  -Y → az=-90
    #   +Z → el=+89.9 俯视（az=None 保持当前值：俯视水平朝向无唯一解，
    #                    保持 az 动画最平滑、不水平甩动）
    #   -Z → el=-89.9 仰视（az=None 同上）
    # 与 Numpad 快捷键为同一套映射：1→+X、3→+Y、7→+Z（Ctrl+ 反向）。
    # 切换时保持：focus（观察目标/锁定跟随天体不变）、distance（缩放不变）、
    # 透视投影（AXIS_VIEW_ORTHO 预留「轴向视角用正交投影」开关，默认关闭）。
    _GIZMO_VIEWS = {
        "+x": (0.0, 0.0), "-x": (180.0, 0.0),
        "+y": (90.0, 0.0), "-y": (-90.0, 0.0),
        "+z": (None, 89.9), "-z": (None, -89.9),
    }

    def _gizmo_view(self, key: str):
        """Gizmo 端点点击 / 快捷键 → 平滑切轴向视角（300~500ms 缓动）"""
        if key not in self._GIZMO_VIEWS:
            return
        az, el = self._GIZMO_VIEWS[key]
        self.camera.view_to(az, el)
        self._mark_active(1.0)
        self.update()

    def set_gizmo_visible(self, shown: bool):
        """设置面板「显示 3D 视角导航轴」开关 → Gizmo 显隐（快捷键不受影响）"""
        self._view_gizmo.set_shown(shown)

    def mousePressEvent(self, ev):
        self._mark_active()
        self._last_pos = ev.pos()
        if ev.button() == Qt.MidButton:
            self._dragging = True
            self._drag_pan = bool(ev.modifiers() & Qt.ShiftModifier)
            if self.camera.fly_mode:
                self._start_fly_capture(ev)
        elif ev.button() == Qt.LeftButton:
            b = self.pick(ev.x(), ev.y())
            if b:
                if self.locked_name is not None and b.name != self.locked_name:
                    pass  # 锁定状态下点击其他天体不切换
                else:
                    self.selected_name = b.name
                    self.bodySelected.emit(b)
                    self.update()
        elif ev.button() == Qt.RightButton:
            self._show_context_menu(ev)

    def mouseMoveEvent(self, ev):
        if self.camera.fly_mode and self._fly_captured and self._last_pos is not None:
            delta = ev.pos() - self._center_pos
            self.camera.orbit(delta.x(), delta.y())
            from PyQt5.QtGui import QCursor
            QCursor.setPos(self.mapToGlobal(self._center_pos))
            return
        if not self._dragging or self._last_pos is None:
            return
        self._mark_active()
        delta = ev.pos() - self._last_pos
        self._last_pos = ev.pos()
        if self._drag_pan:
            self._release_follow()          # 平移视为放弃跟随
            self.camera.pan(delta.x(), delta.y())
        else:
            self.camera.orbit(delta.x(), delta.y())

    def mouseReleaseEvent(self, ev):
        self._dragging = False
        if self._fly_captured:
            self._end_fly_capture()

    def wheelEvent(self, ev):
        self._mark_active()
        delta = ev.angleDelta().y() / 120.0
        self.camera.zoom_step(-delta * 0.15)

    def _start_fly_capture(self, ev):
        """飞行模式鼠标捕获（相对移动控制朝向）"""
        try:
            from PyQt5.QtGui import QCursor
            self._center_pos = ev.pos()
            QCursor.setPos(self.mapToGlobal(self._center_pos))
            self._fly_captured = True
        except Exception:
            self._fly_captured = False

    def _end_fly_capture(self):
        self._fly_captured = False
        self._center_pos = None

    def keyPressEvent(self, ev):
        self._mark_active()
        k = ev.key()
        mods = ev.modifiers()
        text = ev.text().lower()
        if k in (Qt.Key_QuoteLeft, Qt.Key_AsciiTilde) and (mods & Qt.ShiftModifier):
            if self.camera.fly_mode:
                self.camera.exit_fly()
                self._end_fly_capture()
            else:
                self._release_follow()      # 飞行模式下不跟随
                self.camera.enter_fly()
            self.update()
            return
        if k == Qt.Key_Escape and self.camera.fly_mode:
            self.camera.exit_fly()
            self._end_fly_capture()
            self.update()
            return
        if self.camera.fly_mode:
            if text in ("w", "a", "s", "d", "q", "e"):
                self._keys.add(text)
            return
        # F 键：锁定/解锁当前选中天体
        if text == "f" or k == Qt.Key_F:
            self._toggle_lock()
            return
        # Blender 数字键盘视图（与 View Gizmo 同一套映射：1→+X、3→+Y、7→+Z，
        # Ctrl+ 反向；走 view_to 平滑动画，与 Gizmo 点击一致。4/6/8/2 保持连续旋转）
        key_map = {
            Qt.Key_1: None, Qt.Key_3: None, Qt.Key_7: None,
            Qt.Key_4: None, Qt.Key_6: None, Qt.Key_8: None, Qt.Key_2: None,
        }
        if mods & Qt.KeypadModifier or k in key_map:
            if k == Qt.Key_1:
                self.camera.view_to(180 if (mods & Qt.ControlModifier) else 0, 0)
            elif k == Qt.Key_3:
                self.camera.view_to(90 if not (mods & Qt.ControlModifier) else -90, 0)
            elif k == Qt.Key_7:
                # 俯视/仰视 az 保持当前值（原 set_view 固定 az=0，现与 Gizmo 统一：
                # 保持 az 动画最平滑；画面仍是 XY 平面俯视，仅屏幕朝向随当前方位）
                self.camera.view_to(None, 90 if not (mods & Qt.ControlModifier) else -90)
            elif k == Qt.Key_4:
                self.camera._d_az = 1.6
            elif k == Qt.Key_6:
                self.camera._d_az = -1.6
            elif k == Qt.Key_8:
                self.camera._d_el = 1.6
            elif k == Qt.Key_2:
                self.camera._d_el = -1.6
            elif k == Qt.Key_Plus:
                self.camera.zoom_step(-0.4)
            elif k == Qt.Key_Minus:
                self.camera.zoom_step(0.4)
            elif k == Qt.Key_Period:
                self._focus_selected()
            self.update()
            return
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        text = ev.text().lower()
        self._keys.discard(text)
        super().keyReleaseEvent(ev)

    def _focus_selected(self):
        b = next((x for x in self.bodies if x.name == self.selected_name), None)
        if b:
            self._focus_body(b)

    def _toggle_lock(self):
        """F键：锁定/解锁当前选中天体。锁定后点击其他天体不会切换选中。"""
        if self.locked_name is not None:
            self.locked_name = None
        elif self.selected_name is not None:
            self.locked_name = self.selected_name
        self.update()

    def _show_context_menu(self, ev):
        b = self.pick(ev.x(), ev.y())
        menu = QMenu(self)
        if b:
            self.selected_name = b.name
            self.bodySelected.emit(b)
            act_focus = QAction(f"聚焦到 {b.name}", menu)
            act_focus.triggered.connect(lambda: self._focus_body(b))
            menu.addAction(act_focus)
            act_cmp = QAction(f"{'移出对比' if b.name in self.compare_names else '加入对比'}（{b.name}）", menu)
            act_cmp.triggered.connect(lambda: self._toggle_compare(b))
            menu.addAction(act_cmp)
            act_ref = QAction(f"锁定跟随（{b.name}）", menu)
            act_ref.triggered.connect(lambda: self._lock_follow(b))
            menu.addAction(act_ref)
            if self.follow_body is not None:
                act_rel = QAction("解除锁定跟随", menu)
                act_rel.triggered.connect(self._release_follow)
                menu.addAction(act_rel)
            # 潮汐撕裂演示（行星/卫星；τ ∝ (R/d)^6 的演示参数化）
            if b.body_type in ("planet_solar", "dwarf", "etno", "moon",
                               "satellite"):
                act_sh = QAction(f"潮汐撕裂演示（{b.name}）", menu)
                act_sh.triggered.connect(lambda: self.start_shatter_demo())
                menu.addAction(act_sh)
        else:
            act = QAction("回到太阳系原点", menu)
            act.triggered.connect(self._go_home)
            menu.addAction(act)
        menu.addSeparator()
        act_roche = QAction(f"{'隐藏' if self.show_roche else '显示'}洛希极限圈"
                            f"（{'选中天体' if self.selected_name else '请先选中天体'}）",
                            menu)
        act_roche.triggered.connect(self._toggle_roche)
        menu.addAction(act_roche)
        # 地球命运模式（红巨星阶段：逃逸 = 质量损失外移贴边掠过；
        # 吞噬 = 潮汐拖拽压过外移，地球坠入光球，S&C 2008）
        from core import sun_evolution as _se
        fate_now = ("逃逸（贴边掠过）" if _se.EARTH_FATE == "escape"
                    else "吞噬（坠入光球）")
        fate_next = "吞噬" if _se.EARTH_FATE == "escape" else "逃逸"
        act_fate = QAction(f"地球命运：{fate_now}（切换为{fate_next}）", menu)
        act_fate.triggered.connect(self._toggle_earth_fate)
        menu.addAction(act_fate)
        menu.exec_(ev.globalPos())

    def _toggle_earth_fate(self):
        from core import sun_evolution as _se
        _se.EARTH_FATE = "engulf" if _se.EARTH_FATE == "escape" else "escape"
        # 位置/轨道线立即按新模式重算（清缓存 + 强制重建）
        self._orbit_scale_applied = -1.0
        self._last_orbit_rebuild = 0.0
        self._rebuild_orbits()
        mode = "吞噬" if _se.EARTH_FATE == "escape" else "逃逸"
        self._log_evolution_event(
            f"地球命运切换 → {'逃逸（贴边掠过红巨星）' if mode == '逃逸' else '吞噬（潮汐拖拽坠入光球）'}")
        self.update()

    def _toggle_roche(self):
        self.show_roche = not self.show_roche
        self.update()

    def _go_home(self):
        self.focus_body = None
        self._release_follow()
        self.focusChanged.emit("")
        self.camera.snap_focus(np.zeros(3), 80.0)
        self.update()

    def _lock_follow(self, b):
        """聚焦并锁定跟随（相机焦点每帧锁定到天体当前位置）"""
        self._focus_body(b)

    def _focus_body(self, b):
        i = next((k for k, x in enumerate(self.bodies) if x.name == b.name), None)
        if i is None:
            return
        self._mark_active(5.0)
        pos = self._body_pos[i] if self._body_pos is not None \
            else b.position_at_jd(self.clock.jd)
        self.camera.focus_on(pos, b.radius_km)
        self.focus_body = b
        self.follow_body = b
        self.focusChanged.emit(b.name)
        self.followChanged.emit(True)
        self.update()

    def _toggle_compare(self, b):
        if b.name in self.compare_names:
            self.compare_names.remove(b.name)
        else:
            if len(self.compare_names) >= 2:
                self.compare_names.pop(0)
            self.compare_names.append(b.name)
        self.compareToggled.emit(b)
        self.update()

    def focus_body_by_name(self, name):
        """外部（搜索/树）调用：聚焦指定天体并锁定跟随"""
        b = next((x for x in self.bodies if x.name == name), None)
        if b:
            self._focus_body(b)
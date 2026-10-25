"""
camera.py —— Blender 式相机（模块 B）

- 轨道模式：中键拖拽旋转 / Shift+中键平移 / 滚轮对数缩放 / Ctrl+中键缩放
- 飞行模式：Shift+~ 进入，WASD+QE 移动，鼠标转向，Shift 加速 Ctrl 减速
- 平滑阻尼（惯性）、聚焦平滑飞入（缓动动画）、视角书签
- 坐标系：J2000 黄道系，Z 轴为黄道北极（AU 单位）
"""
import math
import numpy as np

ZOOM_FACTOR = 0.85          # 滚轮单次缩放比
DAMP = 6.0                  # 阻尼系数（指数衰减速率/秒）
MIN_DIST = 1e-8             # 最近视距（AU，≈1500 km）
MAX_DIST = 1e10             # 最远视距（AU，银河系尺度）
FOV_DEG = 45.0

ORBIT_SENS_BASE = 0.05      # 旋转灵敏度基准（rad/像素，乘灵敏度系数）
PAN_SENS_BASE = 0.0018      # 平移灵敏度基准（相对视距比例）
FLY_SENS_BASE = 0.004       # 飞行模式转向基准（rad/像素）
MAX_ORBIT_VEL = 12.0        # 旋转角速度上限（rad/s，防快速拖拽甩飞）


def _ease_in_out(t: float) -> float:
    """三次缓动（聚焦飞入动画）"""
    return 3 * t * t - 2 * t * t * t


class OrbitCamera:
    """轨道相机 + 飞行漫游，支持平滑阻尼与对数缩放"""

    def __init__(self):
        self.focus = np.zeros(3)              # 焦点位置（AU）
        self.distance = 80.0                  # 视距（AU）
        self.azimuth = math.radians(35.0)     # 方位角
        self.elevation = math.radians(20.0)   # 俯仰角
        # 阻尼状态
        self._d_az = 0.0
        self._d_el = 0.0
        self._pan_vel = np.zeros(3)
        self._zoom_vel = 0.0
        # 聚焦动画
        self._anim_active = False
        self._anim_t = 0.0
        self._anim_dur = 0.9
        self._anim_focus_from = np.zeros(3)
        self._anim_focus_to = np.zeros(3)
        self._anim_dist_from = 1.0
        self._anim_dist_to = 1.0
        # 轴向视角动画（View Gizmo 点击 / Numpad 视图键共用）
        self._v_anim = None
        # 飞行模式
        self.fly_mode = False
        self.fly_pos = np.zeros(3)
        self.fly_yaw = 0.0
        self.fly_pitch = 0.0
        self._fly_vel = np.zeros(3)
        self._fly_speed_base = 0.005          # AU/s 基准速度
        self.sensitivity = 1.0                # 视角灵敏度系数（1.0 为标准）

    # ---------- 视图矩阵 ----------
    def eye_position(self) -> np.ndarray:
        """相机眼点（AU）"""
        if self.fly_mode:
            return self.fly_pos.copy()
        d = self.distance
        ce, se = math.cos(self.elevation), math.sin(self.elevation)
        ca, sa = math.cos(self.azimuth), math.sin(self.azimuth)
        return self.focus + d * np.array([ce * ca, ce * sa, se])

    def forward_dir(self) -> np.ndarray:
        """视线方向（单位向量）"""
        if self.fly_mode:
            cp, sp = math.cos(self.fly_pitch), math.sin(self.fly_pitch)
            cy, sy = math.cos(self.fly_yaw), math.sin(self.fly_yaw)
            return np.array([cp * cy, cp * sy, sp])
        f = self.focus - self.eye_position()
        n = np.linalg.norm(f)
        return f / max(n, 1e-12)

    # ---------- 轨道模式操作 ----------
    def orbit(self, dx: float, dy: float):
        """中键拖拽旋转（累积角速度，阻尼平滑；受灵敏度系数控制）"""
        s = self.sensitivity
        if self.fly_mode:
            self.fly_yaw += dx * FLY_SENS_BASE * s
            self.fly_pitch += dy * FLY_SENS_BASE * s
            self.fly_pitch = max(-1.55, min(1.55, self.fly_pitch))
            return
        self._d_az = max(-MAX_ORBIT_VEL,
                         min(MAX_ORBIT_VEL, self._d_az - dx * ORBIT_SENS_BASE * s))
        self._d_el = max(-MAX_ORBIT_VEL,
                         min(MAX_ORBIT_VEL, self._d_el + dy * ORBIT_SENS_BASE * s))
        self._anim_active = False
        self._v_anim = None          # 用户拖拽打断视角动画

    def pan(self, dx: float, dy: float):
        """Shift+中键平移（随视距缩放）"""
        if self.fly_mode:
            return
        scale = self.distance * PAN_SENS_BASE * self.sensitivity
        self._pan_vel += self._screen_axes() @ np.array([-dx * scale, dy * scale, 0.0])
        self._anim_active = False

    def zoom_step(self, factor: float):
        """滚轮/键盘对数缩放"""
        self._zoom_vel += factor
        self._anim_active = False

    def _screen_axes(self) -> np.ndarray:
        """屏幕右/上/视线方向矩阵（列）"""
        fwd = self.forward_dir()
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, world_up)
        n = np.linalg.norm(right)
        right = right / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        up = np.cross(right, fwd)
        return np.column_stack([right, up, fwd])

    def set_view(self, azimuth_deg: float, elevation_deg: float):
        """正交视图切换（瞬跳：书签 restore / 程序化调用用；交互切视角走 view_to）"""
        self.azimuth = math.radians(azimuth_deg)
        self.elevation = math.radians(max(-89.9, min(89.9, elevation_deg)))
        self._d_az = self._d_el = 0.0

    # ---------- 轴向视角动画（View Gizmo / Numpad 1·3·7 共用） ----------
    def view_to(self, azimuth_deg=None, elevation_deg=None, duration: float = 0.4):
        """平滑切到轴向视角（约 300~500ms 缓动，可打断）。

        - azimuth_deg / elevation_deg 为 None 表示该角保持当前值：
          +Z 俯视 / -Z 仰视时水平朝向无唯一解，保持当前 az 动画最平滑
          （不会先水平甩一大圈再抬头）
        - 方位角沿最短角路径插值（±180° 内）
        - focus / distance 不动：观察目标（含锁定跟随天体）与缩放保持不变
        - 飞行模式下转 fly_yaw / fly_pitch（等效视角），同一动画字段推进
        - 可打断：动画中再次 view_to 直接改道新目标；用户 orbit 拖拽亦打断
        """
        if self.fly_mode:
            az0 = math.degrees(self.fly_yaw)
            el0 = math.degrees(self.fly_pitch)
        else:
            az0 = math.degrees(self.azimuth)
            el0 = math.degrees(self.elevation)
        az1 = az0 if azimuth_deg is None else float(azimuth_deg)
        el1 = el0 if elevation_deg is None else float(elevation_deg)
        el1 = max(-89.9, min(89.9, el1))
        d_az = (az1 - az0 + 180.0) % 360.0 - 180.0   # 最短角路径
        self._v_anim = dict(az0=az0, d_az=d_az, el0=el0, d_el=el1 - el0,
                            t=0.0, dur=max(0.05, float(duration)))
        self._d_az = self._d_el = 0.0

    @property
    def view_anim_active(self) -> bool:
        return self._v_anim is not None

    def _step_view_anim(self, dt: float):
        va = self._v_anim
        if va is None:
            return
        va["t"] += dt / va["dur"]
        t = min(1.0, va["t"])
        e = _ease_in_out(t)
        az = math.radians(va["az0"] + va["d_az"] * e)
        el = math.radians(va["el0"] + va["d_el"] * e)
        if self.fly_mode:
            self.fly_yaw = az
            self.fly_pitch = max(-1.55, min(1.55, el))
        else:
            self.azimuth = az
            # el 不钳 ±1.55：那是 orbit 阻尼交互的防翻转钳；轴向视角
            # 目标 ±89.9° 已在 view_to 入口校验，动画直接到达
            self.elevation = el
        if t >= 1.0:
            self._v_anim = None

    def set_sensitivity(self, value: float):
        """统一设置视角灵敏度（0.05 ~ 8.0；1.0 为标准，数值越大转得越快）"""
        self.sensitivity = max(0.05, min(8.0, float(value)))

    # ---------- 聚焦 ----------
    def focus_on(self, pos: np.ndarray, body_radius_km: float = None, radius_boost: float = 1.0):
        """聚焦到天体（平滑飞入，自动调整距离）。

        距离按天体**真实半径**的若干倍计算，使实体球在视野中占据合适比例
        （约 4 倍半径 ≈ 张角 28°，即"贴脸"但能看全整个球体）。"""
        target_dist = 8.0
        if body_radius_km:
            r_au = (body_radius_km / 1.495978707e8) * max(radius_boost, 1e-6)
            target_dist = max(r_au * 4.0, MIN_DIST * 50)
        target_dist = max(MIN_DIST * 20, min(target_dist, 2e6))
        self._anim_focus_from = self.focus.copy()
        self._anim_focus_to = np.asarray(pos, dtype=np.float64).copy()
        self._anim_dist_from = self.distance
        self._anim_dist_to = target_dist
        self._anim_t = 0.0
        self._anim_active = True
        self._d_az = self._d_el = 0.0
        self._pan_vel = np.zeros(3)

    def snap_focus(self, pos: np.ndarray, dist: float = None):
        """直接设置焦点（搜索定位等）"""
        self.focus = np.asarray(pos, dtype=np.float64).copy()
        if dist is not None:
            self.distance = max(MIN_DIST, min(dist, MAX_DIST))
        self._anim_active = False

    # ---------- 飞行模式 ----------
    def enter_fly(self):
        """进入飞行模式（Shift+~）：从当前位置继续"""
        self.fly_pos = self.eye_position()
        fwd = self.forward_dir()
        self.fly_yaw = math.atan2(fwd[1], fwd[0])
        self.fly_pitch = math.asin(max(-1.0, min(1.0, fwd[2])))
        self.fly_mode = True
        self._fly_vel = np.zeros(3)

    def exit_fly(self):
        """退出飞行模式：回到轨道视角（焦点取视线前方一点）"""
        fwd = self.forward_dir()
        self.focus = self.fly_pos + fwd * max(self.distance, 1e-3)
        eye = self.fly_pos
        d = self.focus - eye
        self.distance = float(np.clip(np.linalg.norm(d), MIN_DIST, MAX_DIST))
        self.elevation = math.asin(max(-1.0, min(1.0, d[2] / max(self.distance, 1e-12))))
        self.azimuth = math.atan2(d[1], d[0])
        self.fly_mode = False

    def fly_move(self, direction: int, axis: str, speed_mult: float = 1.0):
        """WASD+QE 移动（direction: +1/-1；axis: x 前后 / y 左右 / z 上下；
        speed_mult: Shift 加速 ×5 / Ctrl 减速 ×0.2）"""
        if not self.fly_mode:
            return
        speed = self._fly_speed_base * self._fly_speed_scale() * speed_mult
        fwd = self.forward_dir()
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
        n = np.linalg.norm(right)
        right = right / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        up = np.cross(right, fwd)
        if axis == "x":
            self._fly_vel += fwd * speed * direction
        elif axis == "y":
            self._fly_vel += right * speed * direction
        elif axis == "z":
            self._fly_vel += up * speed * direction

    def _fly_speed_scale(self) -> float:
        """飞行速度随视尺度自适应（Shift/Ctrl 由 key 状态在 viewport 控制）"""
        return max(1e-3, min(self.distance, 1e5))

    def set_fly_speed_factor(self, factor: float):
        self._fly_speed_base = max(1e-7, min(50.0, factor))

    # ---------- 每帧更新 ----------
    def update(self, dt: float):
        """推进阻尼/动画（dt 秒）"""
        self._step_view_anim(dt)
        if self.fly_mode:
            self.fly_pos = self.fly_pos + self._fly_vel * dt
            self._fly_vel *= math.exp(-DAMP * dt)
            return
        # 聚焦动画
        if self._anim_active:
            self._anim_t += dt / self._anim_dur
            t = min(1.0, self._anim_t)
            e = _ease_in_out(t)
            self.focus = self._anim_focus_from + (self._anim_focus_to - self._anim_focus_from) * e
            d0, d1 = max(self._anim_dist_from, MIN_DIST), max(self._anim_dist_to, MIN_DIST)
            self.distance = math.exp(math.log(d0) + (math.log(d1) - math.log(d0)) * e)
            if t >= 1.0:
                self._anim_active = False
            return
        # 旋转阻尼
        if abs(self._d_az) > 1e-5 or abs(self._d_el) > 1e-5:
            self.azimuth += self._d_az * dt
            self.elevation = max(-1.55, min(1.55, self.elevation + self._d_el * dt))
            k = math.exp(-DAMP * dt)
            self._d_az *= k
            self._d_el *= k
        # 平移阻尼
        if np.linalg.norm(self._pan_vel) > 1e-14:
            self.focus = self.focus + self._pan_vel * dt
            self._pan_vel *= math.exp(-DAMP * dt)
        # 缩放阻尼（对数空间）
        if abs(self._zoom_vel) > 1e-4:
            step = ZOOM_FACTOR ** self._zoom_vel
            self.distance = float(np.clip(self.distance * step, MIN_DIST, MAX_DIST))
            self._zoom_vel *= math.exp(-DAMP * 1.4 * dt)

    # ---------- 书签 ----------
    def bookmark(self) -> dict:
        return dict(focus=self.focus.copy(), distance=self.distance,
                    azimuth=self.azimuth, elevation=self.elevation,
                    fly_mode=self.fly_mode, fly_pos=self.fly_pos.copy(),
                    fly_yaw=self.fly_yaw, fly_pitch=self.fly_pitch)

    def restore(self, bm: dict):
        if bm.get("fly_mode"):
            self.fly_mode = True
            self.fly_pos = bm["fly_pos"].copy()
            self.fly_yaw, self.fly_pitch = bm["fly_yaw"], bm["fly_pitch"]
        else:
            self.fly_mode = False
            self.focus = bm["focus"].copy()
            self.distance = bm["distance"]
            self.azimuth, self.elevation = bm["azimuth"], bm["elevation"]
            self._anim_active = False
            self._d_az = self._d_el = 0.0
            self._pan_vel = np.zeros(3)
            self._zoom_vel = 0.0
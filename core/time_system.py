"""
time_system.py —— 儒略日换算与仿真时钟

- 儒略日（JD）与公历日期互转（Fliegel-Van Flandern 算法，格里高利历）
- 仿真时钟：播放/暂停/倍速（含倒放）/跳转日期
- 历元约定：内部以 JD 表示，轨道根数对应 J2000.0 历元（JD 2451545.0）
"""
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from core.constants import J2000_JD


# ---------- 儒略日换算 ----------
def datetime_to_jd(dt: datetime) -> float:
    """公历（UTC，忽略 TT-UTC 的 69 秒差，文档中说明）→ 儒略日"""
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                  + dt.microsecond / 3.6e9) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5


def jd_to_datetime(jd: float) -> datetime:
    """儒略日 → 公历 datetime"""
    jd += 0.5
    Z = int(jd)
    F = jd - Z
    if Z < 2299161:
        A = Z
    else:
        alpha = int((Z - 1867216.25) / 36524.25)
        A = Z + 1 + alpha - alpha // 4
    B = A + 1524
    C = int((B - 122.1) / 365.25)
    D = int(365.25 * C)
    E = int((B - D) / 30.6001)
    day = B - D - int(30.6001 * E) + F
    month = E - 1 if E < 14 else E - 13
    year = C - 4716 if month > 2 else C - 4715
    day_i = int(day)
    frac = day - day_i
    hour = frac * 24.0
    h = int(hour)
    minute = (hour - h) * 60.0
    mi = int(minute)
    sec = (minute - mi) * 60.0
    try:
        return datetime(year, month, day_i, h, mi, min(int(sec), 59))
    except ValueError:
        return datetime(year, month, day_i)


# ---------- 时间倍速档位（单位：仿真天 / 真实秒） ----------
SPEED_STEPS = [
    ("实时 ×1",      1.0 / 86400.0),
    ("1 分钟/秒",    60.0 / 86400.0),
    ("1 小时/秒",    1.0 / 24.0),
    ("1 天/秒",      1.0),
    ("1 周/秒",      7.0),
    ("1 月/秒",      30.0),
    ("1 年/秒",      365.25),
    ("10 年/秒",     3652.5),
    ("100 年/秒",    36525.0),
]
DEFAULT_SPEED_INDEX = 3  # 默认 1 天/秒


@dataclass
class SimulationClock:
    """仿真时钟：驱动所有天体位置计算与分析面板，保证时间同步"""
    jd: float = field(default_factory=lambda: datetime_to_jd(datetime.now()))
    playing: bool = True
    speed_index: int = DEFAULT_SPEED_INDEX
    direction: int = 1          # 1 正放，-1 倒放
    min_jd: float = J2000_JD - 36525.0    # 约 1900 年（星历适用边界提示用）
    max_jd: float = J2000_JD + 36525.0    # 约 2050 年（JPL 近似星历适用范围）

    @property
    def speed(self) -> float:
        return SPEED_STEPS[self.speed_index][1] * self.direction

    @property
    def speed_label(self) -> str:
        sign = "-" if self.direction < 0 else ""
        return sign + SPEED_STEPS[self.speed_index][0]

    def update(self, real_seconds: float):
        """每帧调用：按倍速推进仿真时间（不做范围硬截断，超界时 UI 提示精度下降）"""
        if self.playing:
            self.jd += self.speed * real_seconds

    def toggle_play(self):
        self.playing = not self.playing

    def step_speed(self, delta: int):
        self.speed_index = max(0, min(len(SPEED_STEPS) - 1, self.speed_index + delta))

    def reverse(self):
        self.direction *= -1

    def jump_to(self, jd: float):
        self.jd = jd

    def jump_to_datetime(self, dt: datetime):
        self.jd = datetime_to_jd(dt)

    def now_datetime(self) -> datetime:
        return jd_to_datetime(self.jd)

    def days_since_j2000(self) -> float:
        return self.jd - J2000_JD

    def centuries_since_j2000(self) -> float:
        return self.days_since_j2000() / 36525.0
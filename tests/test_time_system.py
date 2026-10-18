"""test_time_system.py —— 儒略日换算边界（datetime 年份超界钳制）与仿真时钟"""
from datetime import datetime

from core.time_system import (
    MAX_CUSTOM_YEARS_PER_SEC,
    SPEED_STEPS,
    SimulationClock,
    datetime_to_jd,
    jd_to_datetime,
    jd_to_ymd,
)

J2000_JD = 2451545.0
JD_YEAR_12042 = 6119311.0  # 12042-01-01 12:00 UTC


def test_jd_to_ymd_j2000_anchor():
    assert jd_to_ymd(J2000_JD) == (2000, 1, 1, 12, 0, 0.0)


def test_jd_to_ymd_far_future_real_year():
    y, m, d, h, _mi, _s = jd_to_ymd(JD_YEAR_12042)
    assert (y, m, d, h) == (12042, 1, 1, 12)


def test_jd_to_datetime_far_future_clamped():
    dt = jd_to_datetime(JD_YEAR_12042)
    assert isinstance(dt, datetime)
    assert dt.year == 9999


def test_jd_to_datetime_far_past_clamped():
    dt = jd_to_datetime(-1000000.0)
    assert isinstance(dt, datetime)
    assert 1 <= dt.year <= 9999


def test_roundtrip_normal_range():
    dt = datetime(2026, 10, 18, 15, 30, 0)
    assert jd_to_datetime(datetime_to_jd(dt)) == dt


def test_clock_far_future_no_crash():
    clock = SimulationClock()
    clock.jump_to(JD_YEAR_12042)
    dt = clock.now_datetime()
    assert isinstance(dt, datetime)
    assert clock.now_ymd()[0] == 12042


def test_clock_far_past_no_crash():
    clock = SimulationClock()
    clock.jump_to(-500000.0)
    assert isinstance(clock.now_datetime(), datetime)
    y = clock.now_ymd()[0]
    assert y < 0

# ---------- 倍速档位与自定义倍速 ----------
def test_speed_steps_extended_to_gyr_scale():
    """演化功能扩展：14 档，覆盖 1 万年 → 10 亿年/秒"""
    assert len(SPEED_STEPS) == 14
    assert SPEED_STEPS[-1] == ("10 亿年/秒", 3.6525e11)
    labels = [s[0] for s in SPEED_STEPS]
    assert "1 万年/秒" in labels          # 原最大档仍在（尾迹几何弧依赖）
    assert labels.index("1 亿年/秒") == 12  # 教学场景 speed_index=12


def test_custom_speed_set_and_label():
    clock = SimulationClock()
    clock.set_custom_speed(500.0)
    assert clock.speed_index == len(SPEED_STEPS)
    assert abs(clock.speed - 500.0 * 365.25) < 1e-9
    assert "500" in clock.speed_label


def test_custom_speed_clamped_to_10000_years():
    clock = SimulationClock()
    clock.set_custom_speed(999999.0)
    assert abs(clock.speed - MAX_CUSTOM_YEARS_PER_SEC * 365.25) < 1e-6
    assert "10000" in clock.speed_label


def test_custom_speed_nonpositive_ignored():
    clock = SimulationClock()
    clock.set_custom_speed(-5.0)
    assert clock.custom_speed == 0.0
    assert clock.speed_index != len(SPEED_STEPS) or clock.custom_speed == 0.0


def test_speed_index_overflow_falls_back_to_max_step():
    clock = SimulationClock()
    clock.speed_index = len(SPEED_STEPS) + 5
    assert abs(clock.speed - SPEED_STEPS[-1][1]) < 1e-9
    assert "10 亿年/秒" in clock.speed_label


def test_custom_speed_advances_jd():
    clock = SimulationClock()
    clock.set_custom_speed(10000.0)
    jd0 = clock.jd
    clock.update(2.0)
    assert abs((clock.jd - jd0) - 10000.0 * 365.25 * 2.0) < 1e-6


def test_custom_speed_reversed_direction():
    clock = SimulationClock()
    clock.set_custom_speed(2.0)
    clock.reverse()
    assert clock.speed < 0
    assert clock.speed_label.startswith("-")
"""test_sun_evolution_viewport.py —— viewport 太阳演化联动（吞噬/复活/轨道重建/日志裁剪）

用 SimpleNamespace 伪造 viewport 状态（同 test_trail_geo.py 手法），
无需真实 GL 上下文即可验证 _update_sun_evolution 的判定逻辑。
"""
from types import SimpleNamespace

import numpy as np

from core.constants import J2000_JD
from core.sun_evolution import jd_from_age, sun_state
from scene.viewport import Viewport


def _make_fake(jd, positions, body_names, near_idx=None):
    """伪造 viewport：bodies 与 _body_pos 一一对应，全部视为近距天体"""
    bodies = [SimpleNamespace(name=n, body_type="star" if i == 0 else "planet_solar")
              for i, n in enumerate(body_names)]
    emitted = []
    fake = SimpleNamespace(
        bodies=bodies,
        _body_pos=np.asarray(positions, dtype=np.float64),
        _near_idx=near_idx if near_idx is not None else list(range(len(bodies))),
        _engulfed={}, _shatter_hidden=set(),
        _engulf_flash=0.0,
        _vanished_emitted=[], _engulf_dirty=False, _evo_last_jd=None,
        _star_evo_idx=None, _star_evo_last_jd=None, _star_evo_last_t=0.0,
        engulfChanged=SimpleNamespace(emit=emitted.append),
        clock=SimpleNamespace(jd=jd, speed=1.0),
        _orbit_scale_applied=1.0, _last_orbit_rebuild=0.0,
        _sun_mass_applied=1.0,
        evolution_events=[],
        follow_body=None,
    )
    rebuilds = []
    fake._rebuild_orbits = lambda: rebuilds.append(1)
    fake._refresh_near_positions = lambda jd: None
    fake._update_stellar_evolution = (
        lambda jd: Viewport._update_stellar_evolution(fake, jd))
    fake._log_evolution_event = lambda text: Viewport._log_evolution_event(fake, text)
    fake._emit_engulf_changed = lambda: Viewport._emit_engulf_changed(fake)
    fake.rebuild_count = lambda: len(rebuilds)
    fake.emitted = emitted
    return fake


def test_engulf_when_inside_photosphere():
    """RGB tip（R≈1.19 AU）：光球内的水星被吞噬，太阳本体不受影响"""
    jd = jd_from_age(12.18)
    fake = _make_fake(jd, [[0, 0, 0], [0.3, 0, 0]], ["太阳", "水星"])
    Viewport._update_sun_evolution(fake, jd)
    assert 1 in fake._engulfed
    assert 0 not in fake._engulfed            # 恒星永不吞噬
    assert len(fake.evolution_events) == 1
    assert "水星" in fake.evolution_events[0][2]
    assert fake.evolution_events[0][1] > 12.0  # 年龄字段（Gyr）


def test_engulf_revival_when_rewound():
    """跳回吞噬发生之前（含跳回主序）：天体恢复显示（时间条件复活）"""
    jd = jd_from_age(12.18)
    fake = _make_fake(jd, [[0, 0, 0], [0.3, 0, 0]], ["太阳", "水星"])
    Viewport._update_sun_evolution(fake, jd)
    assert 1 in fake._engulfed
    # 跳回现在（2026 年，早于吞噬时刻）→ 水星恢复
    jd_past = J2000_JD
    fake.clock.jd = jd_past
    fake._body_pos = np.array([[0, 0, 0], [0.3, 0, 0]], dtype=np.float64)
    Viewport._update_sun_evolution(fake, jd_past)
    assert 1 not in fake._engulfed
    # 复活 → 发出空列表信号（左侧树恢复条目）
    assert fake.emitted and fake.emitted[-1] == []


def test_engulf_no_revival_when_sun_shrinks():
    """核心回归：太阳收缩成白矮星后，被吞行星不得复活。

    旧 bug：复活判定按「距离 > 光球半径」，白矮星光球极小（~6e-5 AU）
    导致全部被吞行星错误复活（用户实测报告）。
    """
    jd_tip = jd_from_age(12.18)               # RGB tip：吞噬水星
    fake = _make_fake(jd_tip, [[0, 0, 0], [0.3, 0, 0]], ["太阳", "水星"])
    Viewport._update_sun_evolution(fake, jd_tip)
    assert 1 in fake._engulfed
    # 推进到白矮星期（时间更晚、光球极小、水星位置仍在 0.3 AU）
    jd_wd = jd_from_age(12.50)
    fake.clock.jd = jd_wd
    Viewport._update_sun_evolution(fake, jd_wd)
    assert 1 in fake._engulfed            # 不复活：当前时间晚于吞噬时刻
    assert fake.emitted and fake.emitted[-1] == ["水星"]  # 树仍隐藏


def test_engulf_records_timestamp_and_signal():
    """吞噬记录时刻；engulfChanged 发出名字列表（树同步依据）"""
    jd = jd_from_age(12.18)
    fake = _make_fake(jd, [[0, 0, 0], [0.3, 0, 0]], ["太阳", "水星"])
    Viewport._update_sun_evolution(fake, jd)
    assert fake._engulfed[1] == jd       # dict 值 = 吞噬时刻
    assert fake.emitted == [["水星"]]
    # 吞噬后立即重建轨道（去除其轨道线）；RGB tip 时质量 <1 M☉，
    # 轨道外移联动（scale 变化）可能再触发一次重建，故断言 >= 1
    assert fake.rebuild_count() >= 1


def test_engulf_takes_moons_with_planet():
    """行星被吞时其卫星一并消失（贴边掠过时卫星可能差一点点距离）"""
    jd = jd_from_age(12.18)
    earth = SimpleNamespace(name="地球", body_type="planet_solar", parent=None)
    moon = SimpleNamespace(name="月球", body_type="moon", parent=earth)
    sun = SimpleNamespace(name="太阳", body_type="star")
    fake = SimpleNamespace(
        bodies=[sun, earth, moon],
        _body_pos=np.array([[0, 0, 0], [0.5, 0, 0], [0.5003, 0, 0]]),
        _near_idx=[0, 1, 2],
        _engulfed={}, _shatter_hidden=set(), _engulf_flash=0.0,
        _vanished_emitted=[], _engulf_dirty=False, _evo_last_jd=None,
        _star_evo_idx=None, _star_evo_last_jd=None, _star_evo_last_t=0.0,
        engulfChanged=SimpleNamespace(emit=lambda n: None),
        clock=SimpleNamespace(jd=jd, speed=1.0),
        _orbit_scale_applied=1.0, _last_orbit_rebuild=0.0,
        _sun_mass_applied=1.0, evolution_events=[], follow_body=None,
    )
    fake._rebuild_orbits = lambda: None
    fake._refresh_near_positions = lambda jd: None
    fake._update_stellar_evolution = (
        lambda jd: Viewport._update_stellar_evolution(fake, jd))
    fake._log_evolution_event = lambda text: None
    fake._emit_engulf_changed = lambda: Viewport._emit_engulf_changed(fake)
    Viewport._update_sun_evolution(fake, jd)
    assert 1 in fake._engulfed            # 地球被吞
    assert 2 in fake._engulfed            # 月球随母行星消失


def test_main_sequence_not_active():
    """当前（主序）：演化联动未激活，无吞噬无事件"""
    fake = _make_fake(J2000_JD, [[0, 0, 0], [0.3, 0, 0]], ["太阳", "水星"])
    Viewport._update_sun_evolution(fake, J2000_JD)
    assert fake._evo_active is False
    assert not fake._engulfed
    assert not fake.evolution_events
    assert fake._sun_state_cache.phase == "主序"


def test_engulf_jump_uses_current_positions():
    """时间跳转帧：吞噬判定用当前时刻（含质量损失外移）位置，不用上一帧缓存。

    回归：跳到 RGB tip 后第一帧，旧缓存还是主序位置（地球 1.0 AU），
    会误吞实际外移到 1.21 AU 贴边掠过的地球（真实 GL 冒烟曾捕获）。
    """
    jd = jd_from_age(12.18)               # RGB tip：光球 1.19 AU
    fake = _make_fake(jd, [[0, 0, 0], [1.0, 0, 0]], ["太阳", "地球"])
    fake.bodies[0].position_at_jd = lambda jd: np.zeros(3)
    fake.bodies[1].position_at_jd = lambda jd: np.array([1.21, 0.0, 0.0])
    fake._refresh_near_positions = (
        lambda jd: Viewport._refresh_near_positions(fake, jd))
    Viewport._update_sun_evolution(fake, jd)   # _evo_last_jd=None → 视为跳转
    assert 1 not in fake._engulfed         # 1.21 AU > 1.19×0.98：贴边掠过不误吞
    assert fake._body_pos[1][0] == 1.21    # 位置缓存已被重算为当前时刻


def test_orbit_rebuild_on_mass_loss():
    """AGB 质量损失（0.546 M☉）→ 外移因子变化超阈值 → 轨道重建一次（限频）"""
    jd = jd_from_age(12.38)
    # 行星放 5 AU（AGB tip R≈0.79 AU 之外，避免吞噬干扰）
    fake = _make_fake(jd, [[0, 0, 0], [5.0, 0, 0]], ["太阳", "木星"])
    Viewport._update_sun_evolution(fake, jd)
    assert fake.rebuild_count() == 1
    assert abs(fake._orbit_scale_applied - 1.0) > 0.01  # 已应用外移因子
    # 同帧再次调用：因子已应用且限频窗口内 → 不再重建
    Viewport._update_sun_evolution(fake, jd)
    assert fake.rebuild_count() == 1
    assert not fake._engulfed


def test_log_event_trim():
    """事件日志上限裁剪：>400 条时删除最旧 200 条"""
    jd = jd_from_age(12.18)
    fake = _make_fake(jd, [[0, 0, 0]], ["太阳"])
    fake.evolution_events = [(0.0, 5.0, "旧事件")] * 400
    fake._log_evolution_event("新事件")
    assert len(fake.evolution_events) == 201
    assert fake.evolution_events[-1][2] == "新事件"
    assert fake.evolution_events[0][2] == "旧事件"


def test_sun_state_cache_matches_model():
    """_sun_state_cache 与核心模型 sun_state 一致（半径/质量/阶段）"""
    jd = jd_from_age(13.0)   # 白矮星冷却期
    fake = _make_fake(jd, [[0, 0, 0]], ["太阳"])
    Viewport._update_sun_evolution(fake, jd)
    st = fake._sun_state_cache
    ref = sun_state(13.0)
    assert st.phase == ref.phase == "白矮星"
    assert abs(st.radius_solar - ref.radius_solar) < 1e-9
    assert abs(st.mass_solar - 0.546) < 1e-6
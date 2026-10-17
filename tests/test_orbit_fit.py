"""test_orbit_fit.py —— 轨道反演测试：RV 注入-回收、周期图、凌星星历"""
import numpy as np
import pytest

from core import exo_obs
from core.orbit_fit import (fit_rv_kepler, fit_transit_ephemeris, rv_model,
                            rv_periodogram)


class MockBody:
    """最小 body 对象：供 exo_obs 正演复用（字段与 data/loader.py 体系统一）"""
    body_type = "planet_exo"
    period = 12.3                # 天
    mass_earth = 300.0
    a_au = 0.098
    e = 0.20
    radius_km = 80_000.0
    host_mass_solar = 0.91
    host_radius_solar = 0.85
    host_teff = 5300.0
    host_lum = None


# ---------- 与现有正演模块的一致性 ----------
def test_rv_model_matches_exo_obs_curve():
    body = MockBody()
    omega = 37.0
    t, rv_ref, info = exo_obs.rv_curve(body, n=250, omega_deg=omega)
    K = exo_obs.rv_semi_amplitude_m_s(body)
    rv = rv_model((K, body.period, body.e, omega, 0.0, 0.0), t)
    np.testing.assert_allclose(rv, rv_ref, rtol=1e-8, atol=1e-6)


def test_rv_model_zero_eccentricity_is_sinusoid():
    t = np.linspace(0, 10.0, 200)
    rv = rv_model((20.0, 5.0, 0.0, 0.0, 1.25, 3.0), t)
    ref = 3.0 + 20.0 * np.cos(2 * np.pi * (t - 1.25) / 5.0)   # ω=0, e=0 → cos
    np.testing.assert_allclose(rv, ref, atol=1e-10)


# ---------- 周期搜索 ----------
def test_periodogram_finds_period():
    rng = np.random.default_rng(21)
    p_true = 25.0
    t = np.sort(rng.uniform(0, 200, 120))
    y = 15.0 * np.sin(2 * np.pi * t / p_true) + 40.0 + rng.normal(0, 1.0, t.size)
    periods, chi2, best = rv_periodogram(t, y, n_freq=8000)
    assert best == pytest.approx(p_true, rel=0.02)
    assert chi2.min() < chi2.max() * 0.2          # 找到周期后 χ² 显著下降


def test_periodogram_insufficient_data():
    assert rv_periodogram([1.0, 2.0], [1.0, 2.0]) == (None, None, None)


# ---------- RV 轨道拟合：注入-回收 ----------
def test_fit_rv_kepler_recovers_injected_parameters():
    rng = np.random.default_rng(42)
    truth = (12.5, 17.4, 0.25, 55.0, 2450000.5, 3.2)
    t = np.sort(rng.uniform(2450000.0, 2450000.0 + 120.0, 60))
    y_clean = rv_model(truth, t)
    y = y_clean + rng.normal(0.0, 0.15, t.size)
    out = fit_rv_kepler(t, y, rv_err=np.full(t.size, 0.15))
    assert out is not None and out["converged"]
    K, P, e, w, T0, gamma = out["params"]
    assert K == pytest.approx(truth[0], abs=0.2)
    assert P == pytest.approx(truth[1], abs=0.02)
    assert e == pytest.approx(truth[2], abs=0.03)
    # ω 与 T₀ 存在 (ω+180°, T₀+P/2) 简并，取模 360 等价解
    w_equiv = (w + 180.0) % 360.0
    assert min(abs(w - truth[3]), abs(w_equiv - truth[3])) < 5.0
    assert gamma == pytest.approx(truth[5], abs=0.15)
    # 不确定度与拟合质量
    assert 0 < out["chi2_red"] < 5
    assert out["rms"] < 0.3
    assert np.all(np.isfinite(out["errors"]))
    assert out["model_rv"].shape == out["model_t"].shape


def test_fit_rv_kepler_uses_periodogram_when_no_guess():
    rng = np.random.default_rng(7)
    truth = (8.0, 42.0, 0.05, 10.0, 2451000.0, -5.0)
    t = np.sort(rng.uniform(0, 300.0, 90))
    y = rv_model(truth, t) + rng.normal(0, 0.1, t.size)
    out = fit_rv_kepler(t, y)                    # p_guess=None → 周期图自动
    assert out is not None
    assert "periodogram_best" in out
    assert out["params"][1] == pytest.approx(truth[1], rel=0.01)


def test_fit_rv_kepler_circular_orbit():
    rng = np.random.default_rng(2)
    truth = (30.0, 6.7, 0.0, 0.0, 100.0, 0.0)
    t = np.sort(rng.uniform(0, 40.0, 45))
    y = rv_model(truth, t) + rng.normal(0, 0.2, t.size)
    out = fit_rv_kepler(t, y, rv_err=0.2)
    assert out is not None
    assert out["params"][0] == pytest.approx(30.0, abs=0.5)
    assert out["params"][2] < 0.08


def test_fit_rv_kepler_insufficient_points_returns_none():
    t = np.linspace(0, 10, 6)
    assert fit_rv_kepler(t, np.sin(t)) is None    # < 8 点


# ---------- 凌星星历 ----------
def test_fit_transit_ephemeris_exact_linear():
    T0, P = 2454000.5, 7.351
    t = np.array([T0 + n * P for n in range(12)])
    out = fit_transit_ephemeris(t)
    assert out is not None
    assert out["T0"] == pytest.approx(T0, abs=1e-6)
    assert out["P"] == pytest.approx(P, abs=1e-7)     # 儒略日量级下的浮点极限
    np.testing.assert_allclose(out["oc"], 0.0, atol=1e-7)
    assert out["oc_rms_days"] < 1e-7


def test_fit_transit_ephemeris_with_ttv_signal():
    T0, P = 2454000.5, 7.351
    ttv = np.array([0.0 if n % 5 else 0.002 for n in range(20)])   # 5 周期 TTV
    t = np.array([T0 + n * P for n in range(20)]) + ttv
    out = fit_transit_ephemeris(t)
    assert out is not None
    assert out["P"] == pytest.approx(P, rel=1e-5)
    assert 0 < out["oc_rms_days"] < 0.001
    # O−C 应反映 TTV：非零 epoch 与 TTV 同号
    assert np.any(np.abs(out["oc"]) > 1e-6)


def test_fit_transit_ephemeris_wrong_guess_recomputes_epoch():
    """周期猜测偏差 30% 时仍应正确分配循环数并恢复真周期"""
    T0, P = 2450000.0, 3.0
    t = np.array([T0 + n * P for n in range(15)])
    out = fit_transit_ephemeris(t, p_guess=P * 1.3)
    assert out["P"] == pytest.approx(P, rel=1e-6)


def test_fit_transit_ephemeris_needs_two_points():
    assert fit_transit_ephemeris([2450000.0]) is None
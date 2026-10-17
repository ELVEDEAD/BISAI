"""test_photometry.py —— 测光 / 定标 / 去噪 / 光谱预处理测试"""
import numpy as np
import pytest

from core.photometry import (airmass, aperture_photometry, apply_redshift,
                             calibrate_image, correct_extinction,
                             estimate_continuum, flux_to_mag, mag_to_flux,
                             median_filter_image, normalize_spectrum,
                             remove_cosmic_rays, savgol_smooth,
                             sigma_clipped_stats)


# ---------- CCD 定标 ----------
def test_calibrate_image_recovers_signal():
    rng = np.random.default_rng(3)
    bias = np.full((32, 32), 200.0)
    dark = np.full((32, 32), 0.5)               # ADU/s @ 1s
    flat = rng.uniform(0.9, 1.1, (32, 32))
    flat = flat / flat.mean()
    truth = rng.uniform(100, 500, (32, 32))
    exptime = 8.0
    raw = bias + dark * exptime + truth * flat
    out = calibrate_image(raw, bias=bias, dark=dark, dark_exptime=1.0,
                          flat=flat, exptime=exptime)
    np.testing.assert_allclose(out, truth, rtol=1e-10)


def test_calibrate_image_handles_zero_flat_pixel():
    raw = np.ones((4, 4))
    flat = np.ones((4, 4))
    flat[0, 0] = 0.0
    out = calibrate_image(raw, flat=flat)
    assert np.isnan(out[0, 0])
    assert out[1, 1] == 1.0


# ---------- σ 裁剪统计 ----------
def test_sigma_clipped_stats_rejects_outliers():
    rng = np.random.default_rng(11)
    d = rng.normal(0.0, 1.0, 4000)
    d[:100] += 50.0                              # 2.5% 强离群
    mean, med, std = sigma_clipped_stats(d, sigma=3.0)
    assert abs(mean) < 0.05 and abs(med) < 0.05
    assert 0.9 < std < 1.1


def test_sigma_clipped_stats_empty_nan():
    mean, med, std = sigma_clipped_stats(np.array([np.nan, np.nan]))
    assert np.isnan(mean) and np.isnan(std)


# ---------- 孔径测光 ----------
def test_aperture_photometry_gaussian_recovery():
    ny, nx = 80, 80
    sigma = 2.0
    cx, cy = 40.0, 38.0
    amp = 500.0
    yy, xx = np.mgrid[0:ny, 0:nx]
    star = amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    truth_total = amp * 2 * np.pi * sigma ** 2   # 高斯解析总流量
    r = 6.0 * sigma                              # >99.99% 能量
    res = aperture_photometry(star, cx, cy, r)
    assert abs(res["flux"] - truth_total) / truth_total < 0.01
    assert res["snr"] > 100


def test_aperture_photometry_sky_subtraction():
    ny, nx = 80, 80
    sigma = 2.0
    cx, cy = 40.0, 40.0
    amp = 200.0
    yy, xx = np.mgrid[0:ny, 0:nx]
    star = amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    truth = amp * 2 * np.pi * sigma ** 2
    img = star + 77.7                            # 恒定天背景
    res = aperture_photometry(img, cx, cy, 5 * sigma)
    assert abs(res["flux"] - truth) / truth < 0.01
    assert abs(res["sky_per_pix"] - 77.7) < 0.5


def test_aperture_photometry_noise_propagates():
    res0 = aperture_photometry(np.full((20, 20), 100.0), 10, 10, 4, gain=1, read_noise=0)
    res1 = aperture_photometry(np.full((20, 20), 100.0), 10, 10, 4, gain=1,
                               read_noise=10.0)
    # 平场无源（flux=0 扣天背景后），读出噪声越大 → snr 上限越低 / 误差越大
    assert res0["flux"] == 0.0
    assert np.isnan(res0["mag"])                 # F≤0 → 星等 NaN
    assert res1["flux_err"] > res0["flux_err"]


# ---------- 星等与消光 ----------
def test_mag_flux_roundtrip_and_pogson():
    f = np.array([1.0, 100.0, 0.01])
    m = flux_to_mag(f)
    np.testing.assert_allclose(mag_to_flux(m), f)
    # 5 星等差 = 100 倍流量
    assert abs(flux_to_mag(1.0) - flux_to_mag(100.0) - 5.0) < 1e-9
    assert np.isnan(flux_to_mag(-3.0))
    assert flux_to_mag(10.0, zeropoint=25.0) == pytest.approx(22.5)


def test_airmass_and_extinction():
    # Kasten & Young 公式在 z=0 处有 ~3e-4 的固有偏差（公式设计面向大天顶距）
    assert airmass(0.0) == pytest.approx(1.0, abs=1e-3)
    assert 1.0 < airmass(30.0) < 1.16          # 1/cos30° = 1.1547，K-Y 略低
    assert airmass(91.0) == float("inf")
    # 1 mag/airmass 消光：天顶距 60°（X≈2）观测星等应加改正 ~2 mag
    m0 = correct_extinction(10.0, 60.0, 1.0)
    assert m0 < 9.0 and m0 > 8.0


# ---------- 图像去噪 ----------
def test_remove_cosmic_rays_hits_isolated_spike_only():
    rng = np.random.default_rng(5)
    img = rng.normal(100.0, 1.0, (50, 50))
    yy, xx = np.mgrid[0:50, 0:50]
    star = 400.0 * np.exp(-((xx - 25) ** 2 + (yy - 25) ** 2) / (2 * 2.0 ** 2))
    img = img + star
    img[10, 10] += 5000.0                        # 孤立宇宙线
    clean, hit = remove_cosmic_rays(img, sigma=6.0)
    assert hit[10, 10]                           # 宇宙线命中
    assert hit.sum() == 1
    assert not hit[25, 25]                       # 星像中心（展宽）不误杀
    assert abs(clean[10, 10] - np.median(img[9:12, 9:12])) < 10.0


def test_median_filter_removes_salt_pepper():
    rng = np.random.default_rng(9)
    img = np.ones((21, 21)) * 50.0
    pos = rng.integers(0, 21, size=(40, 2))
    img[pos[:, 0], pos[:, 1]] = rng.choice([0.0, 1000.0], 40)
    out = median_filter_image(img, size=3)
    assert abs(out.mean() - 50.0) < 5.0
    assert np.allclose(np.median(out), 50.0)


# ---------- 光谱预处理 ----------
def test_savgol_smooth_reduces_noise_keeps_shape():
    rng = np.random.default_rng(13)
    x = np.linspace(0, 10, 800)
    y = np.sin(x) + rng.normal(0, 0.2, x.size)
    sm = savgol_smooth(y, window=21, polyorder=3)
    assert np.sqrt(np.mean((sm - np.sin(x)) ** 2)) < \
        0.5 * np.sqrt(np.mean((y - np.sin(x)) ** 2))
    # 平滑不破坏信号幅度
    assert abs(sm.max() - 1.0) < 0.15


def test_normalize_spectrum_flat_continuum():
    wave = np.linspace(400.0, 700.0, 3000)
    cont = 0.8 * (wave / 500.0) ** -1.2          # 连续谱随波长缓变
    line = 1.0 - 0.5 * np.exp(-0.5 * ((wave - 589.3) / 1.5) ** 2)   # Na D 吸收
    flux = cont * line
    norm, cont_est = normalize_spectrum(wave, flux, n_segments=30)
    off_line = np.abs(wave - 589.3) > 10.0
    assert np.allclose(norm[off_line], 1.0, atol=0.02)     # 连续谱归一到 1
    assert norm[np.argmin(np.abs(wave - 589.3))] < 0.6     # 线心保持深度


def test_estimate_continuum_resists_emission_outliers():
    wave = np.linspace(400.0, 700.0, 2000)
    flux = np.ones_like(wave)
    flux[500] = 50.0                             # 单点宇宙线
    cont = estimate_continuum(wave, flux, n_segments=20, percentile=95.0)
    assert np.allclose(cont, 1.0, atol=0.05)


def test_apply_redshift():
    w = np.array([500.0, 600.0])
    np.testing.assert_allclose(apply_redshift(w, 0.5), [750.0, 900.0])
    np.testing.assert_allclose(apply_redshift(w, 0.0), w)
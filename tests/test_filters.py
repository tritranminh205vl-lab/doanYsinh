import numpy as np
import pytest

from software import filters as F


def test_ma_group_delay_4ms():
    assert F.ma_group_delay_s(5, 500) == pytest.approx(0.004)
    fs = 500
    t = np.arange(2000) / fs
    x = np.sin(2 * np.pi * 2 * t)
    y = F.moving_average(x, 5)
    assert F.measure_delay_s(x, y, fs) == pytest.approx(0.004, abs=1 / fs)


def test_butter_offline_zero_phase_online_delayed(cfg):
    fs = 500
    t = np.arange(3000) / fs
    x = np.sin(2 * np.pi * 2 * t)
    y_on = F.apply_filter("butterworth", x, cfg, F.LIVE)
    y_off = F.apply_filter("butterworth", x, cfg, F.OFFLINE)
    assert F.measure_delay_s(x, y_off, fs) == pytest.approx(0.0, abs=1 / fs)
    assert F.measure_delay_s(x, y_on, fs) > 0.005


def test_savgol_forbidden_in_live(cfg):
    with pytest.raises(F.NonCausalInLiveModeError):
        F.apply_filter("savgol", np.zeros(100), cfg, F.LIVE)


def test_step_response_no_nan_and_overshoot_small(cfg):
    x = np.r_[np.zeros(200), np.ones(800)]
    for name in F.FILTER_NAMES:
        y = F.apply_filter(name, x, cfg, F.OFFLINE)
        assert np.all(np.isfinite(y))
        assert y.max() < 1.1, name


def test_short_input_edges(cfg):
    for name in F.FILTER_NAMES:
        y = F.apply_filter(name, np.ones(5), cfg, F.OFFLINE if name != "moving_average" else F.LIVE)
        assert y.shape == (5,)

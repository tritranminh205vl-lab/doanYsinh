import numpy as np
import pytest

from software.integrate import rectangle_cumulative, simpson_total, trapezoid_cumulative
from software.metrics import compute_metrics
from software.synth import physio_q
from software.waveforms import five_node_q

FS = 500.0


def five_node():
    t = np.arange(0, 3.0 + 1e-9, 1 / FS)
    return t, five_node_q(t)


def test_five_node_volumes_exact():
    t, q = five_node()
    v = trapezoid_cumulative(t, q)
    assert np.interp(1.0, t, v) == pytest.approx(1.500, abs=1e-9)
    assert v[-1] == pytest.approx(2.500, abs=1e-9)
    assert simpson_total(t, q) == pytest.approx(2.500, abs=1e-6)


def test_five_node_metrics():
    t, q = five_node()
    v = trapezoid_cumulative(t, q)
    m = compute_metrics(t, q, v, q_start=0.01)
    assert m.pef_lps == pytest.approx(2.0)
    assert m.v1s_onset_l == pytest.approx(1.5, abs=1e-6)      # Bài 14/16: V(1s) từ lúc bắt đầu
    assert m.fvc_l == pytest.approx(2.5, abs=1e-6)
    assert 100 * m.v1s_onset_l / m.fvc_l == pytest.approx(60.0, abs=1e-4)
    # Theo ATS/ERS: t0 ngoại suy ngược = 0.25 s, BEV = Qmax·tPEF/8 = 0.125 L
    assert m.t0_s == pytest.approx(0.25, abs=1e-6)
    assert m.bev_l == pytest.approx(0.125, abs=1e-4)
    assert m.fev1_l == pytest.approx(1.9375, abs=1e-4)          # V(t0+1) = V(1.25 s)


def test_trapezoid_beats_rectangle_on_curve():
    # tích phân tới 1.0 s (dòng còn lớn ở cuối) — nếu dòng về 0 ở hai đầu thì hai phương pháp trùng nhau
    t = np.arange(0, 1.0 + 1e-9, 1 / FS)
    q = physio_q(t - 0.5, 8.0, 0.08, 0.55)
    t_f = np.linspace(0, 1.0, 100001)
    v_true = trapezoid_cumulative(t_f, physio_q(t_f - 0.5, 8.0, 0.08, 0.55))[-1]
    e_trap = abs(trapezoid_cumulative(t, q)[-1] - v_true)
    e_rect = abs(rectangle_cumulative(t, q)[-1] - v_true)
    assert e_trap < e_rect
    assert e_trap / v_true < 5e-4                               # < 0.05%


def test_gap_not_integrated_across():
    t = np.arange(0, 1, 1 / FS)
    q = np.ones_like(t)
    seg = (t > 0.5).astype(int)
    v = trapezoid_cumulative(t, q, seg)
    assert v[-1] == pytest.approx(1.0 - 1 / FS - 1 / FS, abs=1e-9)


def test_no_effort_and_zero_division():
    t = np.arange(0, 2, 1 / FS)
    q = np.zeros_like(t)
    m = compute_metrics(t, q, trapezoid_cumulative(t, q))
    assert not m.valid


# ---- phát hiện dừng đột ngột (dùng cho FLAG_EARLY_TERMINATION) ---------------------------
from software.metrics import detect_abrupt_drop  # noqa: E402


def _breath(cut_s=None, cough_at=None, spikes=False, seed=0):
    t = np.arange(0, 8, 1 / FS)
    q = physio_q(t - 0.5, 8.0, 0.08, 0.55)
    if cut_s is not None:
        q[t > 0.5 + cut_s] = 0.0
    if cough_at is not None:                                   # tụt về 0 trong 40 ms rồi hồi lại
        w = (t > 0.5 + cough_at) & (t < 0.5 + cough_at + 0.04)
        q[w] = 0.0
    if spikes:                                                 # gai nhiễu lẻ tẻ sau khi tắt dòng
        rng = np.random.default_rng(seed)
        idx = rng.choice(np.flatnonzero(q == 0), 40, replace=False)
        q[idx] = 0.3
    return t, q


def test_abrupt_cut_detected():
    t, q = _breath(cut_s=1.2)
    assert detect_abrupt_drop(t, q, int(np.argmax(q)))


def test_abrupt_cut_detected_despite_noise_spikes():
    t, q = _breath(cut_s=1.2, spikes=True)
    assert detect_abrupt_drop(t, q, int(np.argmax(q)))


def test_smooth_decay_not_abrupt():
    t, q = _breath()
    assert not detect_abrupt_drop(t, q, int(np.argmax(q)))


def test_cough_dip_not_abrupt():
    t, q = _breath(cough_at=0.5)
    assert not detect_abrupt_drop(t, q, int(np.argmax(q)))

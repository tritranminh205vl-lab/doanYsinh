"""Cờ chất lượng theo ATS/ERS 2019 (Graham et al.) + cờ kỹ thuật thiết bị (VIE-13, Chương 7).

Cờ y khoa:
  FLAG_HESITATING_START   BEV > max(5% FVC, 0.100 L)
  FLAG_EARLY_TERMINATION  dừng đột ngột (Q từ ≥ 1.0 L/s tụt ≤ 0.3 L/s trong 50 ms, không hồi lại)
                          HOẶC (FET < 6 s VÀ chưa plateau)
  FLAG_PLATEAU_REACHED    ΔV trong 1 s cuối ≤ 0.025 L  (cờ thông tin, không phải lỗi)
  FLAG_COUGH_1ST_SEC      sau PEF và trong [t0, t0+1 s], Q tăng > 1.0 L/s trong ≤ 50 ms
  FLAG_REPEATABLE         2 FVC lớn nhất lệch ≤ 0.150 L VÀ 2 FEV1 lớn nhất lệch ≤ 0.150 L
Cờ kỹ thuật:
  FLAG_ZERO_DRIFT         |trung bình ΔP| ở đoạn đuôi (sau khi thở xong) > ngưỡng
  FLAG_PACKET_LOSS        có khoảng mất mẫu > 10 ms (INVALID_GAP)
  FLAG_UNCALIBRATED       chưa nạp calibration/model.json

Ghi chú về chuẩn: ATS/ERS 2019 bỏ yêu cầu bắt buộc FET ≥ 6 s của bản 2005; tiêu chí kết thúc
là plateau ≤ 0.025 L trong 1 s cuối, HOẶC FET ≥ 15 s, HOẶC FVC lặp lại. Quy tắc "FET < 6 s"
ở đây giữ theo sổ tay nhóm; cần ghi rõ trong báo cáo.
"""
from __future__ import annotations

import numpy as np

from .metrics import Metrics

HESITATING = "FLAG_HESITATING_START"
EARLY_TERM = "FLAG_EARLY_TERMINATION"
PLATEAU = "FLAG_PLATEAU_REACHED"
COUGH = "FLAG_COUGH_1ST_SEC"
REPEATABLE = "FLAG_REPEATABLE"
ZERO_DRIFT = "FLAG_ZERO_DRIFT"
PACKET_LOSS = "FLAG_PACKET_LOSS"
UNCALIBRATED = "FLAG_UNCALIBRATED"

FAIL_FLAGS = {HESITATING, EARLY_TERM, COUGH, ZERO_DRIFT, PACKET_LOSS}

DEFAULTS = dict(
    bev_frac=0.05, bev_abs_l=0.100,
    fet_min_s=6.0, plateau_dv_l=0.025, abrupt_q_lps=0.5,
    cough_dq_lps=1.0, cough_window_s=0.050,
    zero_drift_pa=0.6, tail_s=1.5,
    repeat_tol_l=0.150,
)


def check_hesitating_start(m: Metrics, p=DEFAULTS) -> bool:
    return m.bev_l > max(p["bev_frac"] * m.fvc_l, p["bev_abs_l"])


def check_plateau(m: Metrics, p=DEFAULTS) -> bool:
    return m.plateau_dv_l <= p["plateau_dv_l"]


def check_early_termination(m: Metrics, p=DEFAULTS) -> bool:
    # dừng đột ngột: dòng tụt từ > 0.5 L/s về 0 trước khi hết bản ghi
    abrupt = m.abrupt_drop or ((m.q_before_end_lps > p["abrupt_q_lps"]) and not m.flow_at_record_end)
    return abrupt or (m.fet_s < p["fet_min_s"] and not check_plateau(m, p))


def check_cough(t_s, q, m: Metrics, fs: float, p=DEFAULTS) -> bool:
    t = np.asarray(t_s)
    q = np.asarray(q, dtype=np.float64)
    w = int(round(p["cough_window_s"] * fs))
    sel = np.flatnonzero((t > m.t_pef_s) & (t <= m.t0_s + 1.0))
    if sel.size == 0:
        return False
    for i in sel:
        lo = max(sel[0], i - w)
        if q[i] - q[lo:i + 1].min() > p["cough_dq_lps"]:
            return True
    return False


def check_zero_drift(t_s, dp_pa, m: Metrics, p=DEFAULTS) -> tuple[bool, float]:
    """Trung bình ΔP (miền tuyến tính) ở đoạn đuôi sau khi thở xong."""
    t = np.asarray(t_s)
    dp = np.asarray(dp_pa, dtype=np.float64)
    t_from = max(m.t0_s + 3.0, t[-1] - p["tail_s"])
    tail = dp[t >= t_from]
    if tail.size < 50:
        return False, float("nan")
    mean_dp = float(np.mean(tail))
    return abs(mean_dp) > p["zero_drift_pa"], mean_dp


def check_repeatability(fvcs, fev1s, p=DEFAULTS) -> bool:
    fvcs = sorted(fvcs, reverse=True)
    fev1s = sorted(fev1s, reverse=True)
    if len(fvcs) < 2 or len(fev1s) < 2:
        return False
    return (fvcs[0] - fvcs[1] <= p["repeat_tol_l"]) and (fev1s[0] - fev1s[1] <= p["repeat_tol_l"])


def evaluate(t_s, q, dp_pa, m: Metrics, fs: float, gap_invalid: bool, calibrated: bool,
             p=DEFAULTS) -> dict:
    flags = []
    if not m.valid:
        return {"flags": ["NO_EFFORT_DETECTED"], "status": "INVALID", "tail_dp_mean_pa": float("nan")}
    if gap_invalid:
        flags.append(PACKET_LOSS)
    if check_hesitating_start(m, p):
        flags.append(HESITATING)
    if check_early_termination(m, p):
        flags.append(EARLY_TERM)
    if check_plateau(m, p):
        flags.append(PLATEAU)
    if check_cough(t_s, q, m, fs, p):
        flags.append(COUGH)
    drift, tail_mean = check_zero_drift(t_s, dp_pa, m, p)
    if drift:
        flags.append(ZERO_DRIFT)
    if not calibrated:
        flags.append(UNCALIBRATED)
    status = "FAILED" if FAIL_FLAGS.intersection(flags) else "PASSED"
    return {"flags": flags, "status": status, "tail_dp_mean_pa": tail_mean}

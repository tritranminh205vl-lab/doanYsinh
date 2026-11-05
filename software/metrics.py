"""Trích xuất chỉ số hô hấp ký: PEF, t0 (ngoại suy ngược), BEV, FEV1, FVC, FEV1/FVC, FET.

Định nghĩa thời điểm 0 (ATS/ERS 2019): kẻ tiếp tuyến của đường V(t) tại điểm dốc nhất
(chính là điểm PEF, độ dốc = PEF), giao trục V = V_onset tại t0:
    t0  = t_PEF − (V(t_PEF) − V_onset) / PEF
    BEV = V(t0) − V_onset   (thể tích ngoại suy ngược)
    FEV1 = V(t0 + 1 s) − V_onset
Lưu ý: công thức "VBE = V(t0) − Qmax·tPEF/2" trong sổ tay VIE-13 KHÔNG đúng. Với đoạn lên
tuyến tính 0→Qmax trong tPEF, kết quả đúng là BEV = Qmax·tPEF/8.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class Metrics:
    valid: bool
    pef_lps: float = np.nan
    t_pef_s: float = np.nan
    t_onset_s: float = np.nan
    t0_s: float = np.nan
    bev_l: float = np.nan
    fev1_l: float = np.nan
    v1s_onset_l: float = np.nan     # V(t_onset + 1 s), không ngoại suy ngược (Bài 14/16)
    fvc_l: float = np.nan
    fev1_fvc_pct: float = np.nan
    t_end_s: float = np.nan
    fet_s: float = np.nan
    plateau_dv_l: float = np.nan
    q_before_end_lps: float = np.nan
    flow_at_record_end: bool = False   # bản ghi kết thúc khi vẫn còn dòng

    def as_dict(self):
        return asdict(self)


def _interp(t, y, tq):
    return float(np.interp(tq, t, y))


def compute_metrics(t_s, q, v, q_start: float = 0.5, search_from_s: float = 0.0,
                    end_gap_s: float = 0.10) -> Metrics:
    """t_s, q (L/s), v (L, tích lũy từ đầu bản ghi)."""
    t = np.asarray(t_s, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    mask = t >= search_from_s
    idx_above = np.flatnonzero(mask & (q > q_start))
    if idx_above.size == 0:
        return Metrics(valid=False)
    i_start = idx_above[0]
    # lùi về điểm bắt đầu thở thật (Q ≤ 0 gần nhất trước đó)
    i_on = i_start
    while i_on > 0 and q[i_on - 1] > 0 and t[i_on - 1] >= search_from_s:
        i_on -= 1
    if i_on > 0:
        i_on -= 1                     # mẫu Q ≤ 0 cuối cùng = điểm bắt đầu
    v_on = v[i_on]
    vr = v - v_on

    i_pef = i_on + int(np.argmax(q[i_on:]))
    pef = float(q[i_pef])
    t_pef = float(t[i_pef])
    t0 = t_pef - vr[i_pef] / pef
    t0 = max(t0, float(t[i_on]))
    bev = _interp(t, vr, t0)

    fvc = float(np.max(vr[i_on:]))
    fev1 = _interp(t, vr, t0 + 1.0) if t0 + 1.0 <= t[-1] else fvc

    t_on = float(t[i_on])
    v1s_on = _interp(t, vr, t_on + 1.0)

    # kết thúc thở ra: mẫu Q>0 cuối cùng trước một đoạn Q≤0 kéo dài ≥ end_gap_s
    # (bỏ qua các gai nhiễu lẻ tẻ phía sau)
    i_end = i_pef
    i = i_pef
    while i < q.size:
        if q[i] > 0:
            i_end = i
        elif t[i] - t[i_end] >= end_gap_s:
            break
        i += 1
    t_end = float(t[i_end])
    w = (t >= t_end - 0.05) & (t <= t_end)
    q_before_end = float(np.max(q[w]))
    reached_end = (t[-1] - t_end) < end_gap_s     # vẫn còn thở khi hết bản ghi

    t_last = float(t[-1])
    plateau_dv = float(vr[-1] - _interp(t, vr, t_last - 1.0))

    return Metrics(
        valid=True, pef_lps=pef, t_pef_s=t_pef, t_onset_s=float(t[i_on]), t0_s=float(t0),
        bev_l=float(bev), fev1_l=float(fev1), v1s_onset_l=v1s_on, fvc_l=fvc,
        fev1_fvc_pct=(100.0 * fev1 / fvc) if fvc > 0 else np.nan,
        t_end_s=t_end, fet_s=t_end - t0, plateau_dv_l=plateau_dv, q_before_end_lps=q_before_end,
        flow_at_record_end=bool(reached_end),
    )

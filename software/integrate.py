"""Tích phân thể tích theo bước thời gian thực của MCU (VIE-07, mục 5.2).

    V[n] = V[n-1] + ½ (Q[n] + Q[n-1]) (t[n] − t[n-1])

Nếu có segment_id (từ apply_drop_policy) thì KHÔNG cộng diện tích qua ranh giới hai
segment — tức là cấm nối tích phân xuyên qua khoảng mất mẫu.
"""
from __future__ import annotations

import numpy as np
from scipy import integrate as _sint


def trapezoid_cumulative(t_s, q, segment_id=None):
    t = np.asarray(t_s, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    dt = np.diff(t)
    inc = 0.5 * (q[1:] + q[:-1]) * dt
    if segment_id is not None:
        seg = np.asarray(segment_id)
        inc[seg[1:] != seg[:-1]] = 0.0
    return np.concatenate(([0.0], np.cumsum(inc)))


def rectangle_cumulative(t_s, q):
    """Euler lùi (hình chữ nhật) — chỉ để đối chiếu sai số O(Δt)."""
    t = np.asarray(t_s, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    return np.concatenate(([0.0], np.cumsum(q[:-1] * np.diff(t))))


def simpson_total(t_s, q):
    return float(_sint.simpson(np.asarray(q, dtype=np.float64), x=np.asarray(t_s, dtype=np.float64)))

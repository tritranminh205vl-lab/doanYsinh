"""Sóng lưu lượng mẫu dùng chung (Bài 14/16, VIE-02).

Đường cong chuẩn 5 nút: t = 0; 0.5; 1.0; 1.5; 2.0 s  ->  Q = 0; 2; 2; 1; 0 L/s
(nội suy tuyến tính, bằng 0 ngoài [0, 2] s). Kết quả chuẩn: PEF = 2.0 L/s,
V(1 s) = 1.5 L, V tổng = 2.5 L, tỷ số 60 %.
"""
from __future__ import annotations

import numpy as np

FIVE_NODES_T = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
FIVE_NODES_Q = np.array([0.0, 2.0, 2.0, 1.0, 0.0])


def five_node_q(t):
    """Q(t) (L/s) của đường cong chuẩn 5 nút tại các thời điểm t (s)."""
    t = np.asarray(t, dtype=np.float64)
    return np.interp(t, FIVE_NODES_T, FIVE_NODES_Q, left=0.0, right=0.0)

"""VIE-02 — Bài 16: tác động của offset lưu lượng lên thể tích tích phân.

ΔV = offset × T. Với offset 0.02 L/s: T = 2 s -> 0.040 L ; T = 6 s -> 0.120 L (> 0.050 L).
"""
from __future__ import annotations

import numpy as np

from _common import C, DIRS, plt, savefig, write_csv
from software.integrate import trapezoid_cumulative
from software.metrics import compute_metrics
from software.waveforms import five_node_q

FS = 500.0
OFFSETS = [0.005, 0.010, 0.020, 0.050]
DURATIONS = [2.0, 6.0]
ATS_LIMIT_L = 0.050


def main():
    rows = []
    # 1) chỉ số chuẩn của đường 5 nút
    t = np.arange(0, 2.0 + 1e-9, 1 / FS)
    q = five_node_q(t)
    v = trapezoid_cumulative(t, q)
    m = compute_metrics(t, q, v, q_start=0.01)
    base = {"PEF_lps": m.pef_lps, "V1s_L": m.v1s_onset_l, "Vtotal_L": m.fvc_l,
            "ratio_pct": 100 * m.v1s_onset_l / m.fvc_l}
    print("Đường 5 nút:", {k: round(v_, 4) for k, v_ in base.items()})

    # 2) quét offset × thời lượng tích phân
    for T in DURATIONS:
        t = np.arange(0, T + 1e-9, 1 / FS)
        q = five_node_q(t)
        v0 = trapezoid_cumulative(t, q)[-1]
        for off in OFFSETS:
            v1 = trapezoid_cumulative(t, q + off)[-1]
            dv = v1 - v0
            rows.append({"duration_s": T, "offset_lps": off, "dV_numeric_L": dv,
                         "dV_theory_L": off * T, "abs_diff_L": abs(dv - off * T),
                         "exceeds_ATS_50mL": dv > ATS_LIMIT_L})
    write_csv(DIRS["analysis"] / "offset_impact.csv", rows)
    lin = max(r["abs_diff_L"] for r in rows)
    print(f"Sai khác số học–lý thuyết lớn nhất: {lin:.2e} L (tuyến tính tuyệt đối)")

    # 3) đồ thị V(t) có / không offset trong 6 s
    t = np.arange(0, 6.0 + 1e-9, 1 / FS)
    q = five_node_q(t)
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    ax.plot(t, trapezoid_cumulative(t, q), color=C[0], label="Không offset")
    ax.plot(t, trapezoid_cumulative(t, q + 0.02), color=C[1], label="Offset +0.02 L/s")
    ax.set_ylim(0, 3.1)
    ax.annotate("+0.040 L tại 2 s", (2.0, 2.54), xytext=(2.4, 2.2), color="#5f5e5a",
                arrowprops=dict(arrowstyle="-", color="#5f5e5a", lw=0.6))
    ax.annotate("+0.120 L tại 6 s", (6.0, 2.62), xytext=(4.2, 2.9), color="#5f5e5a",
                arrowprops=dict(arrowstyle="-", color="#5f5e5a", lw=0.6))
    ax.set_xlabel("Thời gian (s)")
    ax.set_ylabel("Thể tích V (L)")
    ax.set_title("Bài 16 — offset lưu lượng tích lũy thành sai số thể tích", loc="left")
    ax.legend(loc="lower right")
    savefig(fig, "offset_impact.png")
    return {"baseline": base, "rows": rows}


if __name__ == "__main__":
    main()

"""VIE-06 — đặc tính 3 bộ lọc (4 phương án) và vị trí lọc -> reports/filter_characteristics.pdf

    python scripts/filter_characteristics.py

Nội dung (theo mục 7 và 9 của thẻ VIE-06):
  1. Đáp ứng tần số biên độ + trễ nhóm của MA N=5, Butterworth bậc 2 fc=15 Hz (lfilter / filtfilt),
     Savitzky–Golay N=11 bậc 2.
  2. Đáp ứng bước, sóng vuông 2 Hz và sóng bậc thang: đo trễ 50 %, thời gian lên 10–90 %, quá đà.
  3. Độ vát đỉnh PEF trên một nhịp thở gắng sức (lọc trên ΔP, đúng vị trí mặc định của pipeline).
  4. Vị trí lọc: lọc ΔP rồi khai căn so với khai căn rồi lọc Q, ở dòng thấp có nhiễu.
  5. Ranh giới Live / Offline.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from _common import C, DIRS, plt, savefig, write_csv
from _report import img_tag, page, sign_block, table, write_report
from software import filters as F
from software.config import load_config
from software.synth import A_TRUE, NOISE_PA, physio_q

CFG = load_config()
FS = float(CFG["sample_rate_hz"])
VARIANTS = [  # (nhãn, tên bộ lọc, chế độ, màu)
    ("MA N=5 (Live)", "moving_average", F.LIVE, C[0]),
    ("Butterworth lfilter (Live)", "butterworth", F.LIVE, C[1]),
    ("Butterworth filtfilt (Offline)", "butterworth", F.OFFLINE, C[2]),
    ("Savitzky–Golay (Offline)", "savgol", F.OFFLINE, C[3]),
]


def run(name, mode, x):
    return F.apply_filter(name, x, CFG, mode)


# ---- 1. miền tần số ------------------------------------------------------------------------
def freq_response():
    f = np.linspace(0.01, 0.995 * FS / 2, 4000)        # tránh điểm Nyquist (mẫu số Butterworth = 0)
    w = 2 * np.pi * f / FS
    b_ma = np.ones(int(CFG["ma_window"])) / int(CFG["ma_window"])
    b_bw, a_bw = F.butter_coeffs(FS, CFG["butter_fc_hz"], CFG["butter_order"])
    b_sg = signal.savgol_coeffs(int(CFG["savgol_window"]), int(CFG["savgol_polyorder"]))
    _, h_ma = signal.freqz(b_ma, 1, worN=w)
    _, h_bw = signal.freqz(b_bw, a_bw, worN=w)
    _, h_sg = signal.freqz(b_sg, 1, worN=w)
    h_ff = np.abs(h_bw) ** 2                                       # filtfilt = |H|², pha 0
    _, gd_bw = signal.group_delay((b_bw, a_bw), w=w)
    mags = {VARIANTS[0][0]: np.abs(h_ma), VARIANTS[1][0]: np.abs(h_bw),
            VARIANTS[2][0]: h_ff, VARIANTS[3][0]: np.abs(h_sg)}
    gds = {VARIANTS[0][0]: np.full_like(f, (len(b_ma) - 1) / 2 / FS * 1000),
           VARIANTS[1][0]: gd_bw / FS * 1000, VARIANTS[2][0]: np.zeros_like(f), VARIANTS[3][0]: np.zeros_like(f)}

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.8, 5.6), sharex=True, height_ratios=[3, 2])
    for (lab, *_ , col) in VARIANTS:
        a1.plot(f, 20 * np.log10(np.maximum(mags[lab], 1e-6)), color=col, label=lab)
        a2.plot(f, gds[lab], color=col)
    a1.axhline(-3, color="#5f5e5a", lw=0.7, ls=":")
    a1.axvline(15, color="#5f5e5a", lw=0.7, ls=":")
    a1.text(16, -55, "fc = 15 Hz", color="#5f5e5a", fontsize=8)
    a1.text(245, -1.5, "−3 dB", color="#5f5e5a", fontsize=8, ha="right", va="top")
    a1.set_ylim(-60, 5)
    a1.set_ylabel("Biên độ (dB)")
    a1.set_title("Đáp ứng tần số (Fs = 500 Hz, Nyquist 250 Hz)", loc="left")
    a1.legend(fontsize=8)
    a2.set_ylim(-1, 20)
    a2.set_xlim(0, FS / 2)
    a2.set_xlabel("Tần số (Hz)")
    a2.set_ylabel("Trễ nhóm (ms)")
    savefig(fig, "filter_freq_response.png")

    rows = []
    for lab in mags:
        m = mags[lab]
        f3 = float(f[np.argmax(m < 10 ** (-3 / 20))]) if np.any(m < 10 ** (-3 / 20)) else float("nan")
        rows.append({"variant": lab, "f_minus3dB_Hz": f3,
                     "gain_at_15Hz_dB": float(20 * np.log10(np.interp(15, f, m))),
                     "gain_at_50Hz_dB": float(20 * np.log10(max(np.interp(50, f, m), 1e-9))),
                     "group_delay_1Hz_ms": float(np.interp(1, f, gds[lab]))})
    return rows


# ---- 2. bước / sóng vuông / bậc thang ------------------------------------------------------
def edge_metrics(t, x, y, t_edge):
    """Đo trễ 50 %, thời gian lên 10–90 %, quá đà quanh một sườn lên 0 -> 1 tại t_edge.

    Sườn của tín hiệu rời rạc nằm giữa mẫu cuối = 0 và mẫu đầu = 1, tức tại t_edge − ½/Fs;
    đo trễ từ điểm đó thì MA N = 5 cho đúng (N − 1)/(2·Fs) = 4.0 ms.
    """
    w = (t >= t_edge - 0.05) & (t <= t_edge + 0.2)
    t_ref = t_edge - 0.5 / FS
    tt, yy = t[w], y[w]
    def cross(level):
        i = np.argmax(yy >= level)
        return tt[i - 1] + (level - yy[i - 1]) / (yy[i] - yy[i - 1]) / FS if i > 0 else tt[0]
    t10, t50, t90 = cross(0.1), cross(0.5), cross(0.9)
    return {"delay50_ms": (t50 - t_ref) * 1000, "rise_10_90_ms": (t90 - t10) * 1000,
            "overshoot_pct": max(0.0, (yy.max() - 1.0) * 100), "undershoot_pre_pct": max(0.0, -yy[tt < t_edge].min() * 100)}


def time_tests():
    t = np.arange(0, 2.0, 1 / FS)
    step = (t >= 0.5).astype(float)
    square = (np.sin(2 * np.pi * 2 * t - 1e-9) >= 0).astype(float)          # 2 Hz, sườn lên tại 0, 0.5, 1.0 ...
    stair = np.floor(np.clip((t - 0.2) / 0.4, 0, 3)) / 3                     # 4 bậc 0, 1/3, 2/3, 1
    rows = []
    fig, axs = plt.subplots(1, 3, figsize=(10.5, 3.3))
    for (lab, name, mode, col) in VARIANTS:
        ys = run(name, mode, step)
        yq = run(name, mode, square)
        yt = run(name, mode, stair)
        m = edge_metrics(t, step, ys, 0.5)
        mq = edge_metrics(t, square, yq, 1.0)
        rows.append({"variant": lab, **{k: round(float(v), 3) for k, v in m.items()},
                     "square_delay50_ms": round(float(mq["delay50_ms"]), 3)})
        z = (t > 0.45) & (t < 0.62)
        axs[0].plot((t[z] - 0.5) * 1000, ys[z], color=col, label=lab)
        z2 = (t > 0.8) & (t < 1.6)
        axs[1].plot(t[z2], yq[z2], color=col)
        axs[2].plot(t, yt, color=col)
    axs[0].plot((t[(t > 0.45) & (t < 0.62)] - 0.5) * 1000, step[(t > 0.45) & (t < 0.62)], color="#1f1f1e", lw=1, ls="--")
    axs[1].plot(t[(t > 0.8) & (t < 1.6)], square[(t > 0.8) & (t < 1.6)], color="#1f1f1e", lw=1, ls="--")
    axs[2].plot(t, stair, color="#1f1f1e", lw=1, ls="--", label="Tín hiệu vào")
    axs[0].set_title("Đáp ứng bước (zoom quanh sườn)", loc="left", fontsize=9)
    axs[0].set_xlabel("t − t_sườn (ms)")
    axs[1].set_title("Sóng vuông 2 Hz", loc="left", fontsize=9)
    axs[1].set_xlabel("t (s)")
    axs[2].set_title("Sóng bậc thang", loc="left", fontsize=9)
    axs[2].set_xlabel("t (s)")
    axs[0].legend(fontsize=6.5, loc="lower right")
    axs[2].legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    savefig(fig, "filter_step_square_stair.png")
    return rows


# ---- 3. độ vát đỉnh PEF -------------------------------------------------------------------
def pef_test():
    t = np.arange(0, 3.0, 1 / FS)
    q = physio_q(t - 0.3, 8.0, 0.05, 0.5)                     # PEF 8 L/s, lên đỉnh 50 ms (nhịp gắt nhất)
    dp = np.sign(q) * (q / A_TRUE) ** 2
    rows = []
    fig, ax = plt.subplots(figsize=(6.4, 3.3))
    z = (t > 0.28) & (t < 0.55)
    ax.plot((t[z] - 0.3) * 1000, q[z], color="#1f1f1e", lw=2, label="Q thật")
    for (lab, name, mode, col) in VARIANTS:
        qf = A_TRUE * np.sign(run(name, mode, dp)) * np.sqrt(np.abs(run(name, mode, dp)))
        i0, i1 = np.argmax(q), np.argmax(qf)
        rows.append({"variant": lab, "pef_true": float(q[i0]), "pef_filtered": float(qf[i1]),
                     "pef_error_pct": float((qf[i1] - q[i0]) / q[i0] * 100),
                     "peak_time_shift_ms": float((t[i1] - t[i0]) * 1000)})
        ax.plot((t[z] - 0.3) * 1000, qf[z], color=col, lw=1.3, label=lab)
    ax.set_xlabel("Thời gian từ lúc bắt đầu thở (ms)")
    ax.set_ylabel("Q (L/s)")
    ax.set_title("Độ vát đỉnh PEF — nhịp lên đỉnh trong 50 ms, lọc trên ΔP", loc="left")
    ax.legend(fontsize=7.5, loc="lower right")
    savefig(fig, "filter_pef_peak.png")
    return rows


# ---- 4. vị trí lọc ở dòng thấp có nhiễu -----------------------------------------------------
def placement_test(seed=42):
    rng = np.random.default_rng(seed)
    rows = []
    for dp_true in (2.0, 5.0, 10.0, 50.0, 200.0):
        n = rng.normal(0, NOISE_PA, 20000)
        x = dp_true + n
        q_true = A_TRUE * np.sqrt(dp_true)
        pre = F.apply_filter("butterworth", x, CFG, F.OFFLINE)
        q_pre = A_TRUE * np.sign(pre) * np.sqrt(np.abs(pre))
        q_raw = A_TRUE * np.sign(x) * np.sqrt(np.abs(x))
        q_post = F.apply_filter("butterworth", q_raw, CFG, F.OFFLINE)
        rows.append({"dp_true_Pa": dp_true, "q_true_Lps": float(q_true),
                     "bias_pre_model_pct": float((q_pre.mean() - q_true) / q_true * 100),
                     "bias_post_model_pct": float((q_post.mean() - q_true) / q_true * 100)})
    return rows


def main():
    fr = freq_response()
    tt = time_tests()
    pf = pef_test()
    pl = placement_test()
    write_csv(DIRS["analysis"] / "filter_characteristics.csv",
              [{**a, **b, **c} for a, b, c in zip(fr, tt, pf)])
    write_csv(DIRS["analysis"] / "filter_placement_bias.csv", pl)
    for a, b, c in zip(fr, tt, pf):
        print(f"{a['variant']:32s} -3dB={a['f_minus3dB_Hz']:5.1f} Hz  trễ50%={b['delay50_ms']:5.1f} ms  "
              f"lên={b['rise_10_90_ms']:5.1f} ms  quá đà={b['overshoot_pct']:4.1f} %  PEF={c['pef_error_pct']:+.2f} %")
    for r in pl:
        print(f"ΔP={r['dp_true_Pa']:5.0f} Pa  lệch lọc trước={r['bias_pre_model_pct']:+.2f} %  "
              f"lệch lọc sau={r['bias_post_model_pct']:+.2f} %")

    body = []
    body.append('<div class="box"><b>Kết luận.</b> Live dùng <b>MA N = 5</b> (trễ 4 ms, không quá đà); '
                "Offline dùng <b>Butterworth bậc 2, 15 Hz, filtfilt</b> (pha 0, cắt nhiễu tốt nhất trên 30 Hz). "
                "Savitzky–Golay giữ đỉnh tốt nhất nhưng cần mẫu tương lai, nên chỉ dùng Offline. "
                "Lọc đặt <b>trước</b> mô hình căn thức (lọc ΔP) vì ít lệch ở dòng thấp hơn.</div>")
    body.append("<h2>1. Đáp ứng tần số</h2>")
    body.append(img_tag("filter_freq_response.png", "Biên độ (trên) và trễ nhóm (dưới). filtfilt có biên độ |H|² và pha 0."))
    body.append(table(["Phương án", "f −3 dB (Hz)", "Tại 15 Hz (dB)", "Tại 50 Hz (dB)", "Trễ nhóm ở 1 Hz (ms)"],
                      [[r["variant"], f"{r['f_minus3dB_Hz']:.1f}", f"{r['gain_at_15Hz_dB']:.1f}",
                        f"{r['gain_at_50Hz_dB']:.1f}", f"{r['group_delay_1Hz_ms']:.2f}"] for r in fr]))
    body.append("<p>MA N = 5 có trễ nhóm hằng số (N − 1)/(2·Fs) = <b>4.0 ms</b> ở mọi tần số. "
                "MA có các búp phụ: không chặn sạch nhiễu cao tần như Butterworth.</p>")
    body.append("<h2>2. Đáp ứng bước, sóng vuông, bậc thang</h2>")
    body.append(img_tag("filter_step_square_stair.png", "Nét đứt: tín hiệu vào."))
    body.append(table(["Phương án", "Trễ 50 % (ms)", "Lên 10–90 % (ms)", "Quá đà (%)", "Gợn trước sườn (%)", "Trễ sóng vuông (ms)"],
                      [[r["variant"], f"{r['delay50_ms']:.1f}", f"{r['rise_10_90_ms']:.1f}", f"{r['overshoot_pct']:.1f}",
                        f"{r['undershoot_pre_pct']:.1f}", f"{r['square_delay50_ms']:.1f}"] for r in tt]))
    body.append("<p>Bộ lọc pha 0 (filtfilt, Savitzky–Golay) có trễ ≈ 0 nhưng phản hồi <i>trước</i> sườn "
                "(gợn trước sườn) — điều chỉ làm được khi đã có mẫu tương lai.</p>")
    body.append("<h2>3. Độ vát đỉnh PEF</h2>")
    body.append(img_tag("filter_pef_peak.png", "Nhịp gắng sức gắt nhất (lên đỉnh 50 ms), lọc trên ΔP rồi khai căn."))
    body.append(table(["Phương án", "PEF thật (L/s)", "PEF sau lọc (L/s)", "Sai số PEF (%)", "Lệch thời điểm đỉnh (ms)"],
                      [[r["variant"], f"{r['pef_true']:.3f}", f"{r['pef_filtered']:.3f}", f"{r['pef_error_pct']:+.2f}",
                        f"{r['peak_time_shift_ms']:+.0f}"] for r in pf]))
    body.append("<h2>4. Vị trí lọc: trước hay sau mô hình căn thức</h2>")
    body.append("<p>Cờ cấu hình <code>filter_placement</code>: <code>pre_model</code> lọc ΔP rồi tính Q = a·√ΔP; "
                "<code>post_model</code> tính Q rồi lọc Q. Thử với ΔP không đổi + nhiễu Gauss σ = "
                f"{NOISE_PA} Pa, Butterworth Offline, 20 000 mẫu:</p>")
    body.append(table(["ΔP thật (Pa)", "Q thật (L/s)", "Lệch lọc trước (%)", "Lệch lọc sau (%)"],
                      [[f"{r['dp_true_Pa']:.0f}", f"{r['q_true_Lps']:.3f}", f"{r['bias_pre_model_pct']:+.2f}",
                        f"{r['bias_post_model_pct']:+.2f}"] for r in pl]))
    body.append("<p>Hàm căn lõm nên E[√(ΔP + n)] &lt; √ΔP: khai căn trên tín hiệu còn nhiễu rồi mới lọc sẽ lệch âm "
                "ở dòng thấp. Lọc trước mô hình giảm nhiễu trước khi khai căn nên lệch nhỏ hơn. "
                "Trên 120 phiên mô phỏng (VIE-08), lọc sau mô hình làm FVC lệch âm thêm khoảng 2 %.</p>")
    body.append("<h2>5. Ranh giới Live / Offline</h2>")
    body.append(table(["Bộ lọc", "Live (hiển thị thời gian thực)", "Offline (sau khi bấm Dừng)", "Cài đặt"],
                      [["MA N = 5", "✔ mặc định", "✔", "lfilter nhân quả"],
                       ["Butterworth bậc 2, 15 Hz", "✔ (lfilter, có trễ pha)", "✔ mặc định (filtfilt)", "chọn theo tham số mode"],
                       ["Savitzky–Golay 11/2", "✘ ném NonCausalInLiveModeError", "✔", "cửa sổ đối xứng"]]))
    body.append(sign_block("VIE-06"))
    write_report(page("Đặc tính bộ lọc số và vị trí lọc", "Smart Spirometer · VIE-06 · Nguyễn Hoàng Việt · "
                      "Tín hiệu thử: sóng chuẩn + mô phỏng (không phải số đo thật)", "".join(body)),
                 "filter_characteristics")


if __name__ == "__main__":
    main()

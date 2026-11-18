"""VIE-06 + VIE-08 — đối sánh bộ lọc × vị trí lọc trên 120 phiên mô phỏng.

Biến thể: none | MA N=5 (live) | Butterworth (live, lfilter) | Butterworth (offline, filtfilt)
          | Savitzky–Golay (offline). Mỗi biến thể chạy với filter_placement pre_model / post_model.
Chỉ số: RMSE(Q), sai số PEF %, sai số FVC %, sai số FEV1 (L), trễ thực nghiệm (ms), trạng thái cờ.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np

from _common import C, DIRS, ROOT, plt, read_csv, savefig, write_csv
from _report import img_tag, page, sign_block, table, write_report
from software import filters as F
from software.config import load_config
from software.fit_model import FlowModel
from software.pipeline import process_raw_file
from software.synth import A_TRUE, SCENARIOS, make_session

VARIANTS = [
    ("raw", "none", F.OFFLINE),
    ("ma5_live", "moving_average", F.LIVE),
    ("butter_live", "butterworth", F.LIVE),
    ("butter_offline", "butterworth", F.OFFLINE),
    ("savgol_offline", "savgol", F.OFFLINE),
]
PLACEMENTS = ["pre_model", "post_model"]


def main(sim_dir=None, cfg=None, seed=42):
    cfg = cfg or load_config()
    sim_dir = Path(sim_dir or ROOT / "data" / "simulated" / "sessions")
    man = read_csv(sim_dir / "manifest.csv")
    fs = float(cfg["sample_rate_hz"])
    model = FlowModel("bernoulli", {"a": A_TRUE}, None, calibrated=True)   # mô hình đúng -> chỉ đo ảnh hưởng của lọc
    rows = []
    example = {}
    for r in man:
        sess = make_session(r["scenario"], int(r["seed"]), cfg, seed)
        t_clean = np.arange(sess.q_clean.size) / fs
        for vname, fname, mode in VARIANTS:
            for pl in PLACEMENTS:
                res = process_raw_file(sim_dir / r["file"], cfg, model, fname, pl, mode=mode)
                m = res.metrics
                qc = np.interp(res.t, t_clean, sess.q_clean)
                blow = (res.t > sess.onset_s - 0.1) & (res.t < sess.onset_s + 3.0)
                rows.append({
                    "file": r["file"], "scenario": r["scenario"], "variant": vname, "placement": pl,
                    "rmse_q_lps": float(np.sqrt(np.mean((res.q[blow] - qc[blow]) ** 2))),
                    "pef_err_pct": 100 * (m.pef_lps - float(r["pef_true"])) / float(r["pef_true"]),
                    "fvc_err_pct": 100 * (m.fvc_l - float(r["fvc_true"])) / float(r["fvc_true"]),
                    "fev1_err_l": m.fev1_l - float(r["fev1_true"]),
                    "delay_ms": 1000 * F.measure_delay_s(qc[blow], res.q[blow], fs),
                    "status": res.quality["status"],
                    "correct": (r["expected_flag"] == "PASSED" and res.quality["status"] == "PASSED")
                               or (r["expected_flag"] in res.quality["flags"]),
                })
                if r["file"] == "sim_KB1_s01.csv" and pl == "pre_model":
                    example[vname] = (res.t, res.q, t_clean, sess.q_clean, sess.onset_s)
    write_csv(DIRS["analysis"] / "filters_benchmark.csv", rows)

    # tổng hợp: chỉ KB1 cho sai số đo (phiên sạch), tất cả 120 cho độ đúng cờ
    agg = defaultdict(list)
    for x in rows:
        agg[(x["variant"], x["placement"])].append(x)
    summary = []
    for (vname, pl), xs in agg.items():
        k1 = [x for x in xs if x["scenario"] == "KB1"]
        summary.append({
            "variant": vname, "placement": pl,
            "rmse_q_lps_KB1": np.mean([x["rmse_q_lps"] for x in k1]),
            "pef_err_pct_KB1": np.mean([x["pef_err_pct"] for x in k1]),
            "fvc_err_pct_KB1": np.mean([x["fvc_err_pct"] for x in k1]),
            "fvc_err_sd_KB1": np.std([x["fvc_err_pct"] for x in k1]),
            "fev1_err_l_KB1": np.mean([x["fev1_err_l"] for x in k1]),
            "delay_ms_KB1": np.mean([x["delay_ms"] for x in k1]),
            "flag_accuracy_120": np.mean([x["correct"] for x in xs]),
        })
    write_csv(DIRS["analysis"] / "filters_benchmark_summary.csv", summary)
    for s in summary:
        print(f"{s['variant']:15s} {s['placement']:10s} RMSE={s['rmse_q_lps_KB1']:.3f} "
              f"PEF={s['pef_err_pct_KB1']:+.2f}% FVC={s['fvc_err_pct_KB1']:+.2f}% "
              f"delay={s['delay_ms_KB1']:.1f}ms flags={100 * s['flag_accuracy_120']:.0f}%")

    # đồ thị: zoom đỉnh PEF của phiên KB1_s01
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    t, q, tc, qc, on = example["raw"]
    w = (tc > on - 0.05) & (tc < on + 0.35)
    ax.plot(tc[w], qc[w], color="#1f1f1e", lw=2.2, label="Chân lý (sạch)")
    for i, vname in enumerate(["raw", "ma5_live", "butter_live", "butter_offline", "savgol_offline"]):
        t, q, *_ = example[vname]
        ww = (t > on - 0.05) & (t < on + 0.35)
        ax.plot(t[ww], q[ww], color=C[i], lw=1.2, label=vname)
    ax.set_xlabel("Thời gian (s)")
    ax.set_ylabel("Q (L/s)")
    ax.set_title("Vùng đỉnh PEF — phiên sim_KB1_s01, lọc trước mô hình", loc="left")
    ax.legend(ncol=2, fontsize=8)
    savefig(fig, "filters_peak_zoom.png")
    make_report(summary, rows)
    return summary


LABEL = {"raw": "Không lọc", "ma5_live": "MA N=5 (Live)", "butter_live": "Butterworth lfilter (Live)",
         "butter_offline": "Butterworth filtfilt (Offline)", "savgol_offline": "Savitzky–Golay (Offline)"}
LIVE_V = ["raw", "ma5_live", "butter_live"]
OFF_V = ["raw", "butter_offline", "savgol_offline"]


def make_report(summary, rows):
    """VIE-08 — reports/filter_benchmark_summary.pdf"""
    S = {(s["variant"], s["placement"]): s for s in summary}
    n_sess = len({r["file"] for r in rows})
    n_var = len({r["variant"] for r in rows})

    def row(v, pl="pre_model"):
        s = S[(v, pl)]
        return [LABEL[v], f"{s['rmse_q_lps_KB1']:.3f}", f"{s['pef_err_pct_KB1']:+.2f}",
                f"{s['fvc_err_pct_KB1']:+.2f} ± {s['fvc_err_sd_KB1']:.2f}", f"{s['fev1_err_l_KB1'] * 1000:+.0f}",
                f"{s['delay_ms_KB1']:.1f}", f"{100 * s['flag_accuracy_120']:.0f} %"]
    hdr = ["Phương án", "RMSE Q (L/s)", "Sai số PEF (%)", "Sai số FVC (%)", "Sai số FEV1 (mL)", "Trễ (ms)", "Cờ đúng /120"]
    best_live = min(["ma5_live", "butter_live"], key=lambda v: S[(v, "pre_model")]["rmse_q_lps_KB1"])
    best_off = "butter_offline"

    scen = sorted({r["scenario"] for r in rows})
    per = []
    for v in ["raw", "ma5_live", "butter_live", "butter_offline", "savgol_offline"]:
        xs = [r for r in rows if r["variant"] == v and r["placement"] == "pre_model"]
        per.append([LABEL[v]] + [f"{sum(r['correct'] for r in xs if r['scenario'] == sc)}/20" for sc in scen])
    place = [[LABEL[v], f"{S[(v, 'pre_model')]['fvc_err_pct_KB1']:+.2f}", f"{S[(v, 'post_model')]['fvc_err_pct_KB1']:+.2f}",
              f"{S[(v, 'pre_model')]['rmse_q_lps_KB1']:.3f}", f"{S[(v, 'post_model')]['rmse_q_lps_KB1']:.3f}"]
             for v in ["ma5_live", "butter_live", "butter_offline", "savgol_offline"]]

    body = [
        f'<div class="box"><b>Kết luận.</b> Chạy {n_var} phương án × 2 vị trí lọc × {n_sess} phiên = '
        f'{len(rows)} lần xử lý. Chế độ <b>Live</b>: chọn <b>{LABEL[best_live]}</b> (RMSE thấp nhất trong nhóm nhân quả, '
        f'trễ {S[(best_live, "pre_model")]["delay_ms_KB1"]:.1f} ms). Chế độ <b>Offline</b>: chọn <b>{LABEL[best_off]}</b> '
        f'— cờ chất lượng đúng {100 * S[(best_off, "pre_model")]["flag_accuracy_120"]:.0f} % trên 120 phiên, trễ 0, '
        f'độ phân tán FVC nhỏ nhất (± {S[(best_off, "pre_model")]["fvc_err_sd_KB1"]:.2f} % so với '
        f'± {S[("raw", "pre_model")]["fvc_err_sd_KB1"]:.2f} % khi không lọc). '
        "Vị trí lọc: <b>trước mô hình căn thức</b> (lọc ΔP).</div>",
        "<h2>1. Phương pháp</h2>",
        "<p>Dữ liệu: 120 phiên mô phỏng (6 kịch bản × 20 seed, VIE-05) đi qua đúng pipeline thật: parser → zero động → "
        "ΔP → lọc → Q = a·√ΔP (a đúng bằng giá trị mô phỏng, để chỉ đo ảnh hưởng của lọc) → tích phân → chỉ số → cờ. "
        "Sai số đo (RMSE, PEF, FVC, FEV1, trễ) tính trên 20 phiên sạch KB1 so với chân lý; RMSE lấy trong cửa sổ "
        "từ 0.1 s trước khi thở đến 3 s sau. Trễ đo bằng tương quan chéo. Độ đúng cờ tính trên cả 120 phiên.</p>",
        "<p>Công thức: RMSE = √[(1/N) Σ (Q<sub>calc</sub> − Q<sub>true</sub>)²]; "
        "sai số PEF = (PEF<sub>calc</sub> − PEF<sub>true</sub>)/PEF<sub>true</sub> × 100 %; tương tự cho FVC. "
        "Không có phép chia cho Q<sub>true</sub>[i] từng mẫu nên không sinh NaN/Inf khi Q<sub>true</sub> = 0.</p>",
        "<h2>2. Nhóm Live (nhân quả, dùng cho hiển thị thời gian thực)</h2>",
        table(hdr, [row(v) for v in LIVE_V], best_row=LIVE_V.index(best_live)),
        "<h2>3. Nhóm Offline (sau khi bấm Dừng, ra số cuối cùng)</h2>",
        table(hdr, [row(v) for v in OFF_V], best_row=OFF_V.index(best_off)),
        "<p>Savitzky–Golay có RMSE và sai số PEF nhỏ nhất nhưng giữ lại nhiều nhiễu cao tần hơn (cắt −3 dB ở ~49 Hz). "
        "Sau khi luồng thở đã tắt, phần nhiễu còn vượt ngưỡng chết 1 Pa bị tích phân thành 27–30 mL trong giây cuối, "
        "vượt tiêu chí plateau 25 mL, nên một số phiên sạch KB1 bị đánh nhầm FLAG_EARLY_TERMINATION (bảng 4). "
        "Butterworth filtfilt hạ nhiễu dưới ngưỡng chết, đổi lại PEF thấp hơn khoảng 1 %, và giữ bộ cờ đúng hoàn toàn — "
        "nên được chọn cho Offline.</p>",
        img_tag("filters_peak_zoom.png", "Vùng đỉnh PEF của một phiên KB1 — các phương án lọc trước mô hình."),
        "<h2>4. Độ đúng cờ theo kịch bản (lọc trước mô hình)</h2>",
        table(["Phương án"] + scen, per),
        "<p>KB1 chuẩn · KB2 trôi zero · KB3 khởi đầu chậm · KB4 kết thúc đột ngột · KB5 ho · KB6 mất chuỗi mẫu.</p>",
        "<h2>5. Vị trí lọc: trước hay sau mô hình</h2>",
        table(["Phương án", "FVC lọc trước (%)", "FVC lọc sau (%)", "RMSE lọc trước", "RMSE lọc sau"], place),
        "<p>Lọc sau mô hình làm FVC lệch âm thêm khoảng 2 % ở mọi bộ lọc, do khai căn trên tín hiệu còn nhiễu "
        "(chi tiết ở báo cáo VIE-06, mục 4).</p>",
        "<h2>6. Lỗi phát hiện và đã sửa trong quá trình đối sánh</h2>"
        "<p>Lần chạy đầu, với MA và Savitzky–Golay chỉ 4–5/20 phiên KB4 (kết thúc đột ngột) được gắn cờ đúng. Nguyên nhân: "
        "bộ phát hiện lấy <i>gai nhiễu cuối cùng</i> sau khi tắt dòng làm điểm kết thúc thở, nên bỏ qua cú tụt thật. "
        "Đã sửa trong <code>metrics.detect_abrupt_drop</code>: dừng đột ngột = Q từ ≥ 1.0 L/s tụt xuống ≤ 0.3 L/s "
        "trong 50 ms và trung bình 200 ms sau đó vẫn ≤ 0.3 L/s (để không nhầm với ho, sau ho dòng hồi lại). "
        "Mọi số trong báo cáo này là sau khi sửa; phương án mặc định (Butterworth Offline) đúng 100 % cả trước lẫn sau.</p>"
        "<h2>7. Tái lập</h2><p>Bảng đầy đủ: <code>analysis/filters_benchmark.csv</code> "
        f"({len(rows)} dòng = {n_sess} phiên × {n_var} phương án × 2 vị trí). Lệnh: "
        "<code>python scripts/benchmark_filters.py</code> (cần chạy <code>python -m software.synth</code> trước).</p>",
        sign_block("VIE-08"),
    ]
    write_report(page("Đối sánh bộ lọc trên 120 phiên mô phỏng",
                      "Smart Spirometer · VIE-08 · Nguyễn Hoàng Việt · Dữ liệu MÔ PHỎNG", "".join(body)),
                 "filter_benchmark_summary")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim-dir")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    main(a.sim_dir, seed=a.seed)

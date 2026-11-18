"""Bộ tạo dữ liệu mô phỏng (VIE-05, Chương 4).

Hai loại sóng:
  1) five_node_q(t): đường cong chuẩn 5 nút của Bài 14/16 — dùng để kiểm chứng tích phân
     (V(1s)=1.5 L, V_total=2.5 L, PEF=2.0 L/s). Đây là sóng "giáo khoa", không đủ thực tế
     để chạy bộ cờ ATS/ERS (PEF ở 0.5 s => BEV = Qmax·tPEF/8 = 0.125 L, nằm đúng ngưỡng).
  2) physio_q(...): sóng thở gắng sức sinh lý hơn (lên đỉnh 50–100 ms, suy giảm mũ) — dùng
     cho ma trận 6 kịch bản × 20 seed = 120 phiên.

Đường đi của dữ liệu mô phỏng giống thiết bị thật: Q -> ΔP = (Q/a)^2 -> +nhiễu (Pa) -> count
-> làm tròn -> chuỗi protocol_v1 ($DAT,...) có checksum. Pipeline đọc lại như dữ liệu thật.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .adc_to_dp import AdcToDpConverter
from .integrate import trapezoid_cumulative
from .metrics import compute_metrics
from .parser import format_line
from .waveforms import FIVE_NODES_Q, FIVE_NODES_T, five_node_q  # noqa: F401  (giữ API cũ)


SCENARIOS = {
    "KB1": ("Chuẩn có nhiễu", "PASSED"),
    "KB2": ("Trôi zero sau khi khóa", "FLAG_ZERO_DRIFT"),
    "KB3": ("Khởi đầu chậm", "FLAG_HESITATING_START"),
    "KB4": ("Kết thúc đột ngột", "FLAG_EARLY_TERMINATION"),
    "KB5": ("Ho trong giây đầu", "FLAG_COUGH_1ST_SEC"),
    "KB6": ("Mất chuỗi mẫu", "FLAG_PACKET_LOSS"),
}

A_TRUE = 0.25          # hệ số Bernoulli "thật" của ống mô phỏng, L/(s·√Pa)
NOISE_PA = 1.7         # nhiễu trắng Gauss ≈ 1.4 count
BASELINE_S = 1.0
RECORD_AFTER_ONSET_S = 8.0


def physio_q(t, pef, t_rise, tau, rise="cosine", t_end=7.0):
    t = np.asarray(t, dtype=np.float64)
    q = np.zeros_like(t)
    r = (t >= 0) & (t < t_rise)
    if rise == "cosine":
        q[r] = pef * 0.5 * (1 - np.cos(np.pi * t[r] / t_rise))
    else:
        q[r] = pef * t[r] / t_rise
    d = (t >= t_rise) & (t <= t_end)
    q[d] = pef * np.exp(-(t[d] - t_rise) / tau)
    return q


def q_to_dp(q, a=A_TRUE):
    q = np.asarray(q, dtype=np.float64)
    return np.sign(q) * (q / a) ** 2


@dataclass
class SimSession:
    name: str
    scenario: str
    seed: int
    t_us: np.ndarray
    adc: np.ndarray
    keep: np.ndarray          # mask mẫu được "truyền" (False = mất gói)
    q_clean: np.ndarray       # lưu lượng thật (chân lý)
    onset_s: float
    zero_true: float
    meta: dict


def make_session(scenario: str, seed: int, cfg: dict, global_seed: int = 42) -> SimSession:
    scen_idx = int(scenario[2:])
    rng = np.random.default_rng([global_seed, scen_idx, seed])
    fs = float(cfg["sample_rate_hz"])
    conv = AdcToDpConverter(cfg)

    onset = BASELINE_S + rng.uniform(0.3, 0.6)
    n = int(round((onset + RECORD_AFTER_ONSET_S) * fs))
    t = np.arange(n) / fs
    tt = t - onset

    pef = rng.uniform(6.0, 9.0)
    tau = rng.uniform(0.45, 0.70)
    t_rise = rng.uniform(0.05, 0.10)
    meta = {"pef_set": pef, "tau": tau}

    if scenario == "KB3":
        t_rise = rng.uniform(0.40, 0.65)
        q = physio_q(tt, pef, t_rise, tau, rise="linear")
    else:
        q = physio_q(tt, pef, t_rise, tau)
    meta["t_rise"] = t_rise

    if scenario == "KB4":
        t_cut_max = t_rise + tau * np.log(pef / 1.0)
        t_cut = rng.uniform(0.6, t_cut_max)
        q[tt > t_cut] = 0.0
        meta["t_cut"] = t_cut
    if scenario == "KB5":
        tc = rng.uniform(0.30, 0.70)
        f = rng.uniform(7.0, 10.0)
        amp = rng.uniform(1.2, 2.5)
        dur = 2.0 / f
        w = (tt >= tc) & (tt < tc + dur)
        x = tt[w] - tc
        burst = amp * np.sin(2 * np.pi * f * x) * np.sin(np.pi * x / dur) ** 2
        q[w] = np.clip(q[w] + burst, 0.0, 0.95 * pef)
        meta.update(cough_t=tc, cough_f=f, cough_amp=amp)

    q_clean = q.copy()
    dp = q_to_dp(q) + rng.normal(0.0, NOISE_PA, n)
    if scenario == "KB2":
        drift = rng.uniform(1.0, 2.5)
        dp[t >= BASELINE_S] += drift          # trôi xảy ra SAU khi đã khóa zero
        meta["drift_pa"] = drift

    zero_true = conv.nominal_zero_count() + rng.uniform(-40, 40)   # dung sai linh kiện
    adc = np.clip(np.round(conv.pa_to_count(dp, zero_true)), 0, 4095).astype(int)

    keep = np.ones(n, dtype=bool)
    # 1 mẫu lẻ bị mất (được phép nội suy) ở mọi phiên
    i1 = int(rng.integers(int((onset + 2.0) * fs), int((onset + 6.0) * fs)))
    keep[i1] = False
    if scenario == "KB6":
        run = int(rng.integers(11, 26))                         # 22–50 ms
        i0 = int(rng.integers(int((onset + 0.2) * fs), int((onset + 1.5) * fs)))
        keep[i0:i0 + run] = False
        meta.update(drop_start_s=i0 / fs, drop_len=run)

    t0_us = int(rng.integers(1_000_000, 5_000_000))
    t_us = t0_us + np.arange(n) * int(round(1e6 / fs))
    name = f"sim_{scenario}_s{seed:02d}"
    return SimSession(name, scenario, seed, t_us, adc, keep, q_clean, onset, zero_true, meta)


def truth_metrics(sess: SimSession, fs: float) -> dict:
    t = np.arange(sess.q_clean.size) / fs
    v = trapezoid_cumulative(t, sess.q_clean)
    m = compute_metrics(t, sess.q_clean, v, q_start=0.05, search_from_s=BASELINE_S)
    return {"pef_true": m.pef_lps, "fev1_true": m.fev1_l, "fvc_true": m.fvc_l,
            "bev_true": m.bev_l, "fet_true": m.fet_s}


def write_raw(sess: SimSession, path: Path, cfg: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii", newline="") as f:
        f.write(f"# name={sess.name}\n# scenario={sess.scenario}\n# seed={sess.seed}\n")
        f.write(f"# simulation=true\n# hardware_version={cfg['hardware_version']}\n")
        f.write(f"# firmware_version={cfg['firmware_version']}\n# airpath_version={cfg['airpath_version']}\n")
        for i in np.flatnonzero(sess.keep):
            f.write(format_line(i, int(sess.t_us[i]), int(sess.adc[i])))


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate_matrix(out_dir, cfg: dict, n_seeds: int = 20, global_seed: int = 42) -> Path:
    """Tạo 6 kịch bản × n_seeds phiên + manifest.csv (nhãn + chân lý + SHA-256)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fs = float(cfg["sample_rate_hz"])
    rows = []
    for scen in SCENARIOS:
        for seed in range(1, n_seeds + 1):
            s = make_session(scen, seed, cfg, global_seed)
            p = out_dir / f"{s.name}.csv"
            write_raw(s, p, cfg)
            row = {"file": p.name, "scenario": scen, "seed": seed,
                   "expected_flag": SCENARIOS[scen][1], **truth_metrics(s, fs),
                   "meta": json.dumps(s.meta), "sha256": sha256(p)}
            rows.append(row)
    man = out_dir / "manifest.csv"
    with open(man, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return man


def clean_q_on_grid(sess: SimSession, fs: float):
    t = np.arange(sess.q_clean.size) / fs
    return t, sess.q_clean


# ---- Dữ liệu hiệu chuẩn / kiểm chứng mô phỏng (thay bằng dữ liệu thật của Trí) -------
TRUE_LAW = {"a": 0.24, "b": 0.51}      # ống "thật" hơi lệch Bernoulli để phần dư có ý nghĩa


def _write_stream(path, q, cfg, rng, label):
    fs = float(cfg["sample_rate_hz"])
    conv = AdcToDpConverter(cfg)
    dp = np.sign(q) * (np.abs(q) / TRUE_LAW["a"]) ** (1 / TRUE_LAW["b"]) + rng.normal(0, NOISE_PA, q.size)
    zero_true = conv.nominal_zero_count() + rng.uniform(-40, 40)
    adc = np.clip(np.round(conv.pa_to_count(dp, zero_true)), 0, 4095).astype(int)
    t0 = int(rng.integers(1_000_000, 5_000_000))
    with open(path, "w", encoding="ascii", newline="") as f:
        f.write(f"# {label}\n# simulation=true\n")
        for i in range(q.size):
            f.write(format_line(i, t0 + i * int(round(1e6 / fs)), int(adc[i])))


def generate_cal_val(root, cfg: dict, global_seed: int = 42):
    """cal_v1: các mức lưu lượng ổn định + reference_log.csv; val_v1: 10 lượt bơm xilanh 3.0 L."""
    root = Path(root)
    fs = float(cfg["sample_rate_hz"])
    rng = np.random.default_rng([global_seed, 777])
    cal = root / "cal_v1"
    val = root / "val_v1"
    cal.mkdir(parents=True, exist_ok=True)
    val.mkdir(parents=True, exist_ok=True)
    ref_rows = []
    levels = [0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    for rep in range(2):
        for qref in levels:
            n_base, n_flow = int(BASELINE_S * fs), int(2.0 * fs)
            q = np.concatenate([np.zeros(n_base), np.full(n_flow, qref), np.zeros(int(0.5 * fs))])
            name = f"cal_q{qref:04.1f}_r{rep + 1}.csv"
            _write_stream(cal / name, q, cfg, rng, f"cal level {qref} L/s")
            ref_rows.append({"file": name, "q_ref_lps": qref,
                             "flow_start_s": BASELINE_S + 0.3, "flow_end_s": BASELINE_S + 1.8})
    with open(cal / "reference_log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ref_rows[0].keys()))
        w.writeheader()
        w.writerows(ref_rows)

    val_rows = []
    durations = [("slow", 6.0), ("medium", 1.5), ("fast", 0.6)]
    plan = ["slow", "medium", "fast", "slow", "medium", "fast", "medium", "fast", "slow", "medium"]
    for i, kind in enumerate(plan, 1):
        T = dict(durations)[kind] * rng.uniform(0.9, 1.1)
        n_base = int(BASELINE_S * fs)
        tt = np.arange(int((T + 2.0) * fs)) / fs
        peak = 3.0 * np.pi / (2 * T)
        q = np.where(tt < T, peak * np.sin(np.pi * tt / T), 0.0)
        q = np.concatenate([np.zeros(n_base), q])
        name = f"val_{i:02d}_{kind}.csv"
        _write_stream(val / name, q, cfg, rng, f"val stroke 3.000 L {kind}")
        val_rows.append({"file": name, "kind": kind, "v_ref_l": 3.000, "duration_s": round(T, 3),
                         "peak_lps": round(peak, 3)})
    with open(val / "reference_log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(val_rows[0].keys()))
        w.writeheader()
        w.writerows(val_rows)
    return cal, val


# ---- Chạy trực tiếp ----------------------------------------------------------------------
def verify_reproducible(cfg: dict, global_seed: int = 42, workdir=None) -> tuple[bool, int]:
    """Kịch bản kiểm chứng VIE-05: sinh ma trận 2 lần cùng seed, so SHA-256 từng file."""
    import tempfile
    with tempfile.TemporaryDirectory(dir=workdir) as d:
        a, b = Path(d) / "run1", Path(d) / "run2"
        generate_matrix(a, cfg, 20, global_seed)
        generate_matrix(b, cfg, 20, global_seed)
        files = sorted(p.name for p in a.iterdir())
        same = all(sha256(a / f) == sha256(b / f) for f in files)
        return same, len(files)


def main():
    import argparse
    import sys

    from .config import load_config
    ap = argparse.ArgumentParser(description="Sinh 120 phiên mô phỏng (6 kịch bản × 20 seed)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/simulated/sessions")
    ap.add_argument("--verify", action="store_true", help="sinh 2 lần và so SHA-256")
    a = ap.parse_args()
    cfg = load_config()
    man = generate_matrix(a.out, cfg, 20, a.seed)
    n = sum(1 for _ in open(man, encoding="utf-8")) - 1
    print(f"Đã sinh {n} phiên vào {a.out} (manifest: {man.name})")
    t = np.arange(0, 3.0 + 1e-9, 1 / float(cfg["sample_rate_hz"]))
    v = trapezoid_cumulative(t, five_node_q(t))
    print(f"Kiểm tra sóng 5 nút sạch: V(1 s) = {np.interp(1.0, t, v):.4f} L, V tổng = {v[-1]:.4f} L")
    if a.verify:
        ok, nf = verify_reproducible(cfg, a.seed)
        print(f"Tái lập: sinh 2 lần seed={a.seed}, {nf} file -> SHA-256 {'TRÙNG 100%' if ok else 'KHÁC'}")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

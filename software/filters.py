"""Bộ lọc số và ranh giới Live/Offline (VIE-06, Chương 5).

  none            y[n] = x[n]                                 Live/Offline, trễ 0
  moving_average  y[n] = (1/N) Σ_{k=0..N-1} x[n-k]            Live, trễ nhóm (N-1)/(2Fs) = 4 ms (N=5)
  butterworth     IIR bậc 2, fc = 15 Hz                       Live: lfilter (nhân quả, có trễ pha)
                                                              Offline: filtfilt (pha 0)
  savgol          Savitzky–Golay N=11, bậc 2, cửa sổ đối xứng  CHỈ Offline (cần mẫu tương lai)
"""
from __future__ import annotations

import numpy as np
from scipy import signal

LIVE, OFFLINE = "live", "offline"
FILTER_NAMES = ("none", "moving_average", "butterworth", "savgol")


class NonCausalInLiveModeError(RuntimeError):
    """Gọi bộ lọc phi nhân quả (filtfilt / Savitzky–Golay) trong chế độ Live."""


def moving_average(x, n: int = 5):
    x = np.asarray(x, dtype=np.float64)
    if n <= 1 or x.size == 0:
        return x.copy()
    b = np.ones(n) / n
    zi = signal.lfilter_zi(b, [1.0]) * x[0]          # khởi tạo tránh quá độ đầu
    y, _ = signal.lfilter(b, [1.0], x, zi=zi)
    return y


def ma_group_delay_s(n: int, fs: float) -> float:
    return (n - 1) / (2.0 * fs)


def butter_coeffs(fs: float, fc: float = 15.0, order: int = 2):
    return signal.butter(order, fc, btype="low", fs=fs)


def butterworth(x, fs: float, fc: float = 15.0, order: int = 2, mode: str = LIVE):
    x = np.asarray(x, dtype=np.float64)
    b, a = butter_coeffs(fs, fc, order)
    if mode == LIVE:
        zi = signal.lfilter_zi(b, a) * x[0]
        y, _ = signal.lfilter(b, a, x, zi=zi)
        return y
    if x.size <= 3 * max(len(a), len(b)):
        return x.copy()                       # quá ngắn để lọc hai chiều
    return signal.filtfilt(b, a, x)


def savgol(x, window: int = 11, polyorder: int = 2, mode: str = OFFLINE):
    if mode == LIVE:
        raise NonCausalInLiveModeError("Savitzky–Golay đối xứng cần mẫu tương lai: cấm dùng cho Live Display")
    x = np.asarray(x, dtype=np.float64)
    if x.size < window:
        return x.copy()
    return signal.savgol_filter(x, window, polyorder)


def apply_filter(name: str, x, cfg: dict, mode: str = OFFLINE):
    """Gọi bộ lọc theo tên và tham số trong config."""
    fs = float(cfg["sample_rate_hz"])
    if name == "none":
        return np.asarray(x, dtype=np.float64).copy()
    if name == "moving_average":
        return moving_average(x, int(cfg.get("ma_window", 5)))
    if name == "butterworth":
        return butterworth(x, fs, float(cfg.get("butter_fc_hz", 15.0)),
                           int(cfg.get("butter_order", 2)), mode)
    if name == "savgol":
        return savgol(x, int(cfg.get("savgol_window", 11)), int(cfg.get("savgol_polyorder", 2)), mode)
    raise ValueError(f"Bộ lọc không hỗ trợ: {name}")


def measure_delay_s(y_true, y_filt, fs: float, max_lag_s: float = 0.05) -> float:
    """Ước lượng trễ thực nghiệm bằng tương quan chéo (dương = bộ lọc trễ sau)."""
    a = np.asarray(y_true, dtype=np.float64) - np.mean(y_true)
    b = np.asarray(y_filt, dtype=np.float64) - np.mean(y_filt)
    max_lag = int(max_lag_s * fs)
    lags = np.arange(-max_lag, max_lag + 1)
    best, best_val = 0, -np.inf
    for L in lags:
        if L >= 0:
            v = np.dot(a[: a.size - L], b[L:])
        else:
            v = np.dot(a[-L:], b[: b.size + L])
        if v > best_val:
            best, best_val = L, v
    return best / fs

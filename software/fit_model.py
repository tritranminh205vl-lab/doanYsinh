"""Mô hình lưu lượng Q(ΔP) và fit hiệu chuẩn (VIE-12, VIE-14, Chương 6).

Ứng viên:
  bernoulli : Q = a · sign(ΔP) · √|ΔP|          a [L/(s·√Pa)]
  power     : Q = a · sign(ΔP) · |ΔP|^b
  linear    : Q = c · ΔP                         c [L/(s·Pa)]

Nguyên tắc: chỉ fit trên cal_v1; val_v1 không được mở khi fit; không ngoại suy ngoài dải đã đo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit


def q_bernoulli(dp, a):
    dp = np.asarray(dp, dtype=np.float64)
    return a * np.sign(dp) * np.sqrt(np.abs(dp))


def q_power(dp, a, b):
    dp = np.asarray(dp, dtype=np.float64)
    return a * np.sign(dp) * np.abs(dp) ** b


def q_linear(dp, c):
    return c * np.asarray(dp, dtype=np.float64)


MODELS = {
    "bernoulli": (q_bernoulli, ["a"], [0.1], "L/(s*sqrt(Pa))"),
    "power": (q_power, ["a", "b"], [0.1, 0.5], "a: L/(s*Pa^b), b: -"),
    "linear": (q_linear, ["c"], [0.001], "L/(s*Pa)"),
}


@dataclass
class FitResult:
    model: str
    params: dict
    stderr: dict
    r2: float
    rmse_lps: float
    n_points: int
    residuals: np.ndarray = field(repr=False)


def fit(model: str, dp, q) -> FitResult:
    f, names, p0, _ = MODELS[model]
    dp = np.asarray(dp, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    popt, pcov = curve_fit(f, dp, q, p0=p0, maxfev=10000)   # Levenberg–Marquardt
    q_fit = f(dp, *popt)
    res = q - q_fit
    ss_res = float(np.sum(res ** 2))
    ss_tot = float(np.sum((q - q.mean()) ** 2))
    perr = np.sqrt(np.diag(pcov))
    return FitResult(
        model=model,
        params={n: float(v) for n, v in zip(names, popt)},
        stderr={n: float(v) for n, v in zip(names, perr)},
        r2=1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan,
        rmse_lps=float(np.sqrt(np.mean(res ** 2))),
        n_points=int(dp.size),
        residuals=res,
    )


def fit_all(dp, q) -> dict[str, FitResult]:
    return {m: fit(m, dp, q) for m in MODELS}


def save_model_json(path, result: FitResult, dp_range, q_range, cal_files, calibration_id,
                    direction="expiratory", extra=None):
    doc = {
        "calibration_id": calibration_id,
        "model": result.model,
        "equation": {"bernoulli": "Q = a*sign(dP)*sqrt(|dP|)",
                     "power": "Q = a*sign(dP)*|dP|^b",
                     "linear": "Q = c*dP"}[result.model],
        "params": result.params,
        "params_stderr": result.stderr,
        "units": {"Q": "L/s", "dP": "Pa", "params": MODELS[result.model][3]},
        "valid_range": {"dp_pa": [float(dp_range[0]), float(dp_range[1])],
                        "q_lps": [float(q_range[0]), float(q_range[1])]},
        "direction": direction,
        "fit_quality": {"r2": result.r2, "rmse_lps": result.rmse_lps, "n_points": result.n_points},
        "cal_files": [str(f) for f in cal_files],
    }
    if extra:
        doc.update(extra)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc


class FlowModel:
    """Áp dụng mô hình đã hiệu chuẩn. Đánh dấu (không âm thầm ngoại suy) khi vượt dải."""

    def __init__(self, model: str = "bernoulli", params: dict | None = None,
                 dp_range=None, calibrated: bool = False, calibration_id=None):
        self.model = model
        self.params = params or {"a": 0.25}
        self.dp_range = dp_range
        self.calibrated = calibrated
        self.calibration_id = calibration_id

    @classmethod
    def from_json(cls, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["model"], d["params"], d["valid_range"]["dp_pa"], True, d.get("calibration_id"))

    @classmethod
    def load_or_uncalibrated(cls, path, a_default: float = 0.25):
        p = Path(path)
        if p.exists():
            return cls.from_json(p)
        return cls("bernoulli", {"a": a_default}, None, calibrated=False)

    def __call__(self, dp, deadband_pa: float = 0.0):
        f = MODELS[self.model][0]
        dp = np.asarray(dp, dtype=np.float64)
        q = f(dp, *self.params.values())
        if deadband_pa > 0:
            q = np.where(np.abs(dp) < deadband_pa, 0.0, q)
        return q

    def out_of_range_fraction(self, dp) -> float:
        if not self.dp_range:
            return 0.0
        dp = np.abs(np.asarray(dp, dtype=np.float64))
        return float(np.mean(dp > self.dp_range[1] * 1.0))

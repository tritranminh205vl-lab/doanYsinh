"""Ghép toàn bộ chuỗi xử lý (Hình 1.1):
raw -> parser -> zero động -> ADC→ΔP -> chính sách mất mẫu -> [lọc] -> Q -> [lọc] -> V -> chỉ số -> cờ
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import filters as F
from .adc_to_dp import AdcToDpConverter, ZeroCalibrationError
from .fit_model import FlowModel
from .integrate import trapezoid_cumulative
from .metrics import Metrics, compute_metrics
from .parser import apply_drop_policy, parse_file
from .quality_flags import evaluate


@dataclass
class PipelineResult:
    ok: bool
    reason: str = ""
    t: np.ndarray = field(default=None, repr=False)
    adc: np.ndarray = field(default=None, repr=False)
    dp: np.ndarray = field(default=None, repr=False)
    q: np.ndarray = field(default=None, repr=False)
    v: np.ndarray = field(default=None, repr=False)
    segment: np.ndarray = field(default=None, repr=False)
    zero_adc: float = float("nan")
    zero_std: float = float("nan")
    n_parse_errors: int = 0
    n_dropped: int = 0
    n_interpolated: int = 0
    invalid_gaps: list = field(default_factory=list)
    metrics: Metrics | None = None
    quality: dict = field(default_factory=dict)
    filter_name: str = ""
    placement: str = ""


def _filter_segments(name, x, seg, cfg, mode):
    out = np.empty_like(x)
    for s in np.unique(seg):
        m = seg == s
        out[m] = F.apply_filter(name, x[m], cfg, mode) if m.sum() > 12 else x[m]
    return out


def dp_to_q(dp, seg, cfg, model: FlowModel, filter_name: str, placement: str, mode=F.OFFLINE):
    db = float(cfg.get("dp_deadband_pa", 0.0))
    if placement == "pre_model":
        dp_f = _filter_segments(filter_name, dp, seg, cfg, mode)
        return model(dp_f, deadband_pa=db)
    q = _filter_segments(filter_name, model(dp), seg, cfg, mode)
    if db > 0:
        q_thr = float(model(np.array([db]))[0])
        q = np.where(np.abs(q) < q_thr, 0.0, q)
    return q


def process_samples(t_s, adc, cfg, model: FlowModel, filter_name=None, placement=None,
                    mode=F.OFFLINE, n_parse_errors=0, n_dropped=0) -> PipelineResult:
    filter_name = filter_name or cfg.get("filter_offline", "butterworth")
    placement = placement or cfg.get("filter_placement", "pre_model")
    fs = float(cfg["sample_rate_hz"])
    conv = AdcToDpConverter(cfg)
    try:
        z = conv.compute_zero(adc)
    except ZeroCalibrationError as e:
        return PipelineResult(ok=False, reason=str(e), n_parse_errors=n_parse_errors)
    dp_raw = conv.convert_count_to_pa(adc, z.zero_adc)
    t, dp, seg, gap = apply_drop_policy(t_s, dp_raw, fs, cfg.get("interp_max_gap_s", 0.0045),
                                        cfg.get("invalid_gap_s", 0.010))
    q = dp_to_q(dp, seg, cfg, model, filter_name, placement, mode)
    v = trapezoid_cumulative(t, q, seg)
    zero_dur = z.n_samples / fs
    m = compute_metrics(t, q, v, search_from_s=zero_dur)
    qual = evaluate(t, q, dp, m, fs, gap.invalid, model.calibrated)
    return PipelineResult(
        ok=True, t=t, adc=np.asarray(adc), dp=dp, q=q, v=v, segment=seg,
        zero_adc=z.zero_adc, zero_std=z.std_count, n_parse_errors=n_parse_errors,
        n_dropped=n_dropped, n_interpolated=gap.n_interpolated, invalid_gaps=gap.invalid_gaps,
        metrics=m, quality=qual, filter_name=filter_name, placement=placement,
    )


def process_raw_file(path, cfg, model: FlowModel, filter_name=None, placement=None,
                     errors_log: str | Path | None = None, mode=F.OFFLINE) -> PipelineResult:
    sp = parse_file(path)
    if errors_log:
        sp.write_errors(errors_log)
    sess = max(sp.sessions, key=len)
    if len(sess) == 0:
        return PipelineResult(ok=False, reason="Không có gói hợp lệ", n_parse_errors=len(sp.errors))
    return process_samples(sess.t_s, sess.adc_array, cfg, model, filter_name, placement, mode=mode,
                           n_parse_errors=len(sp.errors), n_dropped=sess.dropped)

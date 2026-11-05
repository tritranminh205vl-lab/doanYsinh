"""Quy đổi ADC count -> Vadc -> Vout -> ΔP (Pa) và bù zero động (VIE-03, Chương 2).

Chuỗi quy đổi:
    Vadc = count * Vref / divisor          (divisor = 4095 theo quy ước nhóm)
    Vout = Vadc / k                        (k = divider_ratio_measured hoặc 2/3)
    P_kPa = (Vout/Vs - offset) / sens      (cảm biến: Vout = Vs*(sens*P + offset))
    P_Pa  = 1000 * P_kPa

Bù zero động: dùng zero_adc đo trước mỗi phiên thay cho 'offset' danh định.
    P_Pa = 1000 * (count - zero_adc) * Vref / divisor / k / Vs / sens
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import effective_divider, effective_vs


class ZeroCalibrationError(RuntimeError):
    """Baseline quá rung (σ > ngưỡng) — không được khóa zero."""


@dataclass
class ZeroResult:
    """Kết quả bù zero: count trung bình, độ lệch chuẩn (count), số mẫu đã dùng."""

    zero_adc: float
    std_count: float
    n_samples: int


class AdcToDpConverter:
    """Quy đổi ADC count sang chênh áp ΔP (Pa). Mọi tham số đọc từ config, không hardcode.

    Args (trong cfg):
        vref_v: điện áp tham chiếu ADC (V).
        adc_divisor: 4095 hoặc 4096 — quy ước mẫu số ADC 12 bit.
        divider_ratio / divider_ratio_measured: tỷ số cầu phân áp k (ưu tiên số đo của Nhung).
        vs_nominal_v / vs_measured_v: điện áp nuôi cảm biến Vs (ưu tiên số đo).
        sensor_offset_frac, sensor_sens_per_kpa: hàm truyền Vout = Vs·(sens·P_kPa + offset).
        zero_samples, zero_max_std_count: số mẫu và ngưỡng σ cho bù zero động.

    Mọi phép tính ép kiểu float64 để tránh chia số nguyên / tràn int16.
    """

    def __init__(self, cfg: dict):
        self.vref = float(cfg["vref_v"])
        self.divisor = float(cfg.get("adc_divisor", 4095))
        self.k = effective_divider(cfg)
        self.vs = effective_vs(cfg)
        self.offset = float(cfg["sensor_offset_frac"])
        self.sens = float(cfg["sensor_sens_per_kpa"])
        self.max_std = float(cfg.get("zero_max_std_count", 5.0))
        self.n_zero = int(cfg.get("zero_samples", 500))

    # ---- chuỗi danh định (không bù zero) -------------------------------------------
    def count_to_vadc(self, count):
        """ADC count -> điện áp tại chân ADC (V): Vadc = count · Vref / divisor."""
        return np.asarray(count, dtype=np.float64) * self.vref / self.divisor

    def vadc_to_vout(self, vadc):
        """Điện áp chân ADC -> điện áp ngõ ra cảm biến (V): Vout = Vadc / k."""
        return np.asarray(vadc, dtype=np.float64) / self.k

    def vout_to_pa(self, vout):
        """Vout (V) -> ΔP (Pa) theo hàm truyền danh định: P = 1000·(Vout/Vs − offset)/sens."""
        return 1000.0 * (np.asarray(vout, dtype=np.float64) / self.vs - self.offset) / self.sens

    def count_to_pa_nominal(self, count):
        """count -> Pa dùng offset danh định của datasheet (không bù zero). Ví dụ 2234 -> 200.44 Pa."""
        return self.vout_to_pa(self.vadc_to_vout(self.count_to_vadc(count)))

    # ---- có bù zero động -----------------------------------------------------------
    @property
    def pa_per_count(self) -> float:
        """Độ phân giải áp suất của 1 count (≈1.209 Pa với cấu hình danh định)."""
        return 1000.0 * self.vref / self.divisor / self.k / self.vs / self.sens

    def convert_count_to_pa(self, count, zero_adc: float | None = None):
        """count -> Pa. Nếu có zero_adc thì trừ offset động, ngược lại dùng offset danh định."""
        if zero_adc is None:
            return self.count_to_pa_nominal(count)
        return (np.asarray(count, dtype=np.float64) - float(zero_adc)) * self.pa_per_count

    def pa_to_count(self, pa, zero_adc: float | None = None):
        """Hàm ngược (dùng cho bộ mô phỏng). Trả về float, chưa làm tròn."""
        pa = np.asarray(pa, dtype=np.float64)
        if zero_adc is None:
            vout = self.vs * (self.sens * pa / 1000.0 + self.offset)
            return vout * self.k * self.divisor / self.vref
        return pa / self.pa_per_count + float(zero_adc)

    def nominal_zero_count(self) -> float:
        """Count lý thuyết khi ΔP = 0 (≈2068, KHÔNG phải 2048)."""
        return float(self.pa_to_count(0.0))

    def compute_zero(self, counts) -> ZeroResult:
        """Bù zero động: lấy n_zero mẫu đầu (1 s @ 500 Hz) khi ống kín gió."""
        c = np.asarray(counts, dtype=np.float64)[: self.n_zero]
        if c.size < self.n_zero:
            raise ZeroCalibrationError(f"Chỉ có {c.size} mẫu, cần {self.n_zero} mẫu baseline")
        mu, sd = float(c.mean()), float(c.std(ddof=1))
        if sd > self.max_std:
            raise ZeroCalibrationError(
                f"σ_zero = {sd:.2f} count > {self.max_std} count: rung gió/cảm biến chưa ổn định nhiệt"
            )
        return ZeroResult(zero_adc=mu, std_count=sd, n_samples=int(c.size))

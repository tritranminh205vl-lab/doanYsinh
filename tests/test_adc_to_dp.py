"""Unit test VIE-03: quy đổi ADC count -> ΔP và bù zero động."""
import numpy as np
import pytest

from software.adc_to_dp import AdcToDpConverter, ZeroCalibrationError


def make(cfg, **kw):
    c = dict(cfg)
    c.update(divider_ratio=2 / 3, **kw)
    return AdcToDpConverter(c)


def test_benchmark_2234(cfg):
    # 2234 × 3.3 = 7372.2 ; 7372.2 / 4095 = 1.8002930 V (sổ tay ghi nhầm 1.80024420 V và 200.37 Pa)
    conv = make(cfg)
    assert conv.count_to_vadc(2234) == pytest.approx(1.80029304, abs=1e-8)
    assert conv.vadc_to_vout(conv.count_to_vadc(2234)) == pytest.approx(2.70043956, abs=1e-8)
    assert conv.count_to_pa_nominal(2234) == pytest.approx(200.44, abs=0.01)


def test_4096_convention(cfg):
    conv = make(cfg, adc_divisor=4096)
    assert conv.count_to_pa_nominal(2234) == pytest.approx(199.78, abs=0.01)   # sổ tay ghi 199.71


@pytest.mark.parametrize("count", [0, 2048, 4095])
def test_boundaries_finite(cfg, count):
    v = make(cfg).count_to_pa_nominal(count)
    assert np.isfinite(v)


def test_boundary_values(cfg):
    conv = make(cfg)
    assert conv.count_to_pa_nominal(0) == pytest.approx(-2500.0, abs=1e-6)   # Vout=0 -> -2.5 kPa
    assert conv.count_to_pa_nominal(2048) < 0                               # 2048 KHÔNG phải zero
    assert conv.nominal_zero_count() == pytest.approx(2068.2, abs=0.1)  # 2.5 V·(2/3) -> 2068 count


def test_integer_input_no_int_division(cfg):
    conv = make(cfg)
    assert conv.count_to_pa_nominal(np.int16(2234)) == pytest.approx(200.44, abs=0.01)


def test_dynamic_zero(cfg):
    conv = make(cfg)
    rng = np.random.default_rng(0)
    base = np.round(2075 + rng.normal(0, 1.4, 500))
    z = conv.compute_zero(base)
    assert z.zero_adc == pytest.approx(2075, abs=0.3)
    assert conv.convert_count_to_pa(z.zero_adc, z.zero_adc) == 0.0


def test_zero_rejects_vibration(cfg):
    conv = make(cfg)
    rng = np.random.default_rng(0)
    with pytest.raises(ZeroCalibrationError):
        conv.compute_zero(2068 + rng.normal(0, 10, 500))


def test_roundtrip(cfg):
    conv = make(cfg)
    pa = np.array([-500.0, 0.0, 123.4, 1500.0])
    assert np.allclose(conv.convert_count_to_pa(conv.pa_to_count(pa, 2070), 2070), pa)

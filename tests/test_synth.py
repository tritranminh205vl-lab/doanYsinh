"""Unit test VIE-05: bộ sinh 120 phiên mô phỏng có nhãn."""
import csv

import numpy as np
import pytest

from software.integrate import trapezoid_cumulative
from software.synth import (SCENARIOS, generate_matrix, make_session, sha256, verify_reproducible,
                            write_raw)
from software.waveforms import five_node_q


def test_clean_five_node_volumes():
    # Tiêu chí nghiệm thu: tích phân đường chuẩn sạch V(1 s) = 1.5 L, V tổng = 2.5 L
    t = np.arange(0, 3.0 + 1e-9, 1 / 500)
    v = trapezoid_cumulative(t, five_node_q(t))
    assert np.interp(1.0, t, v) == pytest.approx(1.5, abs=1e-9)
    assert v[-1] == pytest.approx(2.5, abs=1e-9)


def test_matrix_120_sessions_with_labels(tmp_path, cfg):
    man = generate_matrix(tmp_path, cfg, 20, 42)
    rows = list(csv.DictReader(open(man, encoding="utf-8")))
    assert len(rows) == 120
    assert len(list(tmp_path.glob("sim_*.csv"))) == 120
    for scen, (_, flag) in SCENARIOS.items():
        sub = [r for r in rows if r["scenario"] == scen]
        assert len(sub) == 20
        assert all(r["expected_flag"] == flag for r in sub)
    for r in rows:
        assert sha256(tmp_path / r["file"]) == r["sha256"]


@pytest.mark.parametrize("seed", [1, 7, 20])
def test_faults_really_injected(cfg, seed):
    fs = 500
    assert make_session("KB2", seed, cfg).meta["drift_pa"] >= 1.0               # trôi zero
    assert make_session("KB3", seed, cfg).meta["t_rise"] >= 0.40                # khởi đầu chậm
    s4 = make_session("KB4", seed, cfg)                                         # kết thúc đột ngột
    assert s4.q_clean[int((s4.onset_s + s4.meta["t_cut"]) * fs) + 2] == 0.0
    assert "cough_t" in make_session("KB5", seed, cfg).meta                    # ho
    s6 = make_session("KB6", seed, cfg)                                         # mất chuỗi ≥ 22 ms
    assert s6.meta["drop_len"] >= 11 and (~s6.keep).sum() >= 12
    s1 = make_session("KB1", seed, cfg)                                         # phiên chuẩn: chỉ 1 mẫu lẻ mất
    assert (~s1.keep).sum() == 1


def test_reproducible_sha(tmp_path, cfg):
    a = make_session("KB5", 3, cfg, 42)
    b = make_session("KB5", 3, cfg, 42)
    write_raw(a, tmp_path / "a.csv", cfg)
    write_raw(b, tmp_path / "b.csv", cfg)
    assert sha256(tmp_path / "a.csv") == sha256(tmp_path / "b.csv")


def test_full_matrix_reproducible(tmp_path, cfg):
    ok, n = verify_reproducible(cfg, 42, workdir=tmp_path)
    assert ok and n == 121          # 120 phiên + manifest.csv


def test_different_seed_differs(tmp_path, cfg):
    write_raw(make_session("KB1", 1, cfg), tmp_path / "a.csv", cfg)
    write_raw(make_session("KB1", 2, cfg), tmp_path / "b.csv", cfg)
    assert sha256(tmp_path / "a.csv") != sha256(tmp_path / "b.csv")

"""Unit test VIE-04: parser protocol_v1, quản lý lỗi và chính sách mất mẫu."""
import random

import numpy as np
import pytest

from software.parser import (BAD_FORMAT, CORRUPTED, MCU_RESET, SEQ_DROP, SEQ_DUP, SEQ_OOO,
                             TRUNCATED, TS_DISC, TS_MOD, TS_WRAP, StreamParser, apply_drop_policy,
                             format_line, parse_file, parse_line, xor_checksum)
from software.parser_testset import EXPECTED, EXPECTED_SESSION_LENGTHS, write_testset


# ---- từng dòng --------------------------------------------------------------------------
def test_checksum_example():
    # Sổ tay ghi chk=74, nhưng XOR thực của "DAT,105,210000,2234" là 0x4D
    assert xor_checksum("DAT,105,210000,2234") == 0x4D
    assert format_line(105, 210000, 2234) == "$DAT,105,210000,2234,4D*\r\n"


def test_parse_valid_and_lowercase_hex():
    p = parse_line(format_line(1, 2000, 2100))
    assert (p.seq, p.t_us, p.adc) == (1, 2000, 2100)
    assert parse_line("$DAT,105,210000,2234,4d*\n").adc == 2234       # hex thường, chỉ \n


@pytest.mark.parametrize("line, code", [
    ("$DAT,105,210000,2234,74*\r\n", CORRUPTED),       # ví dụ trong sổ tay
    ("$DAT,105,2100", TRUNCATED),                      # cắt cụt
    ("garbage��", TRUNCATED),                # rác
    ("", TRUNCATED),
    ("$DAT,1,2,3*", BAD_FORMAT),                       # thiếu trường
    ("$DAT,1,2,3,4,5,00*", BAD_FORMAT),                # thừa trường (2 gói dính nhau)
    ("$DAT,-1,2,3,00*", BAD_FORMAT),                   # số âm
    ("$DAT,1,2,4096,00*", BAD_FORMAT),                 # adc ngoài 12 bit
    ("$DAT,70000,2,3,00*", BAD_FORMAT),                # seq ngoài uint16
    ("$DAT,1,2,3,ZZ*", BAD_FORMAT),                    # chk không phải hex
    ("$DAT,１,2,3,00*", BAD_FORMAT),               # chữ số Unicode toàn khổ
])
def test_bad_lines(line, code):
    assert parse_line(line)[0] == code


# ---- kịch bản sổ tay: đếm lỗi đúng 100% ------------------------------------------------
def test_handbook_scenario_counts_exact(tmp_path):
    sp = parse_file(write_testset(tmp_path / "t.csv"))
    summ = sp.summary()
    for k, v in EXPECTED.items():
        assert summ[k] == v, k
    assert [len(s) for s in sp.sessions if len(s)] == EXPECTED_SESSION_LENGTHS


def test_wrap_keeps_time_axis_continuous(tmp_path):
    sp = parse_file(write_testset(tmp_path / "t.csv"))
    t = np.asarray(sp.sessions[0].t_us_unwrapped, dtype=np.int64)
    d = np.diff(t)
    assert np.all(d > 0)                                # đơn điệu tăng qua điểm tràn 2^32
    assert set(np.unique(d)) <= {2000, 4000, 10000}     # chỉ 2 ms, hoặc khoảng trống do mất mẫu


def test_errors_log_written_with_summary(tmp_path):
    sp = parse_file(write_testset(tmp_path / "t.csv"))
    log = tmp_path / "errors.log"
    sp.write_errors(log, source="t.csv")
    txt = log.read_text(encoding="utf-8")
    assert "line 102: TRUNCATED_LINE" in txt            # số dòng thật trong file
    assert "# samples_lost = 6" in txt


# ---- các tình huống thứ tự / thời gian --------------------------------------------------
def feed_all(lines):
    sp = StreamParser()
    for ln in lines:
        sp.feed(ln)
    return sp


def test_seq_wrap_65535_to_0_is_not_reset():
    lines = [format_line(s % 65536, 1_000_000 + 2000 * i, 2068) for i, s in enumerate(range(65530, 65545))]
    sp = feed_all(lines)
    assert sp.errors == [] and len(sp.sessions) == 1


def test_seq_backwards_is_dropped_not_counted_as_loss():
    lines = [format_line(s, 2000 * s, 2068) for s in (10, 11, 12, 11, 13)]
    sp = feed_all(lines)
    assert [e.code for e in sp.errors] == [SEQ_OOO]
    assert sp.summary()["samples_lost"] == 0


def test_t_us_back_to_zero_with_seq_continuing_opens_new_session():
    lines = [format_line(s, 100_000 + 2000 * s, 2068) for s in range(50, 60)]
    lines += [format_line(s, 2000 * (s - 60), 2068) for s in range(60, 70)]
    sp = feed_all(lines)
    assert [e.code for e in sp.errors] == [TS_DISC]
    assert [len(s) for s in sp.sessions] == [10, 10]


def test_true_wrap_adds_2_pow_32():
    lines = [format_line(s, (TS_MOD - 4000 + 2000 * s) % TS_MOD, 2068) for s in range(5)]
    sp = feed_all(lines)
    assert [e.code for e in sp.errors] == [TS_WRAP]
    assert sp.sessions[0].t_us_unwrapped[-1] == TS_MOD + 4000


def test_mcu_reset():
    lines = [format_line(s, 500_000 + 2000 * s, 2068) for s in range(100, 110)]
    lines += [format_line(s, 3000 + 2000 * s, 2068) for s in range(0, 5)]
    sp = feed_all(lines)
    assert [e.code for e in sp.errors] == [MCU_RESET]
    assert len(sp.sessions) == 2


def test_duplicate_and_drop():
    lines = [format_line(s, 2000 * s, 2068) for s in (1, 2, 2, 3, 9)]
    sp = feed_all(lines)
    assert [e.code for e in sp.errors] == [SEQ_DUP, SEQ_DROP]
    assert sp.summary()["samples_lost"] == 5


# ---- không crash với dữ liệu rác ngẫu nhiên ---------------------------------------------
def test_fuzz_never_crashes():
    rng = random.Random(42)
    alphabet = "$DAT,0123456789abcdefXYZ*\r\n\x00\xffé-+ "
    sp = StreamParser()
    for _ in range(5000):
        n = rng.randint(0, 40)
        sp.feed("".join(rng.choice(alphabet) for _ in range(n)))
        if rng.random() < 0.3:
            sp.feed(format_line(rng.randint(0, 65535), rng.randint(0, TS_MOD - 1), rng.randint(0, 4095)))
    assert sp.n_lines > 5000


def test_binary_garbage_file(tmp_path):
    f = tmp_path / "g.csv"
    f.write_bytes(bytes(range(256)) * 20 + format_line(1, 2000, 2068).encode())
    sp = parse_file(f)
    assert sp.n_valid == 1


# ---- chính sách mất mẫu -----------------------------------------------------------------
def test_drop_policy_interpolates_single_and_flags_long_gap():
    fs = 500.0
    t = np.arange(100) / fs
    x = np.arange(100, dtype=float)
    keep = np.ones(100, bool)
    keep[10] = False                 # mất 1 mẫu (4 ms) -> nội suy
    keep[50:61] = False              # mất 11 mẫu (24 ms) -> INVALID
    t2, x2, seg, rep = apply_drop_policy(t[keep], x[keep], fs)
    assert rep.n_interpolated == 1
    assert np.isclose(x2[10], 10.0)
    assert rep.invalid and len(rep.invalid_gaps) == 1
    assert seg.max() == 1

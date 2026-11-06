"""Bộ dữ liệu kiểm thử parser theo kịch bản sổ tay VIE-04 (mục 9), có đáp án sẵn.

Luồng 500 Hz (Δt = 2000 µs), bắt đầu ngay trước điểm tràn t_us để có một lần tràn thật:
  Phiên 1: seq 0–999, t_us bắt đầu tại 2^32 − 1 500 000 -> tràn ở seq 750
      seq 100 : dòng bị cắt cụt                     -> TRUNCATED_LINE (+ mất 1 mẫu)
      seq 200 : sai checksum                        -> CORRUPTED_PACKET (+ mất 1 mẫu)
      seq 299 -> 304 : seq nhảy cóc 5 đơn vị        -> SEQ_DROP, mất 4 mẫu
      sau seq 400 : gửi lặp lại gói 400             -> SEQ_DUPLICATE
      sau seq 500 : một dòng rác nhị phân           -> TRUNCATED_LINE
      sau seq 550 : một dòng sai định dạng          -> BAD_FORMAT
      seq 600 : adc = 4095                          -> ADC_SATURATED (gói vẫn giữ)
  Phiên 2: seq 1000–1199, t_us lùi về 0 trong khi seq vẫn chạy -> TS_DISCONTINUITY
  Phiên 3: MCU reset, seq 0–299, t_us bắt đầu 5000           -> NEW_SESSION_MCU_RESET
"""
from __future__ import annotations

from pathlib import Path

from .parser import (ADC_SAT, BAD_FORMAT, CORRUPTED, MCU_RESET, SEQ_DROP, SEQ_DUP, SEQ_OOO,
                     TRUNCATED, TS_DISC, TS_MOD, TS_WRAP, format_line)

DT_US = 2000
T0_US = TS_MOD - 1_500_000

EXPECTED = {
    "lines_total": 1499,
    "packets_valid": 1494,
    "lines_rejected": 4,
    TRUNCATED: 2,
    BAD_FORMAT: 1,
    CORRUPTED: 1,
    SEQ_DROP: 3,
    SEQ_DUP: 1,
    SEQ_OOO: 0,
    TS_WRAP: 1,
    TS_DISC: 1,
    MCU_RESET: 1,
    ADC_SAT: 1,
    "samples_lost": 6,
    "sessions": 3,
}
EXPECTED_SESSION_LENGTHS = [994, 200, 300]


def _adc(seq: int) -> int:
    """Giá trị ADC giả quanh mức zero 2068, có dao động nhẹ cho dễ nhìn."""
    return 2068 + (seq * 7) % 23 - 11


def build_lines() -> list[bytes]:
    """Trả về danh sách dòng (dạng bytes, đúng như nhận từ UART)."""
    out: list[bytes] = []

    def add(s: str):
        out.append(s.encode("ascii"))

    # Phiên 1
    for seq in range(0, 1000):
        t = (T0_US + seq * DT_US) % TS_MOD
        adc = 4095 if seq == 600 else _adc(seq)
        line = format_line(seq, t, adc)
        if 300 <= seq <= 303:
            continue                                         # seq nhảy cóc 299 -> 304
        if seq == 100:
            add(line[:15] + "\r\n")                          # cắt cụt, mất '*'
            continue
        if seq == 200:
            body, chk = line.rsplit(",", 1)
            bad = f"{(int(chk[:2], 16) ^ 0x5A):02X}"
            add(f"{body},{bad}*\r\n")                        # sai checksum
            continue
        add(line)
        if seq == 400:
            add(line)                                        # gói lặp
        if seq == 500:
            out.append(b"\x00\xff\xfe\x13garbage@@!!\r\n")   # rác nhị phân
        if seq == 550:
            add("$DAT,551,xx,2068,00*\r\n")                  # sai định dạng
    # Phiên 2: t_us lùi về 0, seq vẫn tăng
    for k, seq in enumerate(range(1000, 1200)):
        add(format_line(seq, k * DT_US, _adc(seq)))
    # Phiên 3: MCU reset
    for seq in range(0, 300):
        add(format_line(seq, 5000 + seq * DT_US, _adc(seq)))
    return out


def write_testset(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"# parser_testset.csv - bo kiem thu VIE-04 co chen loi co y (xem software/parser_testset.py)\n")
        for b in build_lines():
            f.write(b)
    return path

"""VIE-04 — chạy parser, xuất logs/errors.log và bảng đối chiếu số lỗi.

    python scripts/parser_demo.py                                  # bộ kiểm thử có chèn lỗi cố ý
    python scripts/parser_demo.py --file data/sample/sample_stream.csv   # file thật của Quang

Xuất:
  data/sample/parser_testset.csv   bộ kiểm thử (chỉ khi không có --file)
  logs/errors.log                  từng lỗi theo số dòng + bảng tổng kết
  analysis/parser_summary.csv      kỳ vọng / đếm được / ĐẠT (với bộ kiểm thử)
Kèm đo tốc độ parser (dòng/giây) để chứng minh không làm tắc luồng UART 500 dòng/s.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from _common import DIRS, ROOT, write_csv
from software.parser import format_line, parse_file, StreamParser
from software.parser_testset import EXPECTED, EXPECTED_SESSION_LENGTHS, write_testset


def benchmark(n=200_000):
    lines = [format_line(i, 1000 + 2000 * i, 2068) for i in range(n)]
    sp = StreamParser()
    t0 = time.perf_counter()
    for ln in lines:
        sp.feed(ln)
    dt = time.perf_counter() - t0
    return n / dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="file raw cần phân tích (mặc định: bộ kiểm thử có chèn lỗi)")
    a = ap.parse_args()

    if a.file:
        path = Path(a.file)
        path = path if path.is_absolute() else ROOT / path
    else:
        path = write_testset(ROOT / "data" / "sample" / "parser_testset.csv")

    sp = parse_file(path)
    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    sp.write_errors(DIRS["logs"] / "errors.log", source=str(rel).replace("\\", "/"))
    summ = sp.summary()

    print(f"Nguồn: {rel}")
    if a.file:
        for k, v in summ.items():
            print(f"  {k:24s} {v}")
        write_csv(DIRS["analysis"] / "parser_summary.csv",
                  [{"item": k, "counted": v} for k, v in summ.items()])
    else:
        rows, ok_all = [], True
        for k, exp in EXPECTED.items():
            got = summ[k]
            ok = got == exp
            ok_all &= ok
            rows.append({"item": k, "expected": exp, "counted": got, "pass": "ĐẠT" if ok else "SAI"})
            print(f"  {k:24s} kỳ vọng {exp:5d}   đếm được {got:5d}   {'ĐẠT' if ok else 'SAI'}")
        lens = [len(s) for s in sp.sessions if len(s)]
        ok = lens == EXPECTED_SESSION_LENGTHS
        ok_all &= ok
        rows.append({"item": "session_lengths", "expected": str(EXPECTED_SESSION_LENGTHS),
                     "counted": str(lens), "pass": "ĐẠT" if ok else "SAI"})
        print(f"  {'session_lengths':24s} kỳ vọng {EXPECTED_SESSION_LENGTHS}   đếm được {lens}   {'ĐẠT' if ok else 'SAI'}")
        write_csv(DIRS["analysis"] / "parser_summary.csv", rows)
        print(f"\nKẾT LUẬN: {'ĐẠT 100%' if ok_all else 'CHƯA ĐẠT'}")

    rate = benchmark()
    print(f"Tốc độ parser: {rate:,.0f} dòng/s (cần ≥ 500 dòng/s, dư {rate / 500:,.0f} lần)")
    print("Đã ghi logs/errors.log và analysis/parser_summary.csv")


if __name__ == "__main__":
    main()

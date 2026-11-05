"""VIE-02 — sinh reports/offset_impact_report.pdf từ kết quả của practice_offset_eval.py.

    python scripts/practice_offset_eval.py
    python scripts/make_offset_report.py

Cần Python Playwright để in PDF (pip install playwright && playwright install chromium).
Không có Playwright thì vẫn có reports/offset_impact_report.html — mở bằng trình duyệt, Ctrl+P → Save as PDF.
"""
from __future__ import annotations

import base64
from datetime import date

from _common import DIRS, ROOT, read_csv

import practice_offset_eval


def build_html(res) -> str:
    b = res["baseline"]
    rows = read_csv(DIRS["analysis"] / "offset_impact.csv")
    img = base64.b64encode((DIRS["figures"] / "offset_impact.png").read_bytes()).decode()
    max_diff = max(float(r["abs_diff_L"]) for r in rows)
    tr = "\n".join(
        f"<tr><td>{float(r['duration_s']):.0f}</td><td>{float(r['offset_lps']):.3f}</td>"
        f"<td>{1000 * float(r['dV_theory_L']):.0f}</td><td>{1000 * float(r['dV_numeric_L']):.3f}</td>"
        f"<td>{float(r['abs_diff_L']):.1e}</td>"
        f"<td class='{'bad' if r['exceeds_ATS_50mL'] == 'True' else 'ok'}'>"
        f"{'Vượt' if r['exceeds_ATS_50mL'] == 'True' else 'Đạt'}</td></tr>" for r in rows)
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<title>Báo cáo tác động offset — VIE-02</title>
<style>
 @page {{ size: A4; margin: 18mm 16mm; }}
 body {{ font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt; color: #1f1f1e; line-height: 1.45; }}
 h1 {{ font-size: 17pt; margin: 0 0 2pt; }} h2 {{ font-size: 12.5pt; margin: 16pt 0 5pt; border-bottom: 1px solid #ddd; padding-bottom: 2pt; }}
 .meta {{ color: #5f5e5a; font-size: 9.5pt; margin-bottom: 10pt; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 9.5pt; margin: 6pt 0; }}
 th, td {{ border: 1px solid #d6d5d0; padding: 3pt 6pt; text-align: right; }} th {{ background: #f3f2ee; text-align: center; }}
 td:first-child, th:first-child {{ text-align: center; }}
 .ok {{ color: #006300; font-weight: 600; text-align: center; }} .bad {{ color: #b3261e; font-weight: 600; text-align: center; }}
 .eq {{ font-family: "Cambria Math", "Times New Roman", serif; font-size: 12pt; text-align: center; margin: 6pt 0; }}
 .box {{ background: #f6f8fc; border-left: 3px solid #2a78d6; padding: 6pt 10pt; margin: 8pt 0; }}
 img {{ width: 100%; }} .sign td {{ text-align: left; height: 26pt; }}
</style></head><body>
<h1>Báo cáo tác động của offset lưu lượng lên thể tích</h1>
<div class="meta">Smart Spirometer · VIE-02 (Bài 16) · Nguyễn Hoàng Việt · {date.today():%d/%m/%Y} ·
Dữ liệu: <b>đường cong chuẩn 5 nút (sóng giáo khoa, không phải số đo thật)</b> · Mã: <code>scripts/practice_offset_eval.py</code></div>

<div class="box"><b>Kết luận.</b> Một offset lưu lượng chỉ +0.02 L/s gây sai số thể tích +0.040 L sau 2 s và
+0.120 L sau 6 s, vượt giới hạn ±0.050 L của ATS/ERS 2019. Sai số tăng tuyến tính tuyệt đối theo thời gian
tích phân (sai khác số học – lý thuyết ≤ {max_diff:.0e} L), nên thiết bị bắt buộc phải bù zero động trước mỗi lượt đo.</div>

<h2>1. Mục tiêu và tiêu chuẩn</h2>
<p>Định lượng sai số thể tích do một offset tĩnh trên tín hiệu lưu lượng Q và chứng minh sự cần thiết của
cơ chế bù zero động. Tiêu chuẩn đối chiếu: ATS/ERS 2019, giới hạn sai số thể tích ±0.050 L hoặc ±3 %.</p>

<h2>2. Phương pháp</h2>
<p>Đường cong lưu lượng chuẩn 5 nút (t = 0; 0.5; 1.0; 1.5; 2.0 s, Q = 0; 2; 2; 1; 0 L/s), nội suy tuyến tính,
lấy mẫu Fs = 500 Hz. Thể tích tích phân bằng phương pháp hình thang:</p>
<div class="eq">V[n] = V[n−1] + ½·(Q[n] + Q[n−1])·(t[n] − t[n−1])</div>
<p>Cộng offset tĩnh vào toàn bộ chuỗi Q, tích phân lại trong 2 s và 6 s, so với sai số lý thuyết:</p>
<div class="eq">ΔV<sub>offset</sub> = offset × Δt</div>

<h2>3. Chỉ số chuẩn (không offset)</h2>
<table><tr><th>PEF (L/s)</th><th>V(1 s) (L)</th><th>V tổng (L)</th><th>V(1 s)/V tổng (%)</th></tr>
<tr><td>{b['PEF_lps']:.3f}</td><td>{b['V1s_L']:.3f}</td><td>{b['Vtotal_L']:.3f}</td><td>{b['ratio_pct']:.1f}</td></tr></table>
<p style="font-size:9pt;color:#5f5e5a">V(1 s) tính từ lúc bắt đầu thở (định nghĩa của Bài 16). FEV1 theo ATS/ERS dùng
t0 ngoại suy ngược (t0 = 0.25 s) nên cho 1.9375 L — khác định nghĩa, không phải sai số.</p>

<h2>4. Kết quả quét offset</h2>
<table><tr><th>Thời gian (s)</th><th>Offset (L/s)</th><th>ΔV lý thuyết (mL)</th><th>ΔV số học (mL)</th>
<th>|Chênh lệch| (L)</th><th>So với 50 mL</th></tr>{tr}</table>
<img src="data:image/png;base64,{img}" alt="Đường thể tích có và không có offset">

<h2>5. Nhận xét</h2>
<ul>
<li>Sai số thể tích tỷ lệ thuận với cả offset và thời gian tích phân; kết quả số học trùng lý thuyết tới sai số làm tròn máy.</li>
<li>Với nhịp thở gắng sức 6 s, chỉ cần offset ≥ 0.010 L/s (≈ 0.2 % của PEF 5 L/s) là FVC đã vượt giới hạn 50 mL.</li>
<li>Offset 0.02 L/s tương ứng ΔP ≈ 0.006 Pa với a = 0.25 L/(s·√Pa), nhỏ hơn nhiều so với 1 count ADC (≈ 1.21 Pa). Nhưng một
lệch zero chỉ 1 count (1.21 Pa) qua mô hình căn thức đã thành Q ≈ 0.25·√1.21 ≈ 0.28 L/s, gấp ~14 lần mức 0.02 L/s ở trên.
Vì vậy phải đo lại zero ngay trước mỗi lượt (1 s, ống kín gió), từ chối khi σ &gt; 5 count, và dùng ngưỡng chết
|ΔP| &lt; 1 Pa → Q = 0.</li>
<li>Phương pháp tích phân không phải nguồn sai số chính: hình thang và Simpson chênh nhau &lt; 0.01 mL (xem VIE-16).</li>
</ul>

<h2>Ký xác nhận</h2>
<table class="sign"><tr><th>Vai trò</th><th>Họ tên</th><th>Ký</th><th>Ngày</th></tr>
<tr><td>Người thực hiện</td><td>Nguyễn Hoàng Việt</td><td></td><td></td></tr>
<tr><td>Trưởng nhóm nghiệm thu</td><td>Nguyễn Gia Trí</td><td></td><td></td></tr></table>
</body></html>"""


def main():
    res = practice_offset_eval.main()
    html = build_html(res)
    out_html = DIRS["reports"] / "offset_impact_report.html"
    out_html.write_text(html, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page()
            page.goto(out_html.resolve().as_uri())
            page.pdf(path=str(DIRS["reports"] / "offset_impact_report.pdf"), format="A4", print_background=True)
            b.close()
        print("Đã tạo reports/offset_impact_report.pdf")
    except Exception as e:
        print(f"Không in được PDF ({e}). Mở {out_html.relative_to(ROOT)} bằng trình duyệt → Ctrl+P → Save as PDF.")


if __name__ == "__main__":
    main()

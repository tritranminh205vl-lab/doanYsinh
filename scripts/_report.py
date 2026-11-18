"""Tiện ích dựng báo cáo PDF (HTML -> PDF qua Playwright) dùng chung cho các script."""
from __future__ import annotations

import base64
import html as _html
from datetime import date
from pathlib import Path

from _common import DIRS, ROOT

CSS = """
@page { size: A4; margin: 16mm 15mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.2pt; color: #1f1f1e; line-height: 1.45; }
h1 { font-size: 16.5pt; margin: 0 0 2pt; } h2 { font-size: 12.3pt; margin: 14pt 0 5pt; border-bottom: 1px solid #ddd; padding-bottom: 2pt; }
.meta { color: #5f5e5a; font-size: 9.3pt; margin-bottom: 9pt; }
table { border-collapse: collapse; width: 100%; font-size: 9.2pt; margin: 5pt 0 8pt; }
th, td { border: 1px solid #d6d5d0; padding: 2.5pt 5pt; text-align: right; } th { background: #f3f2ee; text-align: center; }
td:first-child { text-align: left; }
.box { background: #f6f8fc; border-left: 3px solid #2a78d6; padding: 6pt 10pt; margin: 8pt 0; }
.warn { background: #fff7ec; border-left: 3px solid #eda100; padding: 6pt 10pt; margin: 8pt 0; }
.best { font-weight: 700; color: #006300; }
img { width: 100%; margin: 4pt 0; } figure { margin: 4pt 0 8pt; } figcaption { font-size: 8.8pt; color: #5f5e5a; }
.sign td { text-align: left; height: 24pt; } code { font-size: 9pt; }
"""


def img_tag(name: str, caption: str = "") -> str:
    b64 = base64.b64encode((DIRS["figures"] / name).read_bytes()).decode()
    cap = f"<figcaption>{_html.escape(caption)}</figcaption>" if caption else ""
    return f'<figure><img src="data:image/png;base64,{b64}">{cap}</figure>'


def table(headers, rows, best_col=None, best_row=None) -> str:
    th = "".join(f"<th>{_html.escape(str(h))}</th>" for h in headers)
    trs = []
    for i, r in enumerate(rows):
        cls = ' class="best"' if best_row is not None and i == best_row else ""
        trs.append(f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    return f"<table><tr>{th}</tr>{''.join(trs)}</table>"


def page(title: str, meta: str, body: str) -> str:
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>{_html.escape(title)}</title>'
            f"<style>{CSS}</style></head><body><h1>{_html.escape(title)}</h1>"
            f'<div class="meta">{meta} · {date.today():%d/%m/%Y}</div>{body}</body></html>')


def sign_block(task: str) -> str:
    return ("<h2>Ký xác nhận</h2><table class='sign'><tr><th>Vai trò</th><th>Họ tên</th><th>Ký</th><th>Ngày</th></tr>"
            f"<tr><td>Người thực hiện ({task})</td><td>Nguyễn Hoàng Việt</td><td></td><td></td></tr>"
            "<tr><td>Trưởng nhóm nghiệm thu</td><td>Nguyễn Gia Trí</td><td></td><td></td></tr></table>")


def write_report(html: str, stem: str) -> Path:
    """Ghi reports/<stem>.html rồi in reports/<stem>.pdf (nếu có Playwright)."""
    out_html = DIRS["reports"] / f"{stem}.html"
    out_html.write_text(html, encoding="utf-8")
    out_pdf = DIRS["reports"] / f"{stem}.pdf"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(out_html.resolve().as_uri())
            pg.pdf(path=str(out_pdf), format="A4", print_background=True)
            b.close()
        print(f"Đã tạo {out_pdf.relative_to(ROOT)}")
        return out_pdf
    except Exception as e:
        print(f"Không in được PDF ({type(e).__name__}). Mở {out_html.relative_to(ROOT)} bằng trình duyệt "
              f"→ Ctrl+P → Save as PDF.")
        return out_html

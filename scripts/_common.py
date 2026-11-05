"""Tiện ích dùng chung cho các script: đường dẫn, style đồ thị, ghi CSV."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Bảng màu phân loại cố định (không xoay vòng)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
INK, INK2, GRID = "#1f1f1e", "#5f5e5a", "#e4e3df"

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 140, "font.size": 9,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.6,
    "legend.frameon": False, "svg.hashsalt": "smart-spirometer",
})

DIRS = {k: ROOT / k for k in ("analysis", "figures", "reports", "logs", "calibration", "docs")}
for d in DIRS.values():
    d.mkdir(parents=True, exist_ok=True)


def savefig(fig, name):
    p = DIRS["figures"] / name
    fig.savefig(p, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return p


def write_csv(path, rows, fieldnames=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})
    return path


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

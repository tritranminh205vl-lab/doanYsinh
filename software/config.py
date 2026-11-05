"""Nạp và kiểm tra cấu hình theo config_schema.json (VIE-01)."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from . import PROJECT_ROOT

SCHEMA_PATH = PROJECT_ROOT / "config" / "config_schema.json"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default_config.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_config(cfg: dict) -> dict:
    """Ném jsonschema.ValidationError nếu cấu hình sai/thiếu trường."""
    jsonschema.validate(instance=cfg, schema=load_schema())
    return cfg


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return validate_config(cfg)


def effective_divider(cfg: dict) -> float:
    """Ưu tiên tỷ số đo thực tế của Nhung, nếu chưa có thì dùng danh định."""
    k = cfg.get("divider_ratio_measured")
    return float(k) if k else float(cfg["divider_ratio"])


def effective_vs(cfg: dict) -> float:
    vs = cfg.get("vs_measured_v")
    return float(vs) if vs else float(cfg["vs_nominal_v"])

"""配置加载器 — 支持 YAML 配置和 CLI 参数合并."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


def load_yaml(path: str) -> dict[str, Any]:
    """加载 YAML 配置文件，带降级处理."""
    if yaml is None:
        raise ImportError(
            "PyYAML is required for config loading. "
            "Install with: pip install pyyaml"
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_project_root() -> Path:
    """获取项目根目录 (Geo-OpenClaw/)."""
    return Path(__file__).resolve().parent.parent.parent


def get_config_dir() -> Path:
    """获取配置目录."""
    return get_project_root() / "config"


def get_logs_dir() -> Path:
    """获取日志目录."""
    p = get_project_root() / "logs"
    p.mkdir(exist_ok=True)
    return p


def merge_configs(*configs: dict) -> dict:
    """深度合并多个配置字典，后覆盖前."""
    result: dict = {}
    for config in configs:
        for key, value in config.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = merge_configs(result[key], value)
            else:
                result[key] = value
    return result

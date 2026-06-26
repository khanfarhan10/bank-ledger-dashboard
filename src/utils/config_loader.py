"""Load the YAML config files (aliases, categories, thresholds).

Thin wrappers around PyYAML with sensible fallbacks so a missing or malformed
config file degrades gracefully instead of crashing the dashboard.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.utils.logging_setup import get_logger

CONFIG_DIR = Path("config")


def load_yaml(path: Path | str, default: dict | None = None) -> dict:
    """Load a YAML file into a dict, returning ``default`` on any problem."""
    path = Path(path)
    default = default if default is not None else {}
    if not path.exists():
        get_logger().warning("Config file not found: %s (using defaults)", path)
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else default
    except Exception as exc:  # noqa: BLE001 - never let bad config crash the app
        get_logger().error("Failed to read %s: %s (using defaults)", path, exc)
        return default


def load_aliases(config_dir: Path | str = CONFIG_DIR) -> dict:
    """Return the 'people' mapping from aliases.yml.

    Shape: { person_key: {display_name, related_flag, aliases: [...]}, ... }
    """
    data = load_yaml(Path(config_dir) / "aliases.yml")
    return data.get("people", {}) or {}


def load_categories(config_dir: Path | str = CONFIG_DIR) -> list[str]:
    """Return the list of category strings from categories.yml."""
    data = load_yaml(Path(config_dir) / "categories.yml")
    return list(data.get("categories", []) or [])


def load_review_statuses(config_dir: Path | str = CONFIG_DIR) -> list[str]:
    """Return the list of manual review statuses from categories.yml."""
    data = load_yaml(Path(config_dir) / "categories.yml")
    return list(data.get("review_statuses", []) or [])


def load_threshold(config_dir: Path | str = CONFIG_DIR, default: float = 3000.0) -> float:
    """Return the configured large-payment threshold (file value only)."""
    data = load_yaml(Path(config_dir) / "thresholds.yml")
    try:
        return float(data.get("large_payment_threshold", default))
    except (TypeError, ValueError):
        return default

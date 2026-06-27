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


def load_non_expense_categories(config_dir: Path | str = CONFIG_DIR) -> list[str]:
    """Categories that are NOT real consumption (savings/internal/family deposits)."""
    data = load_yaml(Path(config_dir) / "categories.yml")
    return list(data.get("non_expense_categories", []) or [])


def load_threshold(config_dir: Path | str = CONFIG_DIR, default: float = 3000.0) -> float:
    """Return the configured large-payment threshold (file value only)."""
    data = load_yaml(Path(config_dir) / "thresholds.yml")
    try:
        return float(data.get("large_payment_threshold", default))
    except (TypeError, ValueError):
        return default


def load_self_identity(config_dir: Path | str = CONFIG_DIR) -> dict:
    """Return the account-holder self-identity config (self_identity.yml).

    Used to detect self-transfers (money moving between the user's own
    accounts/instruments) so they are excluded from income/expense totals.
    Returns sensible empty lists if the file is missing.
    """
    data = load_yaml(Path(config_dir) / "self_identity.yml")
    return {
        "account_holder": data.get("account_holder", ""),
        "own_phone_numbers": list(data.get("own_phone_numbers", []) or []),
        "own_upi_handles": list(data.get("own_upi_handles", []) or []),
        "own_account_numbers": list(data.get("own_account_numbers", []) or []),
        "own_account_prefixes": list(data.get("own_account_prefixes", []) or []),
        "own_banks": list(data.get("own_banks", []) or []),
        "self_transfer_patterns": list(data.get("self_transfer_patterns", []) or []),
    }

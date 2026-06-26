"""Export DataFrames to CSV/XLSX under data/exports/ (never the source folder).

Two ways to use it:
    * to_csv_bytes / to_xlsx_bytes -> in-memory bytes for Streamlit download
      buttons (nothing is written to disk).
    * write_csv / write_xlsx -> persist a file under data/exports/ and return
      the path, for users who want a saved copy.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.utils.logging_setup import get_logger

EXPORTS_DIR = Path("data/exports")


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Serialise a DataFrame to CSV bytes (UTF-8 with BOM for Excel friendliness)."""
    return df.to_csv(index=False).encode("utf-8-sig")


def to_xlsx_bytes(df: pd.DataFrame, sheet_name: str = "data") -> bytes:
    """Serialise a DataFrame to XLSX bytes using openpyxl."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31] or "data")
    return buffer.getvalue()


def write_csv(df: pd.DataFrame, label: str, exports_dir: Path | str = EXPORTS_DIR) -> Path:
    """Write a CSV under data/exports/ and return its path."""
    path = _timestamped_path(label, "csv", exports_dir)
    path.write_bytes(to_csv_bytes(df))
    get_logger().info("Exported %d rows -> %s", len(df), path)
    return path


def write_xlsx(df: pd.DataFrame, label: str, exports_dir: Path | str = EXPORTS_DIR) -> Path:
    """Write an XLSX under data/exports/ and return its path."""
    path = _timestamped_path(label, "xlsx", exports_dir)
    path.write_bytes(to_xlsx_bytes(df))
    get_logger().info("Exported %d rows -> %s", len(df), path)
    return path


def export_filename(label: str, extension: str) -> str:
    """Build a safe, timestamped export filename (no directory)."""
    safe = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "export"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe}_{stamp}.{extension}"


def _timestamped_path(label: str, extension: str, exports_dir: Path | str) -> Path:
    exports_dir = Path(exports_dir)
    exports_dir.mkdir(parents=True, exist_ok=True)
    return exports_dir / export_filename(label, extension)

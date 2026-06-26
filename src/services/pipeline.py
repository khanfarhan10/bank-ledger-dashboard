"""Orchestration: tie the services together into one ledger-building flow.

The flow, in order:
    1. extract_all      -> raw rows from every file + per-file reports
    2. normalize        -> amount/direction, transaction_id, name detection
    3. classify         -> transparent auto-categories + large-payment flag
    4. merge_decisions  -> overlay the user's saved manual decisions
    5. + manual entries -> append user-created manual rows

Steps 1-3 depend only on the source files and config, so the app can cache
them. Steps 4-5 depend on the SQLite store and are cheap, so they run on every
interaction to reflect edits immediately.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.models.transaction_schema import SCHEMA_COLUMNS, ensure_columns
from src.services.classification_service import apply_large_payment_flag, classify
from src.services.decision_store import (
    DecisionStore,
    manual_entries_as_rows,
    merge_decisions,
)
from src.services.export_service import write_csv
from src.services.extraction_service import extract_all
from src.services.normalization_service import normalize
from src.utils.config_loader import (
    load_aliases,
    load_categories,
    load_threshold,
)

PROCESSED_DIR = Path("data/processed")
THRESHOLD_SETTING_KEY = "large_payment_threshold"


def effective_aliases(store: DecisionStore) -> dict:
    """Config aliases plus any aliases the user added via the UI."""
    aliases = {k: dict(v) for k, v in load_aliases().items()}
    db = store.get_aliases_df()
    for _, row in db.iterrows() if not db.empty else []:
        key = row["person_key"]
        person = aliases.setdefault(key, {
            "display_name": row.get("display_name") or key,
            "related_flag": row.get("related_flag") or key,
            "aliases": [],
        })
        alias = (row.get("alias") or "").strip().lower()
        if alias and alias not in person["aliases"]:
            person["aliases"].append(alias)
    return aliases


def effective_categories(store: DecisionStore) -> list[str]:
    """Config categories plus any categories the user added via the UI."""
    base = load_categories()
    extra = [c for c in store.get_categories() if c not in base]
    return base + extra


def effective_threshold(store: DecisionStore) -> float:
    """Threshold from the DB setting if present, else from thresholds.yml."""
    value = store.get_setting(THRESHOLD_SETTING_KEY)
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    return load_threshold()


def extract_normalize_classify(source_dir: str, aliases: dict, threshold: float) -> dict:
    """Steps 1-3. Returns dict(unified, reports, classified, extracted_at).

    ``unified`` is the raw extraction (parser output). ``classified`` is the
    full-schema, auto-classified ledger before manual decisions are applied.
    """
    extraction = extract_all(source_dir)
    raw = extraction["transactions"]

    normalized = normalize(raw, aliases)
    classified = classify(normalized, threshold=threshold)

    # Persist processed artifacts (outside the read-only source folder).
    _safe_write(raw, "unified_extraction")
    return {
        "unified": raw,
        "reports": extraction["reports"],
        "classified": classified,
        "extracted_at": extraction["extracted_at"],
    }


def finalize_ledger(classified: pd.DataFrame, store: DecisionStore, threshold: float) -> pd.DataFrame:
    """Steps 4-5. Overlay manual decisions and append manual entries.

    Returns the master combined ledger (full schema), with the large-payment
    flag recomputed for the current threshold.
    """
    merged = merge_decisions(classified, store)
    merged = apply_large_payment_flag(merged, threshold=threshold)

    manual = manual_entries_as_rows(store)
    if not manual.empty:
        manual = apply_large_payment_flag(manual, threshold=threshold)
        combined = pd.concat([merged, manual], ignore_index=True)
    else:
        combined = merged

    combined = ensure_columns(combined, SCHEMA_COLUMNS)
    _safe_write(combined, "combined_transactions")
    return combined


def _safe_write(df: pd.DataFrame, label: str) -> None:
    """Write a processed CSV under data/processed/, ignoring write errors.

    A failure to write a convenience artifact must never break the dashboard.
    """
    try:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(PROCESSED_DIR / f"{label}.csv", index=False, encoding="utf-8-sig")
    except Exception:  # noqa: BLE001 - non-critical convenience output
        pass

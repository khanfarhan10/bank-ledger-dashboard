"""Turn raw extracted rows into the full unified schema.

Normalization is deterministic and transparent:
    * compute absolute ``amount`` and a ``direction`` from debit/credit,
    * assign a stable ``transaction_id``,
    * detect configured person aliases in the description,
    * set the per-person boolean flags.

It does NOT classify into categories (that is classification_service) and does
NOT apply any manual decisions (that is decision_store). Those are layered on
top so each step stays small and testable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

from src.models.transaction_schema import (
    PAID_OUT,
    RECEIVED,
    SCHEMA_COLUMNS,
    UNKNOWN,
    ensure_columns,
)
from src.utils.config_loader import load_aliases
from src.utils.hashing import transaction_id


def normalize(raw: pd.DataFrame, aliases: dict | None = None) -> pd.DataFrame:
    """Return a full-schema DataFrame built from raw parser output.

    ``aliases`` is the people mapping (as from load_aliases); if None it is
    loaded from config. Each input row becomes one normalized row.
    """
    if aliases is None:
        aliases = load_aliases()

    if raw is None or raw.empty:
        return ensure_columns(pd.DataFrame(), SCHEMA_COLUMNS)

    ts = datetime.now(timezone.utc).isoformat()
    records = [_normalize_row(row, aliases, ts) for _, row in raw.iterrows()]
    df = pd.DataFrame(records)
    return ensure_columns(df, SCHEMA_COLUMNS)


def _normalize_row(row: pd.Series, aliases: dict, ts: str) -> dict:
    """Normalize a single raw row into a (partial) full-schema record."""
    debit = _num(row.get("debit"))
    credit = _num(row.get("credit"))
    amount, direction = _amount_and_direction(debit, credit)

    description = str(row.get("description") or "")
    # Paytm enrichment lands in counterparty_name; include it in name detection
    # but NOT in the transaction_id hash, so ids stay stable across re-runs.
    counterparty = str(row.get("counterparty_name") or "")
    detect_text = (description + " " + counterparty).strip()
    detected_keys, matched_alias_strings, flags = _detect_people(detect_text, aliases)

    txn_id = transaction_id(
        bank=row.get("source_bank"),
        date=row.get("transaction_date"),
        description=description,
        debit=debit,
        credit=credit,
        balance=row.get("balance"),
        source_file=row.get("source_file"),
        source_row_number=row.get("source_row_number"),
    )

    return {
        # provenance (carried straight through)
        "transaction_id": txn_id,
        "source_bank": row.get("source_bank"),
        "source_file": row.get("source_file"),
        "source_folder": row.get("source_folder"),
        "source_sheet": row.get("source_sheet"),
        "source_row_number": row.get("source_row_number"),
        "source_parser": row.get("source_parser"),
        "source_format": row.get("source_format"),
        "extraction_timestamp": ts,
        # core
        "transaction_date": row.get("transaction_date"),
        "value_date": row.get("value_date"),
        "description": description,
        "raw_description": row.get("raw_description"),
        "reference_number": row.get("reference_number"),
        "cheque_number": row.get("cheque_number"),
        # money
        "debit": debit,
        "credit": credit,
        "amount": amount,
        "direction": direction,
        "balance": _num(row.get("balance")),
        # names
        "counterparty_name": counterparty,
        "detected_names": ",".join(detected_keys),
        "matched_aliases": ",".join(matched_alias_strings),
        # per-person flags
        "is_benazir_related": flags["benazir"],
        "is_nazrana_related": flags["nazrana"],
        "is_mother_related": flags["mother"],
        "is_sister_related": flags["sister"],
    }


def flag_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Mark exact duplicate rows (is_duplicate=True on all but the first).

    Overlapping bank exports (e.g. ICICI year-boundary ranges) can list the
    same transaction in two files. A row is considered a true duplicate only
    when bank, date, narration, debit, credit AND running balance all match —
    identical running balance means the same ledger position, which cannot
    legitimately occur twice. The first occurrence is kept; the rest are
    flagged so totals can exclude them.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    key = ["source_bank", "transaction_date", "raw_description", "debit", "credit", "balance"]
    have = [k for k in key if k in out.columns]
    out["is_duplicate"] = out.duplicated(subset=have, keep="first")
    return out


def _amount_and_direction(debit: float, credit: float) -> tuple[float, str]:
    """Derive absolute amount and direction from debit/credit.

    debit > 0  -> money paid out
    credit > 0 -> money received
    both zero / both set -> UNKNOWN (rare; flagged for manual review)
    """
    if debit > 0 and credit == 0:
        return abs(debit), PAID_OUT
    if credit > 0 and debit == 0:
        return abs(credit), RECEIVED
    if debit == 0 and credit == 0:
        return 0.0, UNKNOWN
    # Both non-zero: ambiguous; report the larger magnitude, mark UNKNOWN.
    return abs(debit) if abs(debit) >= abs(credit) else abs(credit), UNKNOWN


def _detect_people(description: str, aliases: dict) -> tuple[list[str], list[str], dict]:
    """Find which configured people are mentioned in the description.

    Returns (person_keys, matched_alias_strings, flags) where flags carries the
    per-bucket booleans used by the schema (benazir/nazrana).
    """
    haystack = _normalize_text(description)
    person_keys: list[str] = []
    matched_alias_strings: list[str] = []
    flags = {"benazir": False, "nazrana": False, "mother": False, "sister": False}

    for key, person in aliases.items():
        related_flag = (person or {}).get("related_flag", key)
        for alias in (person or {}).get("aliases", []):
            if _alias_in(alias, haystack):
                if key not in person_keys:
                    person_keys.append(key)
                matched_alias_strings.append(alias)
                if related_flag in flags:
                    flags[related_flag] = True
    return person_keys, matched_alias_strings, flags


def _normalize_text(text: str) -> str:
    """Lowercase and collapse non-alphanumerics to single spaces for matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _alias_in(alias: str, normalized_haystack: str) -> bool:
    """True if the (normalized) alias appears as a token-run in the haystack."""
    needle = _normalize_text(alias)
    if not needle:
        return False
    # Surround with spaces so 'b rahaman' matches token boundaries, not substrings.
    return f" {needle} " in f" {normalized_haystack} "


def _num(value) -> float:
    """Coerce a possibly-NA numeric to float (0.0 when missing)."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0

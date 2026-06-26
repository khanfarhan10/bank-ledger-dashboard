"""The unified transaction schema shared by every parser and service.

Every parser, regardless of bank or file format, must return rows that fit this
schema. Keeping a single, explicit list of columns here means the rest of the
app (normalization, classification, UI, exports) can rely on a stable contract.

Nothing here is clever: it is a flat list of column names plus a couple of small
helpers to build empty/aligned DataFrames.
"""

from __future__ import annotations

import pandas as pd

# Direction values. `amount` is always the absolute value; `direction` records
# which way the money moved. UNKNOWN is used when we genuinely cannot tell.
PAID_OUT = "PAID_OUT"
RECEIVED = "RECEIVED"
UNKNOWN = "UNKNOWN"
DIRECTIONS = (PAID_OUT, RECEIVED, UNKNOWN)

# The full ordered list of columns in the unified schema.
# Grouped by purpose for readability; order is what CSV/XLSX exports will use.
SCHEMA_COLUMNS: list[str] = [
    # --- provenance: where this row came from ---
    "transaction_id",
    "source_bank",
    "source_file",
    "source_folder",
    "source_sheet",
    "source_row_number",
    "source_parser",
    "source_format",
    "extraction_timestamp",
    # --- core transaction fields ---
    "transaction_date",
    "value_date",
    "description",
    "raw_description",
    "reference_number",
    "cheque_number",
    # --- money ---
    "debit",            # money paid out (>= 0)
    "credit",           # money received (>= 0)
    "amount",           # absolute amount of the transaction
    "direction",        # PAID_OUT | RECEIVED | UNKNOWN
    "balance",          # running balance as reported by the bank
    # --- name detection ---
    "counterparty_name",
    "detected_names",   # comma-joined person keys detected via aliases
    "matched_aliases",  # comma-joined specific alias strings that matched
    # --- classification ---
    "category",
    "subcategory",
    "tags",                    # comma-joined multi-label tags (food, upi, 80c...)
    "classification_status",   # auto | manual | unclassified
    "classification_reason",
    "confidence",              # simple 0..1 hint, never a guarantee
    # --- boolean flags ---
    "is_benazir_related",
    "is_nazrana_related",
    "is_large_payment",
    "is_self_transfer",        # money between the user's own accounts (excluded from totals)
    "is_income",               # real income (salary, refund, interest, ...)
    "is_investment",           # money invested/saved (not an expense)
    "is_duplicate",            # exact duplicate from overlapping exports (excluded)
    "is_manual_entry",
    "is_linked_entry",
    # --- manual review (merged in from the decision store) ---
    "manual_comment",
    "manual_review_status",
    "manual_flags",
    "linked_transaction_ids",
    "created_at",
    "updated_at",
]

# Columns a parser is expected to populate directly. Everything else is filled
# in later by normalization / classification / the decision store.
PARSER_OUTPUT_COLUMNS: list[str] = [
    "source_bank",
    "source_file",
    "source_folder",
    "source_sheet",
    "source_row_number",
    "source_parser",
    "source_format",
    "transaction_date",
    "value_date",
    "description",
    "raw_description",
    "reference_number",
    "cheque_number",
    "debit",
    "credit",
    "balance",
]


def empty_frame(columns: list[str] | None = None) -> pd.DataFrame:
    """Return an empty DataFrame with the requested columns (defaults to full schema)."""
    return pd.DataFrame(columns=columns or SCHEMA_COLUMNS)


def ensure_columns(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Return a copy of ``df`` containing exactly ``columns`` in order.

    Missing columns are added (as empty), extra columns are dropped. This keeps
    downstream code from having to defend against partially-populated frames.
    """
    columns = columns or SCHEMA_COLUMNS
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = pd.NA
    return out[columns]

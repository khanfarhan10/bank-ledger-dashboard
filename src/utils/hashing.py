"""Stable transaction-id generation.

A transaction_id is a deterministic hash of the fields that identify a row.
Re-running extraction on the same files produces the same ids, which is what
lets manual decisions (stored separately) re-attach to the right rows.
"""

from __future__ import annotations

import hashlib


def transaction_id(
    *,
    bank: str,
    date,
    description,
    debit,
    credit,
    balance,
    source_file: str,
    source_row_number,
) -> str:
    """Return a stable 16-char hex id for a bank transaction.

    The id is derived from the key identifying fields. Two rows with identical
    bank/date/description/amounts from the same file+row collapse to the same
    id (which is correct — they are the same transaction).
    """
    parts = [
        _clean(bank),
        _clean(date),
        _clean(description),
        _clean(debit),
        _clean(credit),
        _clean(balance),
        _clean(source_file),
        _clean(source_row_number),
    ]
    payload = "|".join(parts).encode("utf-8")
    return "txn_" + hashlib.sha1(payload).hexdigest()[:16]


def manual_entry_id(*, person, amount, entry_date, created_at) -> str:
    """Return a stable id for a manual entry."""
    payload = "|".join(_clean(x) for x in (person, amount, entry_date, created_at))
    return "man_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _clean(value) -> str:
    """Normalise a field to a trimmed string for hashing."""
    if value is None:
        return ""
    return str(value).strip()

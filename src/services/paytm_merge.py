"""Fold Paytm UPI rows into the bank rows without double counting.

Paytm sits on top of the bank accounts, so a Paytm payment funded by ICICI/HDFC
is the SAME money as a row already in the ICICI/HDFC statement. They share the
NPCI **UPI Ref No. (RRN)** — a 12-digit number present in both Paytm's
'UPI Ref No.' column and the bank narration (e.g. ICICI 'UPI/436675400185/...').

Rules:
  * Paytm row whose RRN is already in a bank row  -> DROP it (avoid double count),
    but ENRICH that bank row's counterparty_name with Paytm's payee text so
    people-detection (Benazir / mother / sister) improves. The bank row's
    description / raw_description are left untouched so transaction_id stays
    stable and existing manual decisions keep attaching.
  * Paytm row with no bank match (PNB / SBI / credit-card / UPI-Lite) -> KEEP it;
    this is a real payment the loaded bank statements never captured.

Returns the merged DataFrame and a small report dict for the UI/logs.
"""

from __future__ import annotations

import re

import pandas as pd

_RRN_RE = re.compile(r"\b\d{12}\b")


def _bank_rrn_index(bank: pd.DataFrame) -> dict[str, int]:
    """Map every 12-digit RRN found in a bank row to that row's index."""
    index: dict[str, int] = {}
    for idx, row in bank.iterrows():
        text = f"{row.get('raw_description', '')} {row.get('reference_number', '')}"
        for rrn in _RRN_RE.findall(str(text)):
            index.setdefault(rrn, idx)
    return index


def merge_paytm(combined: pd.DataFrame, logger=None) -> tuple[pd.DataFrame, dict]:
    """Split Paytm vs bank rows, dedup by RRN, enrich, and recombine."""
    empty_report = {"paytm_total": 0, "deduped": 0, "kept": 0, "enriched": 0, "by_source": {}}
    if combined is None or combined.empty or "source_parser" not in combined.columns:
        return combined, empty_report

    is_paytm = combined["source_parser"].fillna("") == "paytm_excel_parser"
    if not is_paytm.any():
        return combined, empty_report

    bank = combined[~is_paytm].copy()
    paytm = combined[is_paytm].copy()
    if "counterparty_name" not in bank.columns:
        bank["counterparty_name"] = ""

    rrn_index = _bank_rrn_index(bank)

    keep_rows, deduped, enriched = [], 0, 0
    for _, prow in paytm.iterrows():
        ref = str(prow.get("reference_number") or "").strip()
        bank_idx = rrn_index.get(ref) if ref else None
        if bank_idx is not None:
            # Same transaction already in a bank statement -> drop, but enrich.
            payee = str(prow.get("description") or "").strip()
            existing = str(bank.at[bank_idx, "counterparty_name"] or "")
            if payee and payee.lower() not in existing.lower():
                bank.at[bank_idx, "counterparty_name"] = (existing + " | " + payee).strip(" |")
                enriched += 1
            deduped += 1
        else:
            keep_rows.append(prow)

    kept = pd.DataFrame(keep_rows, columns=paytm.columns) if keep_rows else paytm.iloc[0:0]

    by_source = (
        kept["source_bank"].value_counts().to_dict() if not kept.empty else {}
    )
    report = {
        "paytm_total": int(len(paytm)),
        "deduped": int(deduped),
        "kept": int(len(kept)),
        "enriched": int(enriched),
        "by_source": {str(k): int(v) for k, v in by_source.items()},
    }
    if logger:
        logger.info(
            "Paytm merge: %d total, %d deduped vs bank (enriched %d), %d kept (%s)",
            report["paytm_total"], report["deduped"], report["enriched"],
            report["kept"], ", ".join(f"{k}:{v}" for k, v in report["by_source"].items()),
        )

    merged = pd.concat([bank, kept], ignore_index=True)
    return merged, report

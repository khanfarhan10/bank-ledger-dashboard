"""Simple, transparent, rule-based classification.

No AI, no external calls, no debt inference. Each rule is a plain check on the
description or amount, and every classified row gets a human-readable reason
string explaining exactly why. Auto-classification is intentionally light:
manual decisions (applied later by the decision store) are the source of truth.

The big rule here is: this module only ever fills the *auto* classification.
It never touches a row that already carries a manual classification — that
guarantee is enforced by the pipeline, which merges manual decisions AFTER
classification and never lets auto overwrite manual.
"""

from __future__ import annotations

import pandas as pd

# Keyword groups -> category. Kept visible and editable on purpose.
_INSURANCE_KEYWORDS = ("kotak life", "life insurance", "insurance", "lic ", " lic", "policy", "premium")
_LOAN_KEYWORDS = ("emi", "loan", "lending", "personal loan")
_CASH_KEYWORDS = ("atm", "cash wdl", "cash withdrawal", "nwd", "self")


def classify(df: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
    """Return a copy of ``df`` with auto-classification columns filled in.

    Sets: category, classification_status, classification_reason, confidence,
    is_large_payment, is_benazir_related/is_nazrana_related (already set by
    normalization, left intact here), is_manual_entry/is_linked_entry defaults.
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    results = [_classify_row(row, threshold) for _, row in out.iterrows()]
    fields = pd.DataFrame(results, index=out.index)
    for col in fields.columns:
        out[col] = fields[col]

    # Default the flag/manual columns that downstream code expects to exist.
    # Bank-extracted rows are never manual entries; linking is decided later in
    # merge_decisions, so both default to False here.
    out["is_manual_entry"] = False
    out["is_linked_entry"] = False
    return out


def _classify_row(row: pd.Series, threshold: float) -> dict:
    """Apply the rules to one row and return the auto-classification fields."""
    description = str(row.get("description") or "").lower()
    amount = _num(row.get("amount"))
    matched_aliases = str(row.get("matched_aliases") or "")
    is_large = amount >= threshold and threshold > 0

    reasons: list[str] = []
    category = "unknown"
    confidence = 0.0

    # 1) Person-related (highest priority — these are the point of the project).
    if bool(row.get("is_benazir_related")):
        category = "benazir_payments"
        confidence = 0.9
        reasons.append(f'Matched Benazir alias ({matched_aliases or "alias"}) in description.')
    elif bool(row.get("is_nazrana_related")):
        category = "nazrana_payments"
        confidence = 0.9
        reasons.append(f'Matched Nazrana/Najrana alias ({matched_aliases or "alias"}) in description.')
    # 2) Lightweight keyword rules.
    elif _contains_any(description, _INSURANCE_KEYWORDS):
        category = "insurance"
        confidence = 0.6
        reasons.append("Description mentions insurance/policy/premium.")
    elif _contains_any(description, _LOAN_KEYWORDS):
        category = "loan_or_emi"
        confidence = 0.6
        reasons.append("Description mentions EMI/loan.")
    elif _contains_any(description, _CASH_KEYWORDS):
        category = "cash_withdrawal"
        confidence = 0.5
        reasons.append("Description looks like a cash/ATM withdrawal.")

    # 3) Large-payment flag (independent of category).
    if is_large:
        reasons.append(
            f"Amount {amount:.2f} is at/above the large-payment threshold {threshold:.0f}."
        )

    status = "auto" if category != "unknown" else "unclassified"
    if not reasons:
        reasons.append("No rule matched; left as unknown for manual review.")

    return {
        "category": category,
        "subcategory": "",
        "classification_status": status,
        "classification_reason": " ".join(reasons),
        "confidence": confidence,
        "is_large_payment": bool(is_large),
    }


def apply_large_payment_flag(df: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
    """Recompute only the is_large_payment flag for a new threshold.

    Used when the user changes the threshold live without wanting to redo the
    whole classification pass.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    amounts = out["amount"].map(_num)
    out["is_large_payment"] = (amounts >= threshold) & (threshold > 0)
    return out


def _contains_any(text: str, keywords) -> bool:
    return any(k in text for k in keywords)


def _num(value) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0

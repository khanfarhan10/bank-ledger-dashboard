"""Transparent, rule-based classification.

No AI, no external calls, no debt inference. The actual rules (regex) live in
``classification_rules.py``; self-transfer detection lives in
``self_transfer.py``. This module orchestrates them per row and records a
human-readable reason for every decision.

Priority order for the PRIMARY category (first win):
    1. self-transfer   — money between the user's own accounts (not in/out)
    2. person-related  — Benazir / Nazrana (the point of the project)
    3. regex category  — income, investment, insurance, food, shopping, ...
    4. unknown         — left for manual review

Independently of the category, every row gets a set of descriptive **tags**
(multi-label), so one entry can carry several valid sub-classifications
(e.g. a Kotak premium → category=insurance, tags={insurance, tax_saving_80c}).

This module only ever fills the *auto* classification. Manual decisions are
merged later by the decision store and always win.
"""

from __future__ import annotations

import pandas as pd

from src.services.classification_rules import (
    match_category,
    match_investment_tags,
    match_tags,
)
from src.services.self_transfer import SelfTransferDetector

# Categories that represent real income (credits that aren't self-transfers).
_INCOME_CATEGORIES = {
    "salary_or_income",
    "it_refund",
    "interest_income",
    "cashback_reward",
}


def classify(df: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
    """Return a copy of ``df`` with auto-classification columns filled in.

    Sets: category, subcategory, tags, classification_status,
    classification_reason, confidence, is_large_payment, is_self_transfer,
    is_income, is_investment, and the manual/linked defaults.
    """
    if df is None or df.empty:
        return df

    detector = SelfTransferDetector()
    out = df.copy()
    results = [_classify_row(row, threshold, detector) for _, row in out.iterrows()]
    fields = pd.DataFrame(results, index=out.index)
    for col in fields.columns:
        out[col] = fields[col]

    # Bank-extracted rows are never manual entries; linking is decided later.
    out["is_manual_entry"] = False
    out["is_linked_entry"] = False
    out["is_duplicate"] = out.get("is_duplicate", False)
    return out


def _classify_row(row: pd.Series, threshold: float, detector: SelfTransferDetector) -> dict:
    """Apply self-transfer + person + regex rules to one row."""
    # Prefer raw_description (full narration incl. merged continuations).
    text = str(row.get("raw_description") or row.get("description") or "").lower()
    amount = _num(row.get("amount"))
    direction = str(row.get("direction") or "").upper()
    matched_aliases = str(row.get("matched_aliases") or "")
    is_large = amount >= threshold and threshold > 0

    tags = match_tags(text)
    investment_tags = match_investment_tags(text)

    category = "unknown"
    confidence = 0.0
    reasons: list[str] = []
    is_self = False
    is_income = False
    is_investment = False

    # 1) Self-transfer (highest priority — excluded from real in/out).
    self_flag, self_reason = detector.is_self_transfer(text)
    if self_flag:
        category = "self_transfer"
        confidence = 0.95
        is_self = True
        reasons.append(self_reason)
        if "self_transfer" not in tags:
            tags.insert(0, "self_transfer")

    # 2) Person-related.
    elif bool(row.get("is_benazir_related")):
        category = "benazir_payments"
        confidence = 0.9
        reasons.append(f'Matched Benazir alias ({matched_aliases or "alias"}).')
    elif bool(row.get("is_nazrana_related")):
        category = "nazrana_payments"
        confidence = 0.9
        reasons.append(f'Matched Nazrana/Najrana alias ({matched_aliases or "alias"}).')

    # 3) Regex category rules.
    else:
        cat, reason = match_category(text, direction)
        if cat is not None:
            category = cat
            confidence = 0.7
            reasons.append(reason)
        elif investment_tags:
            # Tag-detected investment the category regex missed: keep them
            # consistent (paid = investing, received = redemption).
            category = "investment" if direction == "PAID_OUT" else "investment_redemption"
            confidence = 0.6
            reasons.append(f"Investment instrument detected ({investment_tags[0]}).")

    # Derived flags (independent of the headline category).
    if not is_self:
        if category in _INCOME_CATEGORIES and direction == "RECEIVED":
            is_income = True
        if category == "investment" or investment_tags:
            is_investment = True

    if is_large:
        reasons.append(
            f"Amount {amount:.0f} is at/above the large-payment threshold {threshold:.0f}."
        )
    if not reasons:
        reasons.append("No rule matched; left as unknown for manual review.")

    status = "auto" if category != "unknown" else "unclassified"
    # Subcategory: the most specific investment tag, if any (else blank).
    subcategory = investment_tags[0] if investment_tags else ""

    return {
        "category": category,
        "subcategory": subcategory,
        "tags": ",".join(tags),
        "classification_status": status,
        "classification_reason": " ".join(reasons),
        "confidence": confidence,
        "is_large_payment": bool(is_large),
        "is_self_transfer": bool(is_self),
        "is_income": bool(is_income),
        "is_investment": bool(is_investment),
    }


def apply_large_payment_flag(df: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
    """Recompute only the is_large_payment flag for a new threshold."""
    if df is None or df.empty:
        return df
    out = df.copy()
    amounts = out["amount"].map(_num)
    out["is_large_payment"] = (amounts >= threshold) & (threshold > 0)
    return out


_INVESTMENT_CATEGORIES = {"investment", "investment_redemption"}


def recompute_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Re-derive is_self_transfer / is_income / is_investment from the FINAL
    category, so manual overrides (e.g. right-click "mark as self-transfer",
    or reclassifying to "salary_or_income") stay consistent with analytics.

    Run this after manual decisions are merged in.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    cat = out["category"].fillna("")
    direction = out["direction"].fillna("").str.upper()

    self_flag = out.get("is_self_transfer")
    self_flag = self_flag.fillna(False).astype(bool) if self_flag is not None else pd.Series(False, index=out.index)
    out["is_self_transfer"] = self_flag | (cat == "self_transfer")

    out["is_income"] = (
        cat.isin(_INCOME_CATEGORIES)
        & (direction == "RECEIVED")
        & ~out["is_self_transfer"]
    )

    invest_flag = out.get("is_investment")
    invest_flag = invest_flag.fillna(False).astype(bool) if invest_flag is not None else pd.Series(False, index=out.index)
    out["is_investment"] = invest_flag | cat.isin(_INVESTMENT_CATEGORIES)
    return out


def _num(value) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0

"""Read-only analytics over the finished ledger.

Everything here is a pure function of the combined ledger DataFrame — no I/O,
no writes. The web layer calls these to build the Overview, Income, and
Investments views. The central idea is the *corrected* money view:

    real income / expense  EXCLUDES self-transfers and duplicates,

so the headline numbers reflect money that actually entered or left the
person's hands, not internal shuffling between their own accounts.
"""

from __future__ import annotations

import pandas as pd

from src.services.classification_rules import (
    INVESTMENT_TAG_LABELS,
    INVESTMENT_TAG_RULES,
)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _real(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that count as real money movement (exclude self-transfers + dupes)."""
    if df is None or df.empty:
        return df
    mask = ~_boolcol(df, "is_self_transfer") & ~_boolcol(df, "is_duplicate")
    return df[mask]


def _boolcol(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(False, index=df.index)
    return df[name].fillna(False).astype(bool)


def overview(df: pd.DataFrame) -> dict:
    """Headline metrics with self-transfers and duplicates netted out."""
    if df is None or df.empty:
        return {
            "transactions": 0, "real_received": 0.0, "real_paid": 0.0,
            "net": 0.0, "self_transfer_total": 0.0, "duplicate_total": 0.0,
            "income_total": 0.0, "investment_total": 0.0, "expense_total": 0.0,
            "date_from": None, "date_to": None,
        }

    df = df.copy()
    df["amount"] = _num(df["amount"])
    real = _real(df)

    received = real.loc[real["direction"] == "RECEIVED", "amount"].sum()
    paid = real.loc[real["direction"] == "PAID_OUT", "amount"].sum()

    self_total = df.loc[_boolcol(df, "is_self_transfer"), "amount"].sum()
    dup_total = df.loc[_boolcol(df, "is_duplicate"), "amount"].sum()
    income_total = real.loc[_boolcol(real, "is_income"), "amount"].sum()
    invest_total = real.loc[
        _boolcol(real, "is_investment") & (real["direction"] == "PAID_OUT"), "amount"
    ].sum()

    # "Expense" = real money out that is NOT an investment (savings).
    expense_total = real.loc[
        (real["direction"] == "PAID_OUT") & ~_boolcol(real, "is_investment"), "amount"
    ].sum()

    dts = pd.to_datetime(df["transaction_date"], errors="coerce").dropna()
    return {
        "transactions": int(len(df)),
        "real_transactions": int(len(real)),
        "real_received": float(received),
        "real_paid": float(paid),
        "net": float(received - paid),
        "self_transfer_total": float(self_total),
        "self_transfer_count": int(_boolcol(df, "is_self_transfer").sum()),
        "duplicate_total": float(dup_total),
        "duplicate_count": int(_boolcol(df, "is_duplicate").sum()),
        "income_total": float(income_total),
        "investment_total": float(invest_total),
        "expense_total": float(expense_total),
        "date_from": dts.min().date().isoformat() if not dts.empty else None,
        "date_to": dts.max().date().isoformat() if not dts.empty else None,
    }


def category_breakdown(df: pd.DataFrame) -> list[dict]:
    """Per-category rows/paid/received over REAL transactions only."""
    real = _real(df)
    if real is None or real.empty:
        return []
    real = real.copy()
    real["amount"] = _num(real["amount"])
    rows = []
    for cat, g in real.groupby(real["category"].fillna("unknown")):
        rows.append({
            "category": cat,
            "rows": int(len(g)),
            "paid_out": float(g.loc[g["direction"] == "PAID_OUT", "amount"].sum()),
            "received": float(g.loc[g["direction"] == "RECEIVED", "amount"].sum()),
        })
    return sorted(rows, key=lambda r: r["paid_out"] + r["received"], reverse=True)


def income_breakdown(df: pd.DataFrame) -> dict:
    """Who paid the account holder, and how much, over the whole dataset."""
    real = _real(df)
    if real is None or real.empty:
        return {"by_source": [], "total": 0.0, "rows": []}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    income = real[_boolcol(real, "is_income") & (real["direction"] == "RECEIVED")]
    if income.empty:
        return {"by_source": [], "total": 0.0, "rows": []}

    def _source(desc: str) -> str:
        d = str(desc).lower()
        if "koireader" in d:
            return "KoiReader Technologies (salary)"
        if "primus" in d:
            return "Primus Global (salary)"
        if any(k in d for k in ("refund", "cbdt", "income tax")):
            return "Income-tax refund"
        if "int.pd" in d or "interest" in d:
            return "Bank / FD interest"
        if "cashback" in d or "reward" in d:
            return "Cashback / rewards"
        return "Other income"

    income = income.assign(_src=income["raw_description"].map(_source))
    by_source = []
    for src, g in income.groupby("_src"):
        dts = pd.to_datetime(g["transaction_date"], errors="coerce").dropna()
        by_source.append({
            "source": src,
            "payments": int(len(g)),
            "total": float(g["amount"].sum()),
            "first": dts.min().date().isoformat() if not dts.empty else None,
            "last": dts.max().date().isoformat() if not dts.empty else None,
        })
    by_source.sort(key=lambda r: r["total"], reverse=True)
    return {
        "by_source": by_source,
        "total": float(income["amount"].sum()),
        "rows": _records(income.sort_values("amount", ascending=False)),
    }


def investment_breakdown(df: pd.DataFrame) -> dict:
    """Investments by instrument (Groww, Zerodha, SGB, PPF, FD, ...).

    Uses the investment tags from classification_rules; a single transaction
    can match more than one instrument, so totals are per-tag.
    """
    real = _real(df)
    if real is None or real.empty:
        return {"by_instrument": [], "total": 0.0, "rows": []}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    invest = real[_boolcol(real, "is_investment") & (real["direction"] == "PAID_OUT")]
    if invest.empty:
        return {"by_instrument": [], "total": 0.0, "rows": []}

    tags_series = invest["tags"].fillna("")
    by_instrument = []
    for tag, _ in INVESTMENT_TAG_RULES:
        mask = tags_series.str.contains(rf"(?:^|,){tag}(?:,|$)", regex=True)
        g = invest[mask]
        if g.empty:
            continue
        dts = pd.to_datetime(g["transaction_date"], errors="coerce").dropna()
        by_instrument.append({
            "instrument": INVESTMENT_TAG_LABELS.get(tag, tag),
            "tag": tag,
            "transactions": int(len(g)),
            "total": float(g["amount"].sum()),
            "first": dts.min().date().isoformat() if not dts.empty else None,
            "last": dts.max().date().isoformat() if not dts.empty else None,
        })
    by_instrument.sort(key=lambda r: r["total"], reverse=True)

    # 80C-tagged subset (PPF, ELSS, LIC/insurance, NPS, ...).
    eighty_c = real[real["tags"].fillna("").str.contains("tax_saving_80c")]
    return {
        "by_instrument": by_instrument,
        "total": float(invest["amount"].sum()),
        "tax_saving_80c_total": float(eighty_c.loc[eighty_c["direction"] == "PAID_OUT", "amount"].sum()),
        "tax_saving_80c_count": int(len(eighty_c)),
        "rows": _records(invest.sort_values("amount", ascending=False)),
    }


def person_totals(df: pd.DataFrame, flag_col: str) -> dict:
    """Paid/received/net for a person flag (is_benazir_related, ...)."""
    real = _real(df)
    if real is None or real.empty:
        return {"paid": 0.0, "received": 0.0, "net": 0.0, "count": 0}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    sub = real[_boolcol(real, flag_col)]
    paid = sub.loc[sub["direction"] == "PAID_OUT", "amount"].sum()
    received = sub.loc[sub["direction"] == "RECEIVED", "amount"].sum()
    return {
        "paid": float(paid), "received": float(received),
        "net": float(received - paid), "count": int(len(sub)),
    }


import re as _re


def _counterparty(desc: str) -> str:
    """Best-effort counterparty label from an Indian bank narration.

    Handles the common UPI/NEFT/IMPS/INFT shapes; falls back to a short prefix.
    Heuristic and imperfect — meant to *surface* who recurs, for manual tagging.
    """
    s = str(desc or "").strip()
    if not s:
        return "(blank)"
    low = s.lower()

    # HDFC UPI: "UPI-NAME-vpa@bank-IFSC-..."
    m = _re.match(r"upi-([^-]+)-", low)
    if m:
        return m.group(1).strip().title()
    # ICICI UPI: "UPI/refno/note/vpa/Bank/..." -> prefer the VPA (4th field)
    if low.startswith("upi/"):
        parts = s.split("/")
        for p in parts[1:]:
            if "@" in p:
                return p.strip().lower()
        if len(parts) > 2 and parts[2] and not parts[2].isdigit():
            return parts[2].strip().title()
    # NEFT/IMPS/MMT: "...-NAME-..." pick the longest alphabetic chunk
    if any(low.startswith(k) for k in ("neft", "mmt", "imps", "bil/")):
        chunks = _re.split(r"[/\-]", s)
        words = [c.strip() for c in chunks if _re.search(r"[A-Za-z]{4,}", c)
                 and not _re.search(r"bank|ltd|neft|imps|upi|payment|sent|using|paytm", c.lower())]
        if words:
            return max(words, key=len).strip().title()[:40]
    # Cash deposits etc.
    if "by cash" in low or "cash dep" in low:
        return "Cash deposit"
    return s[:30]


def top_counterparties(df: pd.DataFrame, limit: int = 40) -> list[dict]:
    """Aggregate real (non-self, non-dupe) flows by inferred counterparty.

    Surfaces recurring people/merchants so the user can tag who is who.
    """
    real = _real(df)
    if real is None or real.empty:
        return []
    real = real.copy()
    real["amount"] = _num(real["amount"])
    real["_cp"] = real["raw_description"].map(_counterparty)
    rows = []
    for cp, g in real.groupby("_cp"):
        paid = g.loc[g["direction"] == "PAID_OUT", "amount"].sum()
        received = g.loc[g["direction"] == "RECEIVED", "amount"].sum()
        rows.append({
            "counterparty": cp,
            "transactions": int(len(g)),
            "paid_out": float(paid),
            "received": float(received),
            "net": float(received - paid),
            "gross": float(paid + received),
        })
    rows.sort(key=lambda r: r["gross"], reverse=True)
    return rows[:limit]


def _records(df: pd.DataFrame) -> list[dict]:
    """Lightweight row dicts for JSON (a curated column subset)."""
    cols = [
        "transaction_id", "transaction_date", "source_bank", "description",
        "amount", "direction", "category", "tags",
    ]
    have = [c for c in cols if c in df.columns]
    return df[have].head(2000).to_dict(orient="records")

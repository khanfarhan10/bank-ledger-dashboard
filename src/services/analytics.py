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
from src.utils.config_loader import load_non_expense_categories

# Categories that are money-out but NOT consumption (savings/internal/family).
_NON_EXPENSE = set(load_non_expense_categories())


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
    # astype("boolean") first avoids the object-dtype fillna downcast warning.
    return df[name].astype("boolean").fillna(False).astype(bool)


def _is_expense(df: pd.DataFrame) -> pd.Series:
    """Real money-out that is genuine consumption (not savings/family/investment)."""
    cat = df["category"].fillna("") if "category" in df.columns else pd.Series("", index=df.index)
    return (df["direction"] == "PAID_OUT") & ~cat.isin(_NON_EXPENSE)


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
    family_total = real.loc[
        _boolcol(real, "is_family_savings") & (real["direction"] == "PAID_OUT"), "amount"
    ].sum()

    # "Expense" = real money out that is genuine consumption (excludes
    # investments, family savings, and other internal/non-consumption buckets).
    expense_total = real.loc[_is_expense(real), "amount"].sum()

    status = classification_status(df)
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
        "family_savings_total": float(family_total),
        "expense_total": float(expense_total),
        "approved": status["approved"],
        "unapproved": status["unapproved"],
        "unknown": status["unknown"],
        "date_from": dts.min().date().isoformat() if not dts.empty else None,
        "date_to": dts.max().date().isoformat() if not dts.empty else None,
    }


def classification_status(df: pd.DataFrame) -> dict:
    """Counts of approved / unapproved (auto) / unknown transactions."""
    if df is None or df.empty:
        return {"approved": 0, "unapproved": 0, "unknown": 0, "total": 0}
    approved = _boolcol(df, "is_approved")
    cat = df["category"].fillna("") if "category" in df.columns else pd.Series("", index=df.index)
    is_unknown = cat.isin(["", "unknown"])
    return {
        "approved": int(approved.sum()),
        "unapproved": int((~approved & ~is_unknown).sum()),
        "unknown": int((~approved & is_unknown).sum()),
        "total": int(len(df)),
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


# Income sections: (key, emoji label, predicate on lowercased narration).
_INCOME_SECTIONS = [
    ("salary_koireader", "💼 KoiReader Technologies (base salary)", lambda d: "koireader" in d),
    ("freelance_primus", "🧑‍💻 Primus Global (freelancing)", lambda d: "primus" in d),
    ("insurance_claim", "🏥 Insurance claims (ICICI Lombard)", lambda d: "lombard" in d or "claim" in d),
    ("tax_refund", "💰 Income-tax refunds", lambda d: any(k in d for k in ("refund", "cbdt", "income tax"))),
    ("interest", "🏦 Bank / FD interest", lambda d: "int.pd" in d or "interest" in d),
    ("cashback", "🎁 Cashback & rewards", lambda d: "cashback" in d or "reward" in d),
]


def income_breakdown(df: pd.DataFrame) -> dict:
    """Income grouped into clear sections (salary, freelance, refunds, ...)."""
    real = _real(df)
    if real is None or real.empty:
        return {"sections": [], "total": 0.0}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    # Income = is_income OR the accident insurance claim credit.
    cat = real["category"].fillna("")
    income = real[
        (real["direction"] == "RECEIVED")
        & (_boolcol(real, "is_income") | (cat == "accident_insurance_claim"))
    ]
    if income.empty:
        return {"sections": [], "total": 0.0}

    desc = income["raw_description"].fillna("").str.lower()
    assigned = pd.Series(False, index=income.index)
    sections = []
    for key, label, pred in _INCOME_SECTIONS:
        mask = desc.map(pred) & ~assigned
        g = income[mask]
        assigned = assigned | mask
        if g.empty:
            continue
        dts = pd.to_datetime(g["transaction_date"], errors="coerce").dropna()
        sections.append({
            "key": key, "label": label,
            "payments": int(len(g)), "total": float(g["amount"].sum()),
            "first": dts.min().date().isoformat() if not dts.empty else None,
            "last": dts.max().date().isoformat() if not dts.empty else None,
            "rows": _records(g.sort_values("amount", ascending=False)),
        })
    # Anything left over -> "Other income".
    rest = income[~assigned]
    if not rest.empty:
        sections.append({
            "key": "other", "label": "📦 Other income",
            "payments": int(len(rest)), "total": float(rest["amount"].sum()),
            "first": None, "last": None,
            "rows": _records(rest.sort_values("amount", ascending=False)),
        })
    sections.sort(key=lambda s: s["total"], reverse=True)
    return {"sections": sections, "total": float(income["amount"].sum())}


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
    sub = real[_boolcol(real, flag_col) & (real["category"].fillna("") != "historic_evidence")]
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
        "raw_description", "amount", "direction", "category", "tags",
        "manual_comment", "manual_review_status", "is_approved",
    ]
    have = [c for c in cols if c in df.columns]
    return df[have].head(3000).to_dict(orient="records")


# ---------------------------------------------------------------------------
# Benazir (girlfriend) — dedicated relationship ledger with logical sections.
# Per the user: include Benazir + her mother Nazrana only.
# ---------------------------------------------------------------------------

# Section -> categories that belong to it (in priority order of assignment).
_BENAZIR_SECTIONS = [
    ("iphone", "📱 iPhone 16 Pro Max (for Benazir)", {"benazir_iphone"}),
    ("laptop", "💻 Laptop (for Benazir)", {"benazir_laptop"}),
    ("zara_iphone", "📱 iPhone 16 for Zara (her sister)", {"zara_iphone"}),
    ("loan", "🏦 Axis loan taken for Benazir (repaid by me)", {"benazir_loan_repayment"}),
    ("studies", "📚 Buni's studies & material", {"benazir_studies"}),
]


def _detect_offsets(real: pd.DataFrame) -> dict:
    """Find to-and-fro pairs (sent ~X then received ~X back, within 45 days).

    Returns {transaction_id: {"partner_id", "partner_date", "partner_amount",
    "note"}} for BOTH sides. Such pairs net to ~zero and are crossed out so they
    don't inflate the relationship balance.
    """
    ben = real[(_boolcol(real, "is_benazir_related") | _boolcol(real, "is_nazrana_related"))
               & ~_boolcol(real, "is_manual_entry")].copy()
    if ben.empty:
        return {}
    ben["dt"] = pd.to_datetime(ben["transaction_date"], errors="coerce")
    paid = ben[ben["direction"] == "PAID_OUT"].sort_values("dt")
    recv = ben[ben["direction"] == "RECEIVED"].sort_values("dt")
    used, offsets = set(), {}
    for _, p in paid.iterrows():
        for _, r in recv.iterrows():
            rid = r["transaction_id"]
            if rid in used or p["transaction_id"] in offsets:
                continue
            if abs(p["amount"] - r["amount"]) <= max(1.0, 0.02 * p["amount"]) \
                    and pd.notna(p["dt"]) and pd.notna(r["dt"]) and abs((r["dt"] - p["dt"]).days) <= 45:
                used.add(rid)
                offsets[p["transaction_id"]] = {
                    "partner_id": rid, "partner_date": str(r["transaction_date"]),
                    "partner_amount": float(r["amount"]),
                    "note": f"Resolved — {fmt_amt(r['amount'])} received back on {r['transaction_date']}",
                }
                offsets[rid] = {
                    "partner_id": p["transaction_id"], "partner_date": str(p["transaction_date"]),
                    "partner_amount": float(p["amount"]),
                    "note": f"Resolved — offsets {fmt_amt(p['amount'])} paid on {p['transaction_date']}",
                }
                break
    return offsets


def fmt_amt(x) -> str:
    try:
        return f"₹{float(x):,.0f}"
    except (TypeError, ValueError):
        return str(x)


def _s(v) -> str:
    """NA/None-safe string ('' for missing) — avoids 'pd.NA or ...' ambiguity."""
    try:
        if v is None or pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v)


def _member_dict(r, tid, label, historic, off) -> dict:
    """One subchild transaction, including bank + Paytm reference details."""
    bank_ref = _s(r.get("raw_description"))
    paytm_ref = _s(r.get("counterparty_name"))   # Paytm payee folded in via RRN dedup
    rrn = _s(r.get("reference_number"))
    return {
        "transaction_id": tid, "transaction_date": r["transaction_date"],
        "source_bank": r["source_bank"], "description": r["description"],
        "raw_description": bank_ref, "amount": float(r["amount"]),
        "direction": r["direction"], "member_label": label,
        "historic": bool(historic), "is_approved": bool(r.get("is_approved")),
        "manual_comment": _na(r.get("manual_comment")),
        "bank_ref": bank_ref, "paytm_ref": paytm_ref, "reference_number": rrn,
        "offset": bool(off), "offset_partner": (off or {}).get("partner_id"),
        "offset_note": (off or {}).get("note"),
    }


def _na(v):
    try:
        return None if v is None or pd.isna(v) else v
    except (TypeError, ValueError):
        return v


def _group_children(rows: list) -> list:
    """Group member rows by their label into CHILD buckets (parent→child→subchild).

    Each child carries a subtotal (paid/received/net) over its non-historic,
    non-offset subchildren. Children are ordered latest-first.
    """
    groups, order = {}, []
    for r in rows:
        key = r.get("child_group") or r.get("member_label") or "—"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    children = []
    for key in order:
        members = groups[key]
        paid = sum(m["amount"] for m in members if m["direction"] == "PAID_OUT" and not m["historic"] and not m["offset"])
        recv = sum(m["amount"] for m in members if m["direction"] == "RECEIVED" and not m["historic"] and not m["offset"])
        dts = [str(m["transaction_date"]) for m in members if m["transaction_date"]]
        children.append({
            "label": key, "count": len(members),
            "paid": float(paid), "received": float(recv), "net": float(paid - recv),
            "base_date": (min(dts) if dts else None),
            "all_historic": all(m["historic"] for m in members),
            "members": members,
        })
    children.sort(key=lambda c: c["base_date"] or "", reverse=True)
    return children


def benazir_analytics(df: pd.DataFrame, store=None) -> dict:
    """Benazir ledger organised as MASTERS (SUMMARY-A, B, ...) + general.

    Each master pulls its members from the master_members table (assigned by the
    seeder / user), sorted latest-first. The master's net is its declared
    summary_amount if set, else paid − received over its non-historic members.
    Anything Benazir/Nazrana-related not in a master falls under 'General'.
    """
    real = _real(df)
    if real is None or real.empty:
        return {"summary": {}, "masters": []}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    rel_mask = _boolcol(real, "is_benazir_related") | _boolcol(real, "is_nazrana_related")

    masters_df = store.get_masters_df() if store is not None else pd.DataFrame()
    members_df = store.get_master_members_df() if store is not None else pd.DataFrame()
    member_of = {}
    if not members_df.empty:
        for _, mm in members_df.iterrows():
            cg = mm["child_group"] if "child_group" in members_df.columns else ""
            member_of[mm["transaction_id"]] = (mm["code"], mm["label"], bool(mm["historic"]), _s(cg))

    by_txn = {r["transaction_id"]: r for _, r in real.iterrows()}
    offsets = _detect_offsets(real)   # to-and-fro pairs, crossed out

    masters = []
    claimed_ids = set()
    for _, mrow in (masters_df.iterrows() if not masters_df.empty else []):
        code = mrow["code"]
        mem_ids = [tid for tid, v in member_of.items() if v[0] == code]
        rows, paid, received = [], 0.0, 0.0
        dates = []
        for tid in mem_ids:
            claimed_ids.add(tid)
            r = by_txn.get(tid)
            if r is None:
                continue
            _, label, historic, child_group = member_of[tid]
            amt = float(r["amount"])
            off = offsets.get(tid)
            # Offset (to-and-fro) and historic rows don't count toward the net.
            if not historic and not off:
                if r["direction"] == "PAID_OUT":
                    paid += amt
                elif r["direction"] == "RECEIVED":
                    received += amt
            dates.append(str(r["transaction_date"]))
            md = _member_dict(r, tid, label, historic, off)
            md["child_group"] = child_group or label or "Other"
            rows.append(md)
        rows.sort(key=lambda x: str(x["transaction_date"]), reverse=True)  # latest first
        children = _group_children(rows)
        declared = mrow["summary_amount"]
        net = float(declared) if pd.notna(declared) and declared is not None else (paid - received)
        masters.append({
            "code": code, "title": mrow["title"], "detail": mrow["detail"],
            "base_date": mrow["base_date"] or (min(dates) if dates else None),
            "kind": mrow["kind"], "net": net, "paid": paid, "received": received,
            "count": len(rows), "declared": pd.notna(declared) and declared is not None,
            "members": rows, "children": children,
        })

    # General = Benazir/Nazrana-related, not in any master, not historic.
    rel = real[rel_mask]
    rel = rel[~rel["transaction_id"].isin(claimed_ids)]
    rel = rel[rel["category"].fillna("") != "historic_evidence"]
    # Net excludes offset (to-and-fro) rows.
    not_off = ~rel["transaction_id"].isin(offsets)
    gpaid = float(rel.loc[(rel["direction"] == "PAID_OUT") & not_off, "amount"].sum())
    grecv = float(rel.loc[(rel["direction"] == "RECEIVED") & not_off, "amount"].sum())
    gmembers = []
    for _, r in rel.sort_values("amount", ascending=False).iterrows():
        off = offsets.get(r["transaction_id"])
        gmembers.append(_member_dict(r, r["transaction_id"], "", False, off))
    general = {
        "code": "GEN", "title": "General payments (uncategorised)",
        "detail": "Small / one-off payments to Benazir not part of a master. "
                  f"{sum(1 for m in gmembers if m['offset'])} crossed-out rows are to-and-fro (resolved).",
        "base_date": None, "kind": "expense",
        "net": gpaid - grecv, "paid": gpaid, "received": grecv,
        "count": int(len(rel)), "declared": False, "members": gmembers, "children": [],
    }

    billed = sum(m["net"] for m in masters) + general["net"]
    summary = {
        "total_billed": float(billed),
        "masters_total": float(sum(m["net"] for m in masters)),
        "general_total": float(general["net"]),
        "master_count": len(masters),
        "txn_count": int(rel_mask.sum()),
    }
    return {"summary": summary, "masters": masters + [general]}


# ---------------------------------------------------------------------------
# My family — mother (Husna) + sister (Zarinne) as self-investment, with a
# user-overridable "saved" amount (default = net sent).
# ---------------------------------------------------------------------------

def family_analytics(df: pd.DataFrame, store=None) -> dict:
    """Mother + sister sections with sent/received and overridable saved."""
    real = _real(df)
    people = []
    spec = [("mother", "Husna Ara Bano (Mother)", "is_mother_related"),
            ("sister", "Zarinne (Sister)", "is_sister_related")]
    if real is None or real.empty:
        return {"people": [{"key": k, "label": l, "sent": 0, "received": 0,
                            "net": 0, "saved": 0, "count": 0, "rows": []} for k, l, _ in spec]}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    for key, label, flag in spec:
        g = real[_boolcol(real, flag)]
        sent = float(g.loc[g["direction"] == "PAID_OUT", "amount"].sum())
        received = float(g.loc[g["direction"] == "RECEIVED", "amount"].sum())
        net = sent - received
        override = store.get_family_override(key) if store is not None else None
        saved = float(override["total_saved"]) if override and override.get("total_saved") is not None else net
        people.append({
            "key": key, "label": label,
            "sent": sent, "received": received, "net": net,
            "saved": saved, "saved_is_override": bool(override),
            "note": (override or {}).get("note", ""),
            "count": int(len(g)),
            "rows": _records(g.sort_values("transaction_date")),
        })
    return {"people": people}


# ---------------------------------------------------------------------------
# Accident (08 Feb 2024) and marriage (29 Apr 2023) period analytics.
# ---------------------------------------------------------------------------

_ACCIDENT_CATS = {"accident_medical", "accident_surgery", "accident_medicine",
                  "accident_hospital", "accident_recovery", "physio_therapist_hamid",
                  "accident_insurance_claim"}


def accident_analytics(df: pd.DataFrame) -> dict:
    """Accident claim + post-accident medical/recovery spend (auto; confirm)."""
    real = _real(df)
    if real is None or real.empty:
        return {"claim": 0.0, "spend": 0.0, "by_category": [], "rows": []}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    sub = real[real["category"].fillna("").isin(_ACCIDENT_CATS)]
    claim = float(sub.loc[sub["category"] == "accident_insurance_claim", "amount"].sum())
    spend = float(sub.loc[sub["direction"] == "PAID_OUT", "amount"].sum())
    by_category = []
    for c, g in sub.groupby("category"):
        by_category.append({"category": c, "count": int(len(g)),
                            "total": float(g["amount"].sum())})
    by_category.sort(key=lambda r: r["total"], reverse=True)
    return {
        "claim": claim, "spend": spend, "net": spend - claim,
        "by_category": by_category,
        "rows": _records(sub.sort_values("transaction_date")),
    }


def marriage_analytics(df: pd.DataFrame) -> dict:
    """Large payments around Zarinne's marriage (auto-classified; confirm)."""
    real = _real(df)
    if real is None or real.empty:
        return {"total": 0.0, "rows": []}
    real = real.copy()
    real["amount"] = _num(real["amount"])
    sub = real[real["category"].fillna("") == "marriage_expense"]
    return {
        "total": float(sub.loc[sub["direction"] == "PAID_OUT", "amount"].sum()),
        "count": int(len(sub)),
        "rows": _records(sub.sort_values("transaction_date")),
    }


# ---------------------------------------------------------------------------
# Chart data for the Overview page (pies + monthly trend).
# ---------------------------------------------------------------------------

def chart_data(df: pd.DataFrame) -> dict:
    """Pie + bar data for the interactive Overview charts."""
    real = _real(df)
    if real is None or real.empty:
        return {"expense_by_category": [], "income_by_source": [],
                "monthly": [], "money_flow": []}
    real = real.copy()
    real["amount"] = _num(real["amount"])

    # Expense by category (consumption only).
    exp = real[_is_expense(real)]
    by_cat = (exp.groupby(exp["category"].fillna("unknown"))["amount"].sum()
              .sort_values(ascending=False))
    expense_by_category = [{"label": k, "value": float(v)} for k, v in by_cat.items()]

    # Income by section.
    inc = income_breakdown(df)
    income_by_source = [{"label": s["label"], "value": s["total"]} for s in inc["sections"]]

    # Monthly income vs expense trend.
    real["_m"] = pd.to_datetime(real["transaction_date"], errors="coerce").dt.to_period("M")
    monthly = []
    for m, g in real.dropna(subset=["_m"]).groupby("_m"):
        income_m = g.loc[_boolcol(g, "is_income"), "amount"].sum()
        expense_m = g.loc[_is_expense(g), "amount"].sum()
        monthly.append({"month": str(m), "income": float(income_m), "expense": float(expense_m)})
    monthly.sort(key=lambda r: r["month"])

    ov = overview(df)
    money_flow = [
        {"label": "Real income", "value": ov["income_total"]},
        {"label": "Real expense", "value": ov["expense_total"]},
        {"label": "Invested", "value": ov["investment_total"]},
        {"label": "Family savings", "value": ov["family_savings_total"]},
        {"label": "Self-transfers (excluded)", "value": ov["self_transfer_total"]},
    ]
    return {
        "expense_by_category": expense_by_category,
        "income_by_source": income_by_source,
        "monthly": monthly,
        "money_flow": money_flow,
    }


def search(df: pd.DataFrame, *, q="", min_amount=None, max_amount=None,
           date_from=None, date_to=None, direction="", category="",
           bank="", person="") -> list[dict]:
    """Generic filter/search over the ledger for the Search page."""
    if df is None or df.empty:
        return []
    v = df.copy()
    v["amount"] = _num(v["amount"])
    if q:
        hay = (v["description"].fillna("") + " " + v["raw_description"].fillna("")).str.lower()
        v = v[hay.str.contains(str(q).lower(), regex=False)]
    if min_amount is not None:
        v = v[v["amount"] >= float(min_amount)]
    if max_amount is not None:
        v = v[v["amount"] <= float(max_amount)]
    dts = pd.to_datetime(v["transaction_date"], errors="coerce")
    if date_from:
        v = v[dts >= pd.Timestamp(date_from)]
        dts = pd.to_datetime(v["transaction_date"], errors="coerce")
    if date_to:
        v = v[dts <= pd.Timestamp(date_to)]
    if direction:
        v = v[v["direction"] == direction]
    if category:
        v = v[v["category"].fillna("") == category]
    if bank:
        v = v[v["source_bank"] == bank]
    if person:
        flag = {"benazir": "is_benazir_related", "nazrana": "is_nazrana_related",
                "mother": "is_mother_related", "sister": "is_sister_related"}.get(person)
        if flag:
            v = v[_boolcol(v, flag)]
    return _records(v.sort_values("transaction_date", ascending=False))

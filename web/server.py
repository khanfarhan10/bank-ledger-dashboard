"""FastAPI server: JSON API + single-page Tabulator dashboard.

Run with:  python run_web.py     (or: uvicorn web.server:app --reload)

All processing is local. The frontend (templates/index.html + static/) talks to
the /api/* endpoints below, which are thin wrappers over the service layer and
the DecisionStore. Source statements under all_bank_statements/ are never
written to — only data/cache/decisions.sqlite changes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.services import analytics
from web.state import STATE

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Bank Ledger Dashboard", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- helpers ----------------------------------------------------------------

# Columns surfaced to the interactive grid (lean but complete enough to act on).
GRID_COLUMNS = [
    "transaction_id", "transaction_date", "source_bank", "description",
    "amount", "direction", "category", "tags", "detected_names",
    "manual_review_status", "manual_comment", "manual_flags",
    "is_self_transfer", "is_income", "is_investment", "is_family_savings",
    "is_large_payment", "is_duplicate", "is_approved", "is_manual_entry",
    "is_benazir_related", "is_nazrana_related", "is_mother_related",
    "is_sister_related", "raw_description",
]


def _clean(records: list[dict]) -> list[dict]:
    """Make DataFrame records JSON-safe (NaN/NA -> None, numpy -> python)."""
    out = []
    for r in records:
        row = {}
        for k, v in r.items():
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                row[k] = None
            elif v is pd.NA or v is None:
                row[k] = None
            elif isinstance(v, (np.bool_,)):
                row[k] = bool(v)
            elif isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = float(v)
            else:
                try:
                    if pd.isna(v):
                        row[k] = None
                        continue
                except (TypeError, ValueError):
                    pass
                row[k] = v
        out.append(row)
    return out


def _grid_rows(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    have = [c for c in GRID_COLUMNS if c in df.columns]
    return _clean(df[have].to_dict(orient="records"))


# --- page -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


# --- meta -------------------------------------------------------------------

@app.get("/api/meta")
def meta() -> dict:
    aliases = STATE.aliases
    persons = [
        {"key": k, "label": (v or {}).get("display_name", k)}
        for k, v in aliases.items()
    ]
    return {
        "categories": STATE.categories,
        "review_statuses": STATE.review_statuses,
        "persons": persons,
        "threshold": STATE.threshold,
    }


# --- overview ---------------------------------------------------------------

@app.get("/api/overview")
def overview() -> dict:
    ledger = STATE.ledger()
    ext = STATE.extraction()
    ov = analytics.overview(ledger)
    ov["categories"] = analytics.category_breakdown(ledger)
    ov["charts"] = analytics.chart_data(ledger)
    ov["overall_gaps"] = ext.get("overall_gaps", [])
    ov["files"] = len(ext.get("reports", []))
    ov["paytm_merge"] = ext.get("paytm_merge", {})
    return ov


@app.get("/api/classification-status")
def classification_status() -> dict:
    return analytics.classification_status(STATE.ledger())


# --- ledger -----------------------------------------------------------------

@app.get("/api/ledger")
def ledger() -> dict:
    df = STATE.ledger()
    return {"rows": _grid_rows(df), "count": int(len(df)) if df is not None else 0}


@app.get("/api/extraction")
def extraction() -> dict:
    ext = STATE.extraction()
    return {
        "reports": _clean(ext.get("reports", [])),
        "overall_gaps": ext.get("overall_gaps", []),
    }


# --- Benazir (dedicated relationship ledger, organised as masters) ----------

@app.get("/api/benazir")
def benazir() -> dict:
    data = analytics.benazir_analytics(STATE.ledger(), STATE.store)
    # JSON-safe the nested member dicts.
    for m in data.get("masters", []):
        m["members"] = _clean(m.get("members", []))
    return data


class MasterEditIn(BaseModel):
    code: str
    title: str | None = None
    detail: str | None = None
    base_date: str | None = None
    summary_amount: float | None = None


@app.post("/api/benazir/master")
def edit_master(body: MasterEditIn) -> dict:
    STATE.store.update_master(
        body.code, title=body.title, detail=body.detail,
        base_date=body.base_date, summary_amount=body.summary_amount,
    )
    STATE.invalidate_decisions()
    return {"ok": True}


@app.get("/api/benazir/export.csv")
def export_benazir_csv():
    import csv
    import io

    from fastapi.responses import StreamingResponse

    data = analytics.benazir_analytics(STATE.ledger(), STATE.store)
    sv = lambda x: "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Ref", "Date", "Type", "Title / Description", "Paid (₹)",
                "Received (₹)", "Net (₹)", "Historic", "Note"])
    for m in data.get("masters", []):
        w.writerow([
            f"SUMMARY-{m['code']}", sv(m.get("base_date")), "MASTER",
            sv(m.get("title")), f"{m.get('paid', 0):.0f}",
            f"{m.get('received', 0):.0f}", f"{m.get('net', 0):.0f}",
            "", sv(m.get("detail")),
        ])
        for i, mem in enumerate(_clean(m.get("members", [])), start=1):
            amt = mem.get("amount") or 0
            paid = amt if mem.get("direction") == "PAID_OUT" else 0
            recv = amt if mem.get("direction") == "RECEIVED" else 0
            status = "historic" if mem.get("historic") else ("resolved (to-and-fro)" if mem.get("offset") else "")
            note = sv(mem.get("offset_note")) or sv(mem.get("manual_comment"))
            w.writerow([
                f"{m['code']}.{i}", sv(mem.get("transaction_date")), "detail",
                sv(mem.get("member_label")) or sv(mem.get("description")),
                f"{paid:.0f}", f"{recv:.0f}", "", status, note,
            ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=benazir_ledger.csv"},
    )


# --- search (generic filter page) -------------------------------------------

@app.get("/api/search")
def search(
    q: str = "", min_amount: float | None = None, max_amount: float | None = None,
    date_from: str = "", date_to: str = "", direction: str = "",
    category: str = "", bank: str = "", person: str = "",
) -> dict:
    rows = analytics.search(
        STATE.ledger(), q=q, min_amount=min_amount, max_amount=max_amount,
        date_from=date_from or None, date_to=date_to or None,
        direction=direction, category=category, bank=bank, person=person,
    )
    return {"rows": _clean(rows), "count": len(rows)}


@app.get("/api/counterparties")
def counterparties() -> dict:
    return {"counterparties": analytics.top_counterparties(STATE.ledger(), 50)}


# --- family (mother + sister) -----------------------------------------------

@app.get("/api/family")
def family() -> dict:
    return analytics.family_analytics(STATE.ledger(), STATE.store)


class FamilyOverrideIn(BaseModel):
    person: str
    total_saved: float
    note: str = ""


@app.post("/api/family/override")
def family_override(body: FamilyOverrideIn) -> dict:
    STATE.store.set_family_override(body.person, body.total_saved, body.note)
    return {"ok": True}


# --- accident / marriage ----------------------------------------------------

@app.get("/api/accident")
def accident() -> dict:
    return analytics.accident_analytics(STATE.ledger())


@app.get("/api/marriage")
def marriage() -> dict:
    return analytics.marriage_analytics(STATE.ledger())


# --- investments / income ---------------------------------------------------

@app.get("/api/investments")
def investments() -> dict:
    return analytics.investment_breakdown(STATE.ledger())


@app.get("/api/income")
def income() -> dict:
    return analytics.income_breakdown(STATE.ledger())


# --- large ------------------------------------------------------------------

@app.get("/api/large")
def large(threshold: float | None = None) -> dict:
    df = STATE.ledger()
    if df is None or df.empty:
        return {"rows": [], "threshold": STATE.threshold}
    thr = STATE.threshold if threshold is None else float(threshold)
    amt = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    sub = df[amt >= thr].sort_values("amount", ascending=False)
    return {"rows": _grid_rows(sub), "threshold": thr, "count": int(len(sub))}


# --- manual entries ---------------------------------------------------------

class ManualEntryIn(BaseModel):
    entry_date: str
    person: str = ""
    amount: float = 0.0
    direction: str = "PAID_OUT"
    category: str = ""
    description: str = ""
    reason: str = ""
    evidence_note: str = ""


@app.get("/api/manual-entries")
def manual_entries() -> dict:
    df = STATE.store.get_manual_entries_df()
    return {"rows": _clean(df.to_dict(orient="records")) if not df.empty else []}


@app.post("/api/manual-entries")
def add_manual_entry(entry: ManualEntryIn) -> dict:
    eid = STATE.store.add_manual_entry(
        entry_date=entry.entry_date, person=entry.person, amount=entry.amount,
        direction=entry.direction, category=entry.category,
        description=entry.description, reason=entry.reason,
        evidence_note=entry.evidence_note,
    )
    STATE.invalidate_decisions()
    return {"ok": True, "manual_entry_id": eid}


@app.delete("/api/manual-entries/{entry_id}")
def delete_manual_entry(entry_id: str) -> dict:
    STATE.store.delete_manual_entry(entry_id, reason="Deleted from web UI")
    STATE.invalidate_decisions()
    return {"ok": True}


class LinkIn(BaseModel):
    manual_entry_id: str
    transaction_id: str


@app.post("/api/manual-entries/link")
def link_manual_entry(link: LinkIn) -> dict:
    STATE.store.add_link(link.manual_entry_id, link.transaction_id)
    STATE.invalidate_decisions()
    return {"ok": True}


# --- decisions (the heart of the interactive grid) --------------------------

class DecisionIn(BaseModel):
    transaction_id: str
    category: str | None = None
    manual_review_status: str | None = None
    manual_person: str | None = None
    manual_comment: str | None = None
    manual_flags: str | None = None
    reason: str | None = "Edited via web dashboard"


@app.post("/api/decision")
def save_decision(dec: DecisionIn) -> dict:
    if not dec.transaction_id:
        raise HTTPException(status_code=400, detail="transaction_id required")
    STATE.store.save_decision(
        dec.transaction_id,
        category=dec.category,
        manual_review_status=dec.manual_review_status,
        manual_person=dec.manual_person,
        manual_comment=dec.manual_comment,
        manual_flags=dec.manual_flags,
        reason=dec.reason,
    )
    STATE.invalidate_decisions()
    return {"ok": True}


class ResetIn(BaseModel):
    transaction_id: str


@app.post("/api/decision/reset")
def reset_decision(body: ResetIn) -> dict:
    STATE.store.reset_decision(body.transaction_id, reason="Reset via web dashboard")
    STATE.invalidate_decisions()
    return {"ok": True}


# --- approval workflow (confirm / deny / bulk) ------------------------------

class ConfirmIn(BaseModel):
    transaction_id: str


@app.post("/api/decision/confirm")
def confirm_decision(body: ConfirmIn) -> dict:
    """Approve the current auto-classification as-is (keeps the category)."""
    STATE.store.save_decision(
        body.transaction_id, manual_review_status="confirmed_related",
        reason="Confirmed auto-classification",
    )
    STATE.invalidate_decisions()
    return {"ok": True}


@app.post("/api/decision/deny")
def deny_decision(body: ConfirmIn) -> dict:
    """Reject the auto-classification -> send the row to 'unknown'."""
    STATE.store.save_decision(
        body.transaction_id, category="unknown", manual_review_status="not_related",
        reason="Denied auto-classification",
    )
    STATE.invalidate_decisions()
    return {"ok": True}


class BulkApproveIn(BaseModel):
    transaction_ids: list[str]


@app.post("/api/decision/bulk-approve")
def bulk_approve(body: BulkApproveIn) -> dict:
    for tid in body.transaction_ids:
        STATE.store.save_decision(
            tid, manual_review_status="confirmed_related",
            reason="Bulk-approved",
        )
    STATE.invalidate_decisions()
    return {"ok": True, "count": len(body.transaction_ids)}


# --- threshold / refresh ----------------------------------------------------

class ThresholdIn(BaseModel):
    value: float


@app.post("/api/threshold")
def set_threshold(body: ThresholdIn) -> dict:
    STATE.set_threshold(body.value)
    return {"ok": True, "threshold": STATE.threshold}


@app.post("/api/refresh")
def refresh() -> dict:
    STATE.refresh()
    return {"ok": True}


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})

"""Seed the Benazir ledger: structured MASTERS first, then general payments.

Run once after setup (idempotent — clears and re-applies):
    python scripts/seed_benazir.py

Masters (config/benazir_masters.yml) are the structured expenses (iPhone, Zara,
Axis loan, studies, Kotak, salary-replacement, rent, job-comp). Each member is
matched to a real bank/Paytm row where possible, else added as a manual entry,
and assigned to the master. General reasons (config/benazir_reasons.yml) are the
small leftover payments; any (date, amount) already claimed by a master is
skipped to avoid double counting.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.decision_store import DecisionStore  # noqa: E402
from src.services.pipeline import (  # noqa: E402
    effective_aliases, effective_threshold,
    extract_normalize_classify, finalize_ledger,
)

SOURCE_DIR = "all_bank_statements"
MASTER_CATEGORY = {
    "A": "benazir_iphone", "B": "zara_iphone", "C": "benazir_loan_repayment",
    "D": "benazir_studies", "E": "insurance", "F": "benazir_payments",
    "G": "benazir_payments", "H": "benazir_payments",
    "I": "benazir_laptop", "J": "benazir_payments",
}


def _match(ledger, date, amount, direction=None, tol=1.0, day_window=3):
    """Find a real row by amount (tight) within +/- days; optional direction."""
    amt = pd.to_numeric(ledger["amount"], errors="coerce")
    tdate = pd.to_datetime(ledger["transaction_date"], errors="coerce")
    target = pd.Timestamp(date)
    dd = (tdate - target).abs().dt.days
    not_self = ~ledger["is_self_transfer"].fillna(False).astype(bool)
    sel = ((amt - float(amount)).abs() <= tol) & (dd <= day_window) & not_self
    if direction:
        sel = sel & (ledger["direction"].fillna("") == direction)
    hits = ledger[sel].copy()
    if hits.empty:
        return []
    hits["_dd"] = dd[hits.index]
    hits["_ben"] = ~ledger["is_benazir_related"].fillna(False).astype(bool)[hits.index]
    return hits.sort_values(["_ben", "_dd"])["transaction_id"].tolist()


def main() -> None:
    masters = (yaml.safe_load(Path("config/benazir_masters.yml").read_text(encoding="utf-8")) or {}).get("masters", [])
    reasons = (yaml.safe_load(Path("config/benazir_reasons.yml").read_text(encoding="utf-8")) or {}).get("rows", [])

    store = DecisionStore()
    # Clean slate for re-seeding (keeps user header edits? No — full reseed).
    me = store.get_manual_entries_df()
    for eid in (me["manual_entry_id"].tolist() if not me.empty else []):
        store.delete_manual_entry(eid, reason="reseed")
    dec = store.get_decisions_df()
    for tid in (dec["transaction_id"].tolist() if not dec.empty else []):
        store.reset_decision(tid, reason="reseed")

    aliases = effective_aliases(store)
    threshold = effective_threshold(store)
    classified = extract_normalize_classify(SOURCE_DIR, aliases, threshold)["classified"]
    ledger = finalize_ledger(classified, store, threshold)

    used_ids: set[str] = set()
    claimed: set[tuple] = set()

    def make_manual(date, amount, direction, category, label):
        return store.add_manual_entry(
            entry_date=str(date), person="benazir", amount=float(amount),
            direction=direction or "PAID_OUT", category=category,
            description=label, reason=label,
        )

    # ---- masters ----
    for i, m in enumerate(masters):
        code = m["code"]
        store.upsert_master(code, m.get("title", code), m.get("detail", ""),
                            str(m.get("base_date", "")), m.get("summary_amount"),
                            m.get("kind", "expense"), i)
        store.clear_master_members(code)
        member_dates = []
        for mem in m.get("members", []):
            historic = bool(mem.get("historic"))
            cat = "historic_evidence" if historic else MASTER_CATEGORY.get(code, "benazir_payments")
            direction = mem.get("direction", "PAID_OUT")
            label = mem.get("label", "")
            tid = None
            if not mem.get("manual"):
                ids = [x for x in _match(ledger, mem["date"], mem["amount"], direction) if x not in used_ids]
                if ids:
                    tid = ids[0]
                    store.save_decision(tid, category=cat, manual_comment=label,
                                        manual_person="benazir", reason=f"Master {code}")
            if tid is None:
                tid = make_manual(mem["date"], mem["amount"], direction, cat, label)
            used_ids.add(tid)
            claimed.add((str(mem["date"]), round(float(mem["amount"]))))
            store.set_master_member(code, tid, label, historic)
            member_dates.append(str(mem["date"]))
        # base_date default = earliest member date
        if not m.get("base_date") and member_dates:
            store.update_master(code, base_date=min(member_dates))
    print(f"Seeded {len(masters)} masters.")

    # ---- general reasons (skip master-claimed) ----
    applied = recalled = 0
    for r in reasons:
        key = (str(r["date"]), round(float(r["amount"])))
        if key in claimed:
            continue
        ids = [x for x in _match(ledger, r["date"], r["amount"]) if x not in used_ids]
        # restrict generic notes to Benazir-flagged rows
        ids = [x for x in ids if bool(ledger.loc[ledger["transaction_id"] == x, "is_benazir_related"].fillna(False).any())]
        if ids:
            used_ids.add(ids[0])
            store.save_decision(ids[0], manual_comment=r.get("reason") or None,
                                manual_person="benazir", reason="General reason")
            applied += 1
        else:
            make_manual(r["date"], r["amount"], "PAID_OUT", "benazir_payments",
                        (r.get("reason") or f"Benazir payment (recalled) ₹{r['amount']:.0f}")
                        + " [recalled — not a single matched txn]")
            recalled += 1
    print(f"General: {applied} attached to bank rows, {recalled} recalled manual entries.")


if __name__ == "__main__":
    main()

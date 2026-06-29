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
    "M": "benazir_laptop", "N": "rent",
}


def _group_ids(ledger, mem, used_ids):
    """Return real transaction_ids for an aggregated member (handle/month).

    group: 'handle' -> all rows whose raw_description contains `handle` in `month`.
    group: 'month'  -> all Benazir/Nazrana-flagged rows in `month`.
    Excludes manual entries and ids already claimed by another master.
    """
    dt = pd.to_datetime(ledger["transaction_date"], errors="coerce")
    ym = dt.dt.to_period("M").astype(str)
    is_manual = ledger["is_manual_entry"].fillna(False).astype(bool)
    is_ben = ledger["is_benazir_related"].fillna(False).astype(bool) | \
        ledger["is_nazrana_related"].fillna(False).astype(bool)
    sel = (ym == mem["month"]) & ~is_manual
    if mem["group"] == "handle":
        raw = ledger["raw_description"].fillna("").astype(str).str.contains(mem["handle"], case=False, regex=False)
        sel = sel & raw
    else:  # month: all Benazir-flagged that month
        sel = sel & is_ben
    return [tid for tid in ledger.loc[sel, "transaction_id"].tolist() if tid not in used_ids]


def _match(ledger, date, amount, direction=None, tol=1.0, day_window=3,
           benazir_only=True):
    """Find a real row by amount (tight) within +/- days; optional direction.

    benazir_only (default True): ONLY consider rows flagged Benazir/Nazrana-
    related. This is critical — without it the matcher silently grabbed
    unrelated same-amount rows (e.g. a Hazaribag computer-shop payment or a
    cash withdrawal), then stamped them Benazir. Masters must never invent a
    link to a transaction that isn't actually hers.
    """
    amt = pd.to_numeric(ledger["amount"], errors="coerce")
    tdate = pd.to_datetime(ledger["transaction_date"], errors="coerce")
    target = pd.Timestamp(date)
    dd = (tdate - target).abs().dt.days
    not_self = ~ledger["is_self_transfer"].fillna(False).astype(bool)
    is_ben = ledger["is_benazir_related"].fillna(False).astype(bool) | \
        ledger["is_nazrana_related"].fillna(False).astype(bool)
    sel = ((amt - float(amount)).abs() <= tol) & (dd <= day_window) & not_self
    if benazir_only:
        sel = sel & is_ben
    if direction:
        sel = sel & (ledger["direction"].fillna("") == direction)
    hits = ledger[sel].copy()
    if hits.empty:
        return []
    hits["_dd"] = dd[hits.index]
    hits["_ben"] = ~is_ben[hits.index]
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
    # Config is the source of truth: drop ALL masters (headers + member links)
    # first, so edited titles/details apply and masters removed from the config
    # (e.g. the bogus K/L) disappear instead of lingering in the DB.
    for code in store.all_master_codes():
        store.delete_master(code)

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
    # Two passes so that EXPLICIT (match/manual) members claim their real rows
    # BEFORE any month/handle GROUP aggregation runs. Otherwise a broad month
    # aggregation (e.g. Master F "all May payments") could swallow a row that a
    # specific master (e.g. the laptop-repair cluster) should own — and the
    # specific master would then find nothing left to match.
    member_dates: dict[str, list] = {}
    skipped = 0
    for i, m in enumerate(masters):
        code = m["code"]
        store.upsert_master(code, m.get("title", code), m.get("detail", ""),
                            str(m.get("base_date", "")), m.get("summary_amount"),
                            m.get("kind", "expense"), i)
        store.clear_master_members(code)
        member_dates[code] = []

    # Pass 1 — explicit members (real-row matches + legitimate manual entries).
    for m in masters:
        code = m["code"]
        default_child = m.get("title", code)
        for mem in m.get("members", []):
            if mem.get("group"):
                continue
            historic = bool(mem.get("historic"))
            cat = "historic_evidence" if historic else MASTER_CATEGORY.get(code, "benazir_payments")
            direction = mem.get("direction", "PAID_OUT")
            label = mem.get("label", "")
            child = mem.get("child") or default_child

            tid = None
            if not mem.get("manual"):
                # `any: true` opts a member out of the Benazir-only guard — used
                # only for declared, precise, large non-person rows (loan
                # disbursal to me, an insurance premium/refund), never for
                # generic amounts.
                ids = [x for x in _match(ledger, mem["date"], mem["amount"], direction,
                                         tol=mem.get("tol", 1.0),
                                         day_window=mem.get("day_window", 3),
                                         benazir_only=not mem.get("any"))
                       if x not in used_ids]
                if ids:
                    tid = ids[0]
                    store.save_decision(tid, category=cat, manual_comment=label,
                                        manual_person="benazir", reason=f"Master {code}")
                else:
                    # No genuine Benazir/Nazrana row -> do NOT fabricate a match.
                    print(f"  ! {code}: no Benazir row for {mem['date']} ₹{mem['amount']:.0f} ({label}) — skipped")
                    skipped += 1
                    continue
            else:
                tid = make_manual(mem["date"], mem["amount"], direction, cat, label)
            used_ids.add(tid)
            claimed.add((str(mem["date"]), round(float(mem["amount"]))))
            store.set_master_member(code, tid, label, historic=historic, child_group=child)
            member_dates[code].append(str(mem["date"]))

    # Pass 2 — GROUP aggregations (handle/month), excluding rows already claimed.
    for m in masters:
        code = m["code"]
        default_child = m.get("title", code)
        for mem in m.get("members", []):
            if not mem.get("group"):
                continue
            historic = bool(mem.get("historic"))
            cat = "historic_evidence" if historic else MASTER_CATEGORY.get(code, "benazir_payments")
            label = mem.get("label", "")
            child = mem.get("child") or default_child
            for gid in _group_ids(ledger, mem, used_ids):
                store.save_decision(gid, category=cat, manual_comment=label,
                                    manual_person="benazir", reason=f"Master {code} ({mem['month']})")
                used_ids.add(gid)
                store.set_master_member(code, gid, "", historic=historic, child_group=label or child)
                row = ledger.loc[ledger["transaction_id"] == gid]
                if not row.empty:
                    member_dates[code].append(str(row.iloc[0]["transaction_date"]))
                    claimed.add((str(row.iloc[0]["transaction_date"]), round(float(row.iloc[0]["amount"]))))

    # base_date default = earliest member date
    for m in masters:
        code = m["code"]
        if not m.get("base_date") and member_dates[code]:
            store.update_master(code, base_date=min(member_dates[code]))
    print(f"Seeded {len(masters)} masters ({skipped} unmatched members skipped — no fabrication).")

    # ---- general reasons (attach to a real Benazir row, or DROP) ----
    # No fabricated "[recalled]" manual entries: a reason only sticks if it lands
    # on an actual Benazir/Nazrana bank/Paytm row. Reasons with no real row are
    # dropped (the underlying expense, if real, is surfaced on the
    # "Figuring Out Benazir Expenses" page for chat-based identification).
    applied = dropped = 0
    for r in reasons:
        key = (str(r["date"]), round(float(r["amount"])))
        if key in claimed:
            continue
        ids = [x for x in _match(ledger, r["date"], r["amount"], benazir_only=True)
               if x not in used_ids]
        if ids:
            used_ids.add(ids[0])
            store.save_decision(ids[0], manual_comment=r.get("reason") or None,
                                manual_person="benazir", reason="General reason")
            applied += 1
        else:
            dropped += 1
    print(f"General: {applied} attached to real Benazir rows, {dropped} dropped (no real row, not fabricated).")


if __name__ == "__main__":
    main()

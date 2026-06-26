"""Bank Ledger Dashboard — Streamlit entry point.

Local-only dashboard for reviewing bank statements and maintaining a manual
transaction ledger. Source files under all_bank_statements/ are READ ONLY; all
manual edits live in data/cache/decisions.sqlite.

Run with:  streamlit run app.py

The file is organised as: shared data loading (cached) at the top, then one
function per page, then a small router at the bottom. Keeping the heavy lifting
in src/services means this file stays mostly about layout and widgets.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.services.decision_store import DecisionStore
from src.services.export_service import export_filename, to_csv_bytes, to_xlsx_bytes
from src.services.pipeline import (
    THRESHOLD_SETTING_KEY,
    effective_aliases,
    effective_categories,
    effective_threshold,
    extract_normalize_classify,
    finalize_ledger,
)
from src.utils.config_loader import load_review_statuses
from src.utils.money import format_inr

SOURCE_DIR = "all_bank_statements"

st.set_page_config(page_title="Bank Ledger Dashboard", page_icon="🧾", layout="wide")


# --- shared data loading -----------------------------------------------------

@st.cache_resource
def get_store() -> DecisionStore:
    """One DecisionStore for the whole app session."""
    return DecisionStore()


@st.cache_data(show_spinner="Reading statements…")
def load_extraction(cache_key: tuple, aliases: dict, threshold: float) -> dict:
    """Cached extraction+normalization+classification.

    ``cache_key`` makes the cache sensitive to the alias/threshold inputs so a
    config change re-runs extraction. The store is intentionally NOT part of
    this cache — manual decisions are applied separately on every rerun.
    """
    return extract_normalize_classify(SOURCE_DIR, aliases, threshold)


def build_state():
    """Load everything the pages need and return it as a dict."""
    store = get_store()
    aliases = effective_aliases(store)
    categories = effective_categories(store)
    threshold = effective_threshold(store)

    # A simple, hashable cache key derived from inputs that affect extraction.
    cache_key = (
        tuple(sorted((k, tuple(v.get("aliases", []))) for k, v in aliases.items())),
        threshold,
    )
    extraction = load_extraction(cache_key, aliases, threshold)
    ledger = finalize_ledger(extraction["classified"], store, threshold)

    return {
        "store": store,
        "aliases": aliases,
        "categories": categories,
        "threshold": threshold,
        "unified": extraction["unified"],
        "reports": extraction["reports"],
        "overall_gaps": extraction.get("overall_gaps", []),
        "ledger": ledger,
        "review_statuses": load_review_statuses() or [
            "unreviewed", "confirmed_related", "probably_related",
            "not_related", "unknown", "review_later", "do_not_remember",
        ],
    }


def refresh():
    """Clear caches and rerun (used after edits that change extraction inputs)."""
    load_extraction.clear()
    st.rerun()


# --- small UI helpers --------------------------------------------------------

def money_metric(col, label: str, value: float):
    col.metric(label, format_inr(value))


def download_buttons(df: pd.DataFrame, label: str, key: str):
    """Render CSV + XLSX download buttons for a DataFrame."""
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇ CSV", data=to_csv_bytes(df),
        file_name=export_filename(label, "csv"), mime="text/csv",
        key=f"{key}_csv", use_container_width=True,
    )
    c2.download_button(
        "⬇ XLSX", data=to_xlsx_bytes(df),
        file_name=export_filename(label, "xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key}_xlsx", use_container_width=True,
    )


def totals(df: pd.DataFrame) -> dict:
    """Compute paid/received/net totals for a ledger slice."""
    if df.empty:
        return {"paid": 0.0, "received": 0.0, "net": 0.0}
    paid = df.loc[df["direction"] == "PAID_OUT", "amount"].sum()
    received = df.loc[df["direction"] == "RECEIVED", "amount"].sum()
    return {"paid": float(paid), "received": float(received), "net": float(received - paid)}


def s(value) -> str:
    """Coerce a possibly-NA/None cell to a plain string ('' for missing).

    Guards against ``pd.NA or ''`` which raises 'boolean value of NA is
    ambiguous'. Use this anywhere a schema cell feeds a widget's value.
    """
    try:
        if value is None or pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _date_bounds(df: pd.DataFrame):
    """Return (min_date, max_date) python dates from transaction_date.

    Falls back to today's date for both bounds when no dates are present.
    """
    from datetime import date

    dates = pd.to_datetime(df["transaction_date"], errors="coerce").dropna()
    if dates.empty:
        today = date.today()
        return today, today
    return dates.min().date(), dates.max().date()


def _filter_ledger(df, bank, direction, search, drange, only_manual) -> pd.DataFrame:
    """Apply the combined-ledger page filters and return the filtered frame."""
    view = df.copy()
    if bank != "(all)":
        view = view[view["source_bank"] == bank]
    if direction != "(all)":
        view = view[view["direction"] == direction]
    if search:
        view = view[view["description"].str.contains(search, case=False, na=False)]
    if only_manual:
        view = view[view["is_manual_entry"].fillna(False).astype(bool)]
    # Date range: st.date_input gives a (start, end) tuple once both are set.
    if isinstance(drange, (tuple, list)) and len(drange) == 2:
        start, end = pd.Timestamp(drange[0]), pd.Timestamp(drange[1])
        dts = pd.to_datetime(view["transaction_date"], errors="coerce")
        view = view[(dts >= start) & (dts <= end) | dts.isna()]
    return view


# --- Page 1: Unified Extraction View ----------------------------------------

def page_unified(state):
    st.header("1 · Unified Extraction View")
    st.caption("Exactly what each parser pulled from each file, before heavy transformation.")

    # --- coverage gap banner --------------------------------------------------
    overall_gaps = state.get("overall_gaps", [])
    if overall_gaps:
        gap_list = ", ".join(overall_gaps[:12]) + (f"  …+{len(overall_gaps)-12} more" if len(overall_gaps) > 12 else "")
        st.error(
            f"⚠ **{len(overall_gaps)} month(s) have zero transactions** in the combined dataset. "
            f"These months are missing — you may need to download additional statements.\n\n"
            f"**Missing:** {gap_list}"
        )
    else:
        st.success("Coverage looks complete — no month gaps detected between the earliest and latest transaction dates.")

    reports = state["reports"]
    if reports:
        st.subheader("Per-file parse report")
        rep_df = pd.DataFrame([
            {
                "Bank": r["bank_folder"],
                "File": r["file"],
                "Parser": r["parser"],
                "Rows": r["rows"],
                "Stated from": r.get("stated_date_from") or "—",
                "Stated to": r.get("stated_date_to") or "—",
                "Status": r["status"],
                "Warnings": "; ".join(r["warnings"]),
                "Errors": "; ".join(r["errors"]),
                "Checksum": r["checksum"],
            }
            for r in reports
        ])
        st.dataframe(rep_df, use_container_width=True, hide_index=True)
        bad = [r for r in reports if r["status"] != "ok"]
        if bad:
            st.warning(f"{len(bad)} file(s) reported problems — see the Errors column above.")

    unified = state["unified"]
    st.subheader(f"Extracted rows ({len(unified)})")
    if unified.empty:
        st.info("No rows extracted yet.")
        return

    c1, c2, c3 = st.columns([1, 1, 2])
    banks = ["(all)"] + sorted(unified["source_bank"].dropna().unique().tolist())
    bank = c1.selectbox("Bank", banks, key="u_bank")
    files = ["(all)"] + sorted(unified["source_file"].dropna().unique().tolist())
    file_sel = c2.selectbox("File", files, key="u_file")
    search = c3.text_input("Search description", key="u_search")

    view = unified.copy()
    if bank != "(all)":
        view = view[view["source_bank"] == bank]
    if file_sel != "(all)":
        view = view[view["source_file"] == file_sel]
    if search:
        view = view[view["raw_description"].str.contains(search, case=False, na=False)]

    st.dataframe(view, use_container_width=True, hide_index=True)
    download_buttons(view, "unified_extraction", key="u")


# --- Page 2: Combined Transactions View (master ledger) ----------------------

def page_combined(state):
    st.header("2 · Combined Transactions View")
    st.caption("The master ledger: every normalized transaction across all sources.")

    ledger = state["ledger"]
    if ledger.empty:
        st.info("No transactions to show.")
        return

    c1, c2, c3, c4 = st.columns(4)
    banks = ["(all)"] + sorted(ledger["source_bank"].dropna().unique().tolist())
    bank = c1.selectbox("Bank", banks, key="c_bank")
    direction = c2.selectbox("Direction", ["(all)", "PAID_OUT", "RECEIVED", "UNKNOWN"], key="c_dir")
    search = c3.text_input("Search description", key="c_search")
    only_manual = c4.checkbox("Only manual entries", key="c_manual")

    from datetime import timedelta

    dmin, dmax = _date_bounds(ledger)
    all_dates_label = (
        f"All dates  ({dmin.strftime('%d %b %Y')} – {dmax.strftime('%d %b %Y')})"
    )
    _RANGE_PRESETS = [
        all_dates_label,
        "Last 30 days",
        "Last 90 days",
        "Last 6 months",
        "Last 1 year",
        "Custom range",
    ]
    preset = st.selectbox("Date range", _RANGE_PRESETS, index=0, key="c_date_preset")

    if preset == all_dates_label:
        drange = (dmin, dmax)
    elif preset == "Last 30 days":
        drange = (max(dmin, dmax - timedelta(days=30)), dmax)
    elif preset == "Last 90 days":
        drange = (max(dmin, dmax - timedelta(days=90)), dmax)
    elif preset == "Last 6 months":
        drange = (max(dmin, dmax - timedelta(days=183)), dmax)
    elif preset == "Last 1 year":
        drange = (max(dmin, dmax - timedelta(days=365)), dmax)
    else:
        drange = st.date_input(
            "Custom date range", value=(dmin, dmax),
            min_value=dmin, max_value=dmax, key="c_dates_custom",
        )

    if preset != "Custom range" and isinstance(drange, tuple) and len(drange) == 2:
        st.caption(f"Effective range: {drange[0].strftime('%d %b %Y')} → {drange[1].strftime('%d %b %Y')}")

    view = _filter_ledger(ledger, bank, direction, search, drange, only_manual)
    view = view.sort_values("transaction_date", na_position="last")

    t = totals(view)
    m1, m2, m3, m4 = st.columns(4)
    money_metric(m1, "Total paid out", t["paid"])
    money_metric(m2, "Total received", t["received"])
    money_metric(m3, "Net (received − paid)", t["net"])
    m4.metric("Rows", len(view))

    display_cols = [
        "source_bank", "transaction_date", "description", "debit", "credit",
        "amount", "direction", "balance", "category", "detected_names",
        "manual_review_status", "manual_comment", "is_manual_entry",
    ]
    st.dataframe(view[display_cols], use_container_width=True, hide_index=True)
    download_buttons(view, "combined_transactions", key="c")

    _editor_for_selection(state, view)


def _editor_for_selection(state, view):
    """Inline single-transaction editor used on the combined ledger page."""
    st.subheader("Edit a transaction")
    st.caption("Manual edits are saved to data/cache/decisions.sqlite and persist across restarts.")
    if view.empty:
        return
    options = view["transaction_id"].tolist()
    labels = {
        row["transaction_id"]: f'{row["transaction_date"]} · {row["source_bank"]} · '
                               f'{format_inr(row["amount"])} · {str(row["description"])[:50]}'
        for _, row in view.iterrows()
    }
    txn_id = st.selectbox("Transaction", options, format_func=lambda x: labels.get(x, x), key="c_edit_sel")
    if txn_id:
        _transaction_editor(state, txn_id, key_prefix="c_edit")


# --- Page 3: Name-Based / Person-Focused Review ------------------------------

def page_names(state):
    st.header("3 · Name-Based Search / Person Review")
    st.caption("Transactions involving Benazir, Nazrana/Najrana, and configured aliases.")

    ledger = state["ledger"]
    store = state["store"]
    aliases = state["aliases"]

    person_keys = ["benazir", "nazrana"] + [k for k in aliases if k not in ("benazir", "nazrana")]
    labels = {k: aliases.get(k, {}).get("display_name", k) for k in person_keys}
    chosen = st.multiselect(
        "People", person_keys, default=person_keys,
        format_func=lambda k: labels.get(k, k), key="n_people",
    )
    include_manual_marked = st.checkbox(
        "Include transactions I manually marked as related", value=True, key="n_incl_manual",
    )

    mask = pd.Series(False, index=ledger.index)
    if "benazir" in chosen:
        mask = mask | ledger["is_benazir_related"].fillna(False).astype(bool)
    if "nazrana" in chosen:
        mask = mask | ledger["is_nazrana_related"].fillna(False).astype(bool)
    for k in chosen:
        if k not in ("benazir", "nazrana"):
            mask = mask | ledger["detected_names"].fillna("").str.contains(k, case=False)
    matched = ledger[mask].copy()

    if not include_manual_marked:
        # Drop rows whose relation came only from a manual mark (no alias hit).
        matched = matched[matched["matched_aliases"].fillna("") != ""]

    st.subheader(f"Matched transactions ({len(matched)})")
    if matched.empty:
        st.info("No matching transactions for the selected people.")
    else:
        t = totals(matched)
        m1, m2, m3 = st.columns(3)
        money_metric(m1, "Net paid out", t["paid"])
        money_metric(m2, "Net received", t["received"])
        money_metric(m3, "Net difference (received − paid)", t["net"])

        cols = [
            "source_bank", "transaction_date", "description", "amount",
            "direction", "matched_aliases", "category", "manual_review_status",
            "manual_comment",
        ]
        st.dataframe(matched[cols], use_container_width=True, hide_index=True)
        download_buttons(matched, "person_related", key="n")

        st.subheader("Review a matched transaction")
        opts = matched["transaction_id"].tolist()
        lab = {
            r["transaction_id"]: f'{r["transaction_date"]} · {format_inr(r["amount"])} · {str(r["description"])[:50]}'
            for _, r in matched.iterrows()
        }
        sel = st.selectbox("Transaction", opts, format_func=lambda x: lab.get(x, x), key="n_sel")
        if sel:
            _transaction_editor(state, sel, key_prefix="n_edit")

    st.divider()
    _manual_mark_unmatched(state)
    st.divider()
    _alias_admin(store, aliases)


def _manual_mark_unmatched(state):
    """Let the user mark ANY transaction as related, even with no alias hit."""
    st.subheader("Manually mark a transaction as related")
    st.caption("Use this when a payment relates to someone but their name isn't in the narration.")
    ledger = state["ledger"]
    non_manual = ledger[~ledger["is_manual_entry"].fillna(False).astype(bool)]
    opts = non_manual["transaction_id"].tolist()
    lab = {
        r["transaction_id"]: f'{r["transaction_date"]} · {r["source_bank"]} · '
                             f'{format_inr(r["amount"])} · {str(r["description"])[:45]}'
        for _, r in non_manual.iterrows()
    }
    sel = st.selectbox("Pick any transaction", opts, format_func=lambda x: lab.get(x, x), key="n_mark_sel")
    person = st.selectbox("Mark as related to", ["benazir", "nazrana", "both"], key="n_mark_person")
    if st.button("Mark as related", key="n_mark_btn") and sel:
        state["store"].save_decision(
            sel, manual_person=person, manual_review_status="confirmed_related",
            reason="Manually marked related on Name Review page",
        )
        st.success("Marked. Refreshing…")
        st.rerun()


def _alias_admin(store, aliases):
    """Add new aliases live."""
    with st.expander("Manage aliases (config + your additions)"):
        st.write({k: v.get("aliases", []) for k, v in aliases.items()})
        c1, c2, c3 = st.columns(3)
        key = c1.text_input("Person key", key="alias_key", placeholder="benazir")
        alias = c2.text_input("New alias", key="alias_val", placeholder="b rahaman")
        flag = c3.selectbox("Related flag", ["benazir", "nazrana", "(none)"], key="alias_flag")
        if st.button("Add alias", key="alias_add") and key and alias:
            store.add_alias(key.strip().lower(), alias, key, "" if flag == "(none)" else flag)
            st.success(f'Added alias "{alias}" to {key}. Refreshing…')
            refresh()


# --- Page 4: Large Payments Review -------------------------------------------

def page_large(state):
    st.header("4 · Large Payments Review")
    ledger = state["ledger"]
    store = state["store"]
    threshold = state["threshold"]

    c1, c2 = st.columns([1, 3])
    new_threshold = c1.number_input(
        "Large-payment threshold (₹)", min_value=0.0, value=float(threshold),
        step=500.0, key="l_threshold",
    )
    if c2.button("Save threshold", key="l_save"):
        store.set_setting(THRESHOLD_SETTING_KEY, new_threshold)
        st.success(f"Threshold saved as {format_inr(new_threshold)}. Refreshing…")
        refresh()

    # Apply the (possibly unsaved) live threshold for this view.
    large = ledger[ledger["amount"].fillna(0) >= new_threshold].copy()
    st.caption(f"Showing {len(large)} transaction(s) with amount ≥ {format_inr(new_threshold)}.")

    f1, f2, f3 = st.columns(3)
    banks = ["(all)"] + sorted(large["source_bank"].dropna().unique().tolist())
    bank = f1.selectbox("Bank", banks, key="l_bank")
    direction = f2.selectbox("Direction", ["(all)", "PAID_OUT", "RECEIVED"], key="l_dir")
    search = f3.text_input("Search description", key="l_search")

    if bank != "(all)":
        large = large[large["source_bank"] == bank]
    if direction != "(all)":
        large = large[large["direction"] == direction]
    if search:
        large = large[large["description"].str.contains(search, case=False, na=False)]
    large = large.sort_values("amount", ascending=False)

    cols = [
        "source_bank", "transaction_date", "description", "amount", "direction",
        "category", "detected_names", "manual_review_status", "manual_comment",
    ]
    st.dataframe(large[cols], use_container_width=True, hide_index=True)
    download_buttons(large, "large_payments", key="l")

    st.subheader("Classify a large payment")
    if not large.empty:
        opts = large["transaction_id"].tolist()
        lab = {
            r["transaction_id"]: f'{r["transaction_date"]} · {format_inr(r["amount"])} · {str(r["description"])[:50]}'
            for _, r in large.iterrows()
        }
        sel = st.selectbox("Transaction", opts, format_func=lambda x: lab.get(x, x), key="l_sel")
        if sel:
            _transaction_editor(state, sel, key_prefix="l_edit")


# --- Page 5: Classification Summary ------------------------------------------

def page_summary(state):
    st.header("5 · Classification Summary")
    ledger = state["ledger"]
    if ledger.empty:
        st.info("No data to summarize.")
        return

    overall = totals(ledger)
    m1, m2, m3, m4 = st.columns(4)
    money_metric(m1, "Total paid out", overall["paid"])
    money_metric(m2, "Total received", overall["received"])
    money_metric(m3, "Net (received − paid)", overall["net"])
    m4.metric("Transactions", len(ledger))

    st.subheader("Person-wise totals")
    ben = ledger[ledger["is_benazir_related"].fillna(False).astype(bool)]
    naz = ledger[ledger["is_nazrana_related"].fillna(False).astype(bool)]
    tb, tn = totals(ben), totals(naz)
    pcols = st.columns(4)
    money_metric(pcols[0], "Benazir — paid", tb["paid"])
    money_metric(pcols[1], "Benazir — received", tb["received"])
    money_metric(pcols[2], "Nazrana — paid", tn["paid"])
    money_metric(pcols[3], "Nazrana — received", tn["received"])
    st.caption(
        '"Owed" is never assumed automatically — it only reflects what you mark '
        "manually via review status and comments."
    )

    st.subheader("Category-wise totals")
    cat = (
        ledger.groupby("category")
        .apply(lambda g: pd.Series({
            "rows": len(g),
            "paid_out": g.loc[g["direction"] == "PAID_OUT", "amount"].sum(),
            "received": g.loc[g["direction"] == "RECEIVED", "amount"].sum(),
        }), include_groups=False)
        .reset_index()
        .sort_values("rows", ascending=False)
    )
    st.dataframe(cat, use_container_width=True, hide_index=True)

    _income_breakdown(ledger)

    st.subheader("Review-status counts")
    rs = ledger["manual_review_status"].fillna("").replace("", "(none)").value_counts()
    st.dataframe(rs.rename_axis("review_status").reset_index(name="count"),
                 use_container_width=True, hide_index=True)

    st.divider()
    _category_exports(state, ledger)


def _income_breakdown(ledger: pd.DataFrame):
    """Employer-wise and IT-refund income breakdown inside an expander."""
    income = ledger[ledger["category"].isin(["salary_or_income", "it_refund"])]
    if income.empty:
        return

    with st.expander("Income breakdown — who paid how much", expanded=True):
        st.caption(
            "Auto-classified from NEFT narrations. Verify each row on the Combined Ledger. "
            "'Amount' here is absolute (all are credits / RECEIVED)."
        )

        # Determine source employer from description keyword matching.
        def _employer(desc: str) -> str:
            d = desc.lower()
            if "koireader" in d:
                return "KoiReader Technologies"
            if "primus" in d:
                return "Primus Global"
            return "Other / unidentified"

        sal = income[income["category"] == "salary_or_income"].copy()
        it_ref = income[income["category"] == "it_refund"].copy()

        if not sal.empty:
            sal["employer"] = sal["description"].apply(_employer)
            emp_summary = (
                sal.groupby("employer")
                .apply(lambda g: pd.Series({
                    "payments": len(g),
                    "total_received": g["amount"].sum(),
                    "first_payment": g["transaction_date"].min(),
                    "last_payment": g["transaction_date"].max(),
                }), include_groups=False)
                .reset_index()
                .sort_values("total_received", ascending=False)
            )
            emp_summary["total_received"] = emp_summary["total_received"].apply(format_inr)
            st.markdown("**Salary / employer credits**")
            st.dataframe(emp_summary, use_container_width=True, hide_index=True)

        if not it_ref.empty:
            st.markdown("**Income tax refunds**")
            it_cols = ["transaction_date", "source_bank", "description", "amount"]
            it_ref_disp = it_ref[it_cols].copy()
            it_ref_disp["amount"] = it_ref_disp["amount"].apply(format_inr)
            st.dataframe(it_ref_disp, use_container_width=True, hide_index=True)
            st.caption(
                f"IT refund total: {format_inr(income[income['category'] == 'it_refund']['amount'].sum())}"
            )


def _category_exports(state, ledger):
    st.subheader("Category / focused exports")
    ben = ledger[ledger["is_benazir_related"].fillna(False).astype(bool)]
    naz = ledger[ledger["is_nazrana_related"].fillna(False).astype(bool)]
    large = ledger[ledger["is_large_payment"].fillna(False).astype(bool)]
    review = ledger[ledger["manual_review_status"].isin(["review_later", "unknown", "do_not_remember"])]
    manual = ledger[ledger["is_manual_entry"].fillna(False).astype(bool)]

    grid = [
        ("Benazir-related", ben, "exp_ben"),
        ("Nazrana-related", naz, "exp_naz"),
        ("Large payments", large, "exp_large"),
        ("Unknown / review-later", review, "exp_review"),
        ("Manual entries", manual, "exp_manual"),
        ("Full ledger (with comments)", ledger, "exp_full"),
    ]
    for label, df, key in grid:
        st.markdown(f"**{label}** — {len(df)} row(s)")
        download_buttons(df, label, key=key)

    st.markdown("**Summary report**")
    summary = _summary_frame(state, ledger)
    download_buttons(summary, "summary_report", key="exp_summary")


def _summary_frame(state, ledger) -> pd.DataFrame:
    """Build a one-table summary report for export."""
    overall = totals(ledger)
    ben = totals(ledger[ledger["is_benazir_related"].fillna(False).astype(bool)])
    naz = totals(ledger[ledger["is_nazrana_related"].fillna(False).astype(bool)])
    rows = [
        ("Total paid out", overall["paid"]),
        ("Total received", overall["received"]),
        ("Net (received - paid)", overall["net"]),
        ("Benazir - paid", ben["paid"]),
        ("Benazir - received", ben["received"]),
        ("Nazrana - paid", naz["paid"]),
        ("Nazrana - received", naz["received"]),
        ("Large payments (count)", int(ledger["is_large_payment"].fillna(False).sum())),
        ("Manual entries (count)", int(ledger["is_manual_entry"].fillna(False).sum())),
        ("Transactions (count)", len(ledger)),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


# --- Manual Entries page (supports linking) ----------------------------------

def page_manual_entries(state):
    st.header("➕ Manual Entries")
    st.caption("For payments that don't appear directly with the person's name "
               "(e.g. Kotak Life Insurance, cash, unclear UPI). Clearly marked as manual.")
    store = state["store"]
    ledger = state["ledger"]

    with st.form("manual_entry_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        entry_date = c1.date_input("Date", key="me_date")
        person = c2.text_input("Person", key="me_person", placeholder="benazir / nazrana / other")
        amount = c3.number_input("Amount (₹)", min_value=0.0, step=100.0, key="me_amount")
        c4, c5 = st.columns(2)
        direction = c4.selectbox("Direction", ["PAID_OUT", "RECEIVED", "UNKNOWN"], key="me_dir")
        category = c5.selectbox("Category", ["(none)"] + state["categories"], key="me_cat")
        description = st.text_input("Description", key="me_desc")
        reason = st.text_area("Reason / context", key="me_reason")
        evidence = st.text_area("Evidence note", key="me_evidence")
        submitted = st.form_submit_button("Add manual entry")
        if submitted:
            store.add_manual_entry(
                entry_date=str(entry_date), person=person, amount=amount,
                direction=direction, category="" if category == "(none)" else category,
                description=description, reason=reason, evidence_note=evidence,
            )
            st.success("Manual entry added.")
            st.rerun()

    entries = store.get_manual_entries_df()
    st.subheader(f"Existing manual entries ({len(entries)})")
    if entries.empty:
        st.info("No manual entries yet.")
        return
    st.dataframe(entries, use_container_width=True, hide_index=True)

    st.subheader("Link a manual entry to bank transaction(s)")
    entry_id = st.selectbox(
        "Manual entry", entries["manual_entry_id"].tolist(),
        format_func=lambda x: _manual_label(entries, x), key="me_link_entry",
    )
    bank_txns = ledger[~ledger["is_manual_entry"].fillna(False).astype(bool)]
    txn_id = st.selectbox(
        "Bank transaction", bank_txns["transaction_id"].tolist(),
        format_func=lambda x: _txn_label(bank_txns, x), key="me_link_txn",
    )
    c1, c2 = st.columns(2)
    if c1.button("Link", key="me_link_btn") and entry_id and txn_id:
        store.add_link(entry_id, txn_id)
        st.success("Linked.")
        st.rerun()
    if c2.button("Delete selected manual entry", key="me_del_btn") and entry_id:
        store.delete_manual_entry(entry_id, reason="Deleted from Manual Entries page")
        st.warning("Manual entry deleted.")
        st.rerun()


def _manual_label(entries, x):
    row = entries[entries["manual_entry_id"] == x]
    if row.empty:
        return x
    r = row.iloc[0]
    return f'{r["entry_date"]} · {r["person"]} · {format_inr(r["amount"])} · {str(r["description"])[:40]}'


def _txn_label(df, x):
    row = df[df["transaction_id"] == x]
    if row.empty:
        return x
    r = row.iloc[0]
    return f'{r["transaction_date"]} · {r["source_bank"]} · {format_inr(r["amount"])} · {str(r["description"])[:40]}'


# --- shared transaction editor ----------------------------------------------

def _transaction_editor(state, txn_id: str, *, key_prefix: str):
    """Render the edit form for one transaction and persist changes."""
    store = state["store"]
    ledger = state["ledger"]
    row = ledger[ledger["transaction_id"] == txn_id]
    if row.empty:
        st.info("Transaction not found.")
        return
    row = row.iloc[0]

    st.markdown(
        f'**{s(row["source_bank"])}** · {s(row["transaction_date"])} · '
        f'{format_inr(row["amount"])} · {s(row["direction"])}'
    )
    st.code(s(row["raw_description"]) or "(no description)", language=None)
    st.caption(f'Why classified: {s(row.get("classification_reason")) or "—"}')

    categories = ["(unchanged)"] + state["categories"]
    review_statuses = ["(unchanged)"] + state["review_statuses"]

    c1, c2 = st.columns(2)
    category = c1.selectbox("Category", categories, key=f"{key_prefix}_cat_{txn_id}")
    review = c2.selectbox("Review status", review_statuses, key=f"{key_prefix}_rev_{txn_id}")
    person = st.selectbox(
        "Mark related to", ["(unchanged)", "benazir", "nazrana", "both", "none"],
        key=f"{key_prefix}_person_{txn_id}",
    )
    comment = st.text_area(
        "Comment / reasoning", value=s(row.get("manual_comment")),
        key=f"{key_prefix}_comment_{txn_id}",
    )
    flags = st.text_input(
        "Flags (comma-separated)", value=s(row.get("manual_flags")),
        key=f"{key_prefix}_flags_{txn_id}",
    )

    c1, c2 = st.columns(2)
    if c1.button("💾 Save", key=f"{key_prefix}_save_{txn_id}"):
        store.save_decision(
            txn_id,
            category=None if category == "(unchanged)" else category,
            manual_review_status=None if review == "(unchanged)" else review,
            manual_person=None if person == "(unchanged)" else person,
            manual_comment=comment,
            manual_flags=flags,
            reason="Edited via dashboard",
        )
        st.success("Saved. Refreshing…")
        st.rerun()
    if c2.button("↺ Reset to auto", key=f"{key_prefix}_reset_{txn_id}"):
        store.reset_decision(txn_id, reason="Reset via dashboard")
        st.info("Reset. Refreshing…")
        st.rerun()


# --- router ------------------------------------------------------------------

PAGES = {
    "1 · Unified Extraction": page_unified,
    "2 · Combined Ledger": page_combined,
    "3 · Name / Person Review": page_names,
    "4 · Large Payments": page_large,
    "5 · Classification Summary": page_summary,
    "➕ Manual Entries": page_manual_entries,
}


def main():
    st.sidebar.title("🧾 Bank Ledger Dashboard")

    state = build_state()

    st.sidebar.metric("Transactions", len(state["ledger"]))
    st.sidebar.metric("Source files", len(state["reports"]))
    if st.sidebar.button("🔄 Re-read statements"):
        refresh()

    choice = st.sidebar.radio("Page", list(PAGES.keys()), key="nav")
    st.sidebar.caption("All processing is local. No cloud, no telemetry.")

    PAGES[choice](state)


if __name__ == "__main__":
    main()

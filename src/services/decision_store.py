"""SQLite-backed store for everything the user edits by hand.

This is the only place the app persists user decisions. Source statements stay
read-only; all manual classifications, comments, review flags, manual entries,
links, custom categories/aliases, settings, and an audit trail live here in
``data/cache/decisions.sqlite``.

Design notes:
    * One short-lived connection per operation. For a local single-user app this
      is simple and robust against Streamlit's re-run model.
    * Decisions are keyed by ``transaction_id`` so they survive re-extraction.
    * Every write that changes a value also appends to ``audit_log`` with the
      old value, new value, timestamp, and an optional reason.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.utils.hashing import manual_entry_id
from src.utils.logging_setup import get_logger

DEFAULT_DB_PATH = Path("data/cache/decisions.sqlite")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionStore:
    """Thin wrapper over the SQLite database of manual decisions."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # -- connection -----------------------------------------------------------

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Create all tables if they do not already exist."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS transaction_decisions (
                    transaction_id       TEXT PRIMARY KEY,
                    category             TEXT,
                    subcategory          TEXT,
                    manual_comment       TEXT,
                    manual_review_status TEXT,
                    manual_flags         TEXT,
                    manual_person        TEXT,
                    created_at           TEXT,
                    updated_at           TEXT
                );

                CREATE TABLE IF NOT EXISTS manual_entries (
                    manual_entry_id      TEXT PRIMARY KEY,
                    entry_date           TEXT,
                    person               TEXT,
                    amount               REAL,
                    direction            TEXT,
                    category             TEXT,
                    subcategory          TEXT,
                    description          TEXT,
                    reason               TEXT,
                    evidence_note        TEXT,
                    review_status        TEXT,
                    created_at           TEXT,
                    updated_at           TEXT
                );

                CREATE TABLE IF NOT EXISTS transaction_links (
                    link_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    manual_entry_id  TEXT,
                    transaction_id   TEXT,
                    created_at       TEXT,
                    UNIQUE(manual_entry_id, transaction_id)
                );

                CREATE TABLE IF NOT EXISTS categories (
                    name       TEXT PRIMARY KEY,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS aliases (
                    person_key   TEXT,
                    alias        TEXT,
                    display_name TEXT,
                    related_flag TEXT,
                    created_at   TEXT,
                    PRIMARY KEY (person_key, alias)
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT,
                    entity_id   TEXT,
                    field       TEXT,
                    old_value   TEXT,
                    new_value   TEXT,
                    reason      TEXT,
                    timestamp   TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TEXT
                );
                """
            )
        get_logger().info("Decision store ready at %s", self.db_path)

    # -- transaction decisions ------------------------------------------------

    def get_decision(self, transaction_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM transaction_decisions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_decisions_df(self) -> pd.DataFrame:
        """Return all transaction decisions as a DataFrame."""
        with self._connect() as conn:
            return pd.read_sql_query("SELECT * FROM transaction_decisions", conn)

    def save_decision(
        self,
        transaction_id: str,
        *,
        category: str | None = None,
        subcategory: str | None = None,
        manual_comment: str | None = None,
        manual_review_status: str | None = None,
        manual_flags: str | None = None,
        manual_person: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Insert or update a manual decision for one transaction (with audit).

        Only the provided (non-None) fields are changed; others are preserved.
        Each changed field is recorded in the audit log.
        """
        existing = self.get_decision(transaction_id) or {}
        now = _now()
        updates = {
            "category": category,
            "subcategory": subcategory,
            "manual_comment": manual_comment,
            "manual_review_status": manual_review_status,
            "manual_flags": manual_flags,
            "manual_person": manual_person,
        }
        # Audit only fields that actually change.
        for field, new_value in updates.items():
            if new_value is None:
                continue
            old_value = existing.get(field)
            if str(old_value or "") != str(new_value or ""):
                self._audit("transaction", transaction_id, field, old_value, new_value, reason)

        merged = {**{k: existing.get(k) for k in updates}, **{k: v for k, v in updates.items() if v is not None}}
        created_at = existing.get("created_at") or now

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO transaction_decisions
                    (transaction_id, category, subcategory, manual_comment,
                     manual_review_status, manual_flags, manual_person,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transaction_id) DO UPDATE SET
                    category=excluded.category,
                    subcategory=excluded.subcategory,
                    manual_comment=excluded.manual_comment,
                    manual_review_status=excluded.manual_review_status,
                    manual_flags=excluded.manual_flags,
                    manual_person=excluded.manual_person,
                    updated_at=excluded.updated_at
                """,
                (
                    transaction_id, merged["category"], merged["subcategory"],
                    merged["manual_comment"], merged["manual_review_status"],
                    merged["manual_flags"], merged["manual_person"],
                    created_at, now,
                ),
            )

    def reset_decision(self, transaction_id: str, *, reason: str | None = None) -> None:
        """Remove a manual decision so the row reverts to auto-classification."""
        existing = self.get_decision(transaction_id)
        if not existing:
            return
        self._audit("transaction", transaction_id, "*reset*", "decision", "", reason)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM transaction_decisions WHERE transaction_id = ?",
                (transaction_id,),
            )

    # -- manual entries -------------------------------------------------------

    def add_manual_entry(
        self,
        *,
        entry_date: str,
        person: str,
        amount: float,
        direction: str,
        category: str = "",
        subcategory: str = "",
        description: str = "",
        reason: str = "",
        evidence_note: str = "",
        review_status: str = "unreviewed",
    ) -> str:
        """Create a manual entry and return its id."""
        now = _now()
        entry_id = manual_entry_id(person=person, amount=amount, entry_date=entry_date, created_at=now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO manual_entries
                    (manual_entry_id, entry_date, person, amount, direction,
                     category, subcategory, description, reason, evidence_note,
                     review_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(manual_entry_id) DO NOTHING
                """,
                (entry_id, entry_date, person, float(amount), direction,
                 category, subcategory, description, reason, evidence_note,
                 review_status, now, now),
            )
        self._audit("manual_entry", entry_id, "*create*", "", description or person, reason)
        return entry_id

    def update_manual_entry(self, manual_entry_id_: str, **fields) -> None:
        """Update editable fields on a manual entry (with audit)."""
        allowed = {
            "entry_date", "person", "amount", "direction", "category",
            "subcategory", "description", "reason", "evidence_note", "review_status",
        }
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return
        existing = self.get_manual_entry(manual_entry_id_) or {}
        for field, new_value in sets.items():
            old_value = existing.get(field)
            if str(old_value or "") != str(new_value or ""):
                self._audit("manual_entry", manual_entry_id_, field, old_value, new_value, None)
        sets["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in sets)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE manual_entries SET {assignments} WHERE manual_entry_id = ?",
                (*sets.values(), manual_entry_id_),
            )

    def get_manual_entry(self, manual_entry_id_: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM manual_entries WHERE manual_entry_id = ?",
                (manual_entry_id_,),
            ).fetchone()
        return dict(row) if row else None

    def get_manual_entries_df(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query("SELECT * FROM manual_entries", conn)

    def delete_manual_entry(self, manual_entry_id_: str, *, reason: str | None = None) -> None:
        self._audit("manual_entry", manual_entry_id_, "*delete*", manual_entry_id_, "", reason)
        with self._connect() as conn:
            conn.execute("DELETE FROM manual_entries WHERE manual_entry_id = ?", (manual_entry_id_,))
            conn.execute("DELETE FROM transaction_links WHERE manual_entry_id = ?", (manual_entry_id_,))

    # -- links ----------------------------------------------------------------

    def add_link(self, manual_entry_id_: str, transaction_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO transaction_links (manual_entry_id, transaction_id, created_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(manual_entry_id, transaction_id) DO NOTHING""",
                (manual_entry_id_, transaction_id, _now()),
            )
        self._audit("manual_entry", manual_entry_id_, "*link*", "", transaction_id, None)

    def remove_link(self, manual_entry_id_: str, transaction_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM transaction_links WHERE manual_entry_id = ? AND transaction_id = ?",
                (manual_entry_id_, transaction_id),
            )

    def get_links_df(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query("SELECT * FROM transaction_links", conn)

    def links_for_transaction(self, transaction_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT manual_entry_id FROM transaction_links WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchall()
        return [r["manual_entry_id"] for r in rows]

    # -- categories -----------------------------------------------------------

    def add_category(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO categories (name, created_at) VALUES (?, ?) "
                "ON CONFLICT(name) DO NOTHING",
                (name, _now()),
            )
        self._audit("category", name, "*create*", "", name, None)

    def get_categories(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    # -- aliases (UI-added) ---------------------------------------------------

    def add_alias(self, person_key: str, alias: str, display_name: str = "", related_flag: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO aliases (person_key, alias, display_name, related_flag, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(person_key, alias) DO NOTHING""",
                (person_key, alias.strip().lower(), display_name, related_flag, _now()),
            )
        self._audit("alias", person_key, "*create*", "", alias, None)

    def get_aliases_df(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query("SELECT * FROM aliases", conn)

    # -- settings -------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        old = self.get_setting(key)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, str(value), _now()),
            )
        if str(old or "") != str(value):
            self._audit("setting", key, key, old, value, None)

    # -- audit ----------------------------------------------------------------

    def _audit(self, entity_type, entity_id, field, old_value, new_value, reason) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (entity_type, entity_id, field, old_value, new_value, reason, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (entity_type, str(entity_id), field,
                 None if old_value is None else str(old_value),
                 None if new_value is None else str(new_value),
                 reason, _now()),
            )

    def get_audit_df(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query(
                "SELECT * FROM audit_log ORDER BY id DESC", conn
            )


# --- overlay helpers (operate on a DecisionStore's data) --------------------

def merge_decisions(df: pd.DataFrame, store: "DecisionStore") -> pd.DataFrame:
    """Overlay manual decisions from ``store`` onto a classified ledger.

    Manual values win over auto values, but only where the user actually set
    something. Auto classification is never silently discarded otherwise. Also
    fills linked_transaction_ids from the links table.
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    decisions = store.get_decisions_df()
    links = store.get_links_df()

    dec_by_id = {row["transaction_id"]: row for _, row in decisions.iterrows()} if not decisions.empty else {}
    links_by_txn: dict[str, list[str]] = {}
    if not links.empty:
        for _, lk in links.iterrows():
            links_by_txn.setdefault(lk["transaction_id"], []).append(lk["manual_entry_id"])

    for idx, row in out.iterrows():
        txn_id = row["transaction_id"]
        out.at[idx, "linked_transaction_ids"] = ",".join(links_by_txn.get(txn_id, []))
        out.at[idx, "is_linked_entry"] = bool(links_by_txn.get(txn_id))

        dec = dec_by_id.get(txn_id)
        if dec is None:
            continue

        if _has(dec.get("category")):
            out.at[idx, "category"] = dec["category"]
            out.at[idx, "classification_status"] = "manual"
            out.at[idx, "classification_reason"] = (
                f'User manually set category "{dec["category"]}". '
                + str(row.get("classification_reason") or "")
            ).strip()
        if _has(dec.get("subcategory")):
            out.at[idx, "subcategory"] = dec["subcategory"]
        if _has(dec.get("manual_comment")):
            out.at[idx, "manual_comment"] = dec["manual_comment"]
        if _has(dec.get("manual_review_status")):
            out.at[idx, "manual_review_status"] = dec["manual_review_status"]
        if _has(dec.get("manual_flags")):
            out.at[idx, "manual_flags"] = dec["manual_flags"]

        # Manual person override lets the user mark relation even with no alias.
        person = (dec.get("manual_person") or "").lower()
        if person in ("benazir", "both"):
            out.at[idx, "is_benazir_related"] = True
        if person in ("nazrana", "both"):
            out.at[idx, "is_nazrana_related"] = True

    return out


def manual_entries_as_rows(store: "DecisionStore") -> pd.DataFrame:
    """Render manual entries as schema-shaped ledger rows (is_manual_entry=True).

    These are clearly marked so they are never confused with bank-extracted
    transactions. debit/credit are derived from the entry's direction.
    """
    from src.models.transaction_schema import (  # local import avoids a cycle
        PAID_OUT,
        RECEIVED,
        SCHEMA_COLUMNS,
        ensure_columns,
    )

    entries = store.get_manual_entries_df()
    if entries.empty:
        return ensure_columns(pd.DataFrame(), SCHEMA_COLUMNS)

    links = store.get_links_df()
    links_by_entry: dict[str, list[str]] = {}
    if not links.empty:
        for _, lk in links.iterrows():
            links_by_entry.setdefault(lk["manual_entry_id"], []).append(lk["transaction_id"])

    records = []
    for _, e in entries.iterrows():
        direction = (e.get("direction") or "").upper()
        amount = float(e.get("amount") or 0.0)
        debit = amount if direction == PAID_OUT else 0.0
        credit = amount if direction == RECEIVED else 0.0
        person = (e.get("person") or "").lower()
        records.append({
            "transaction_id": e["manual_entry_id"],
            "source_bank": "MANUAL",
            "source_file": "(manual entry)",
            "source_parser": "manual",
            "source_format": "manual",
            "transaction_date": e.get("entry_date"),
            "value_date": e.get("entry_date"),
            "description": e.get("description") or "",
            "raw_description": e.get("description") or "",
            "debit": debit,
            "credit": credit,
            "amount": amount,
            "direction": direction or "UNKNOWN",
            "counterparty_name": e.get("person") or "",
            "detected_names": e.get("person") or "",
            "category": e.get("category") or "",
            "subcategory": e.get("subcategory") or "",
            "classification_status": "manual",
            "classification_reason": e.get("reason") or "Manual entry.",
            "confidence": 1.0,
            "is_benazir_related": "benazir" in person,
            "is_nazrana_related": person in ("nazrana", "najrana"),
            "is_manual_entry": True,
            "is_linked_entry": bool(links_by_entry.get(e["manual_entry_id"])),
            "manual_comment": e.get("reason") or "",
            "manual_review_status": e.get("review_status") or "",
            "linked_transaction_ids": ",".join(links_by_entry.get(e["manual_entry_id"], [])),
            "created_at": e.get("created_at"),
            "updated_at": e.get("updated_at"),
        })

    return ensure_columns(pd.DataFrame(records), SCHEMA_COLUMNS)


def _has(value) -> bool:
    """True if a decision field holds a meaningful (non-empty) value."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip() != ""

# Bank Ledger Dashboard

A simple, **local-only** Streamlit dashboard for reviewing bank statements and
maintaining a manual, documented transaction ledger.

It reads your exported bank statements (ICICI and HDFC `.xls` today, PDFs later),
builds one combined transaction history, helps you find and document
transactions involving specific people, flags large payments, and lets you
classify, comment on, and link transactions by hand — with every manual decision
saved so it survives restarts.

> **This tool does not make legal or financial conclusions.** It helps *you*
> organise, classify, and export your own transaction evidence and notes. You
> must verify every transaction yourself.

---

## Project purpose

Document and review transactions involving:

- **Benazir Rahaman**
- **Nazrana / Najrana** (her mother) — and spelling variations
- payments made on her behalf even when her name isn't in the narration
  (e.g. an insurance premium, cash, or an unclear UPI reference)

For each transaction you can record: paid vs received, a category, a review
status (confirmed / probable / not related / unknown / review later / do not
remember), free-text reasoning, and links to manual entries. Nothing about
"owed" or "repayment" is ever inferred automatically — that only comes from
**your** manual classification.

---

## Read-only guarantee

The folder **`all_bank_statements/` is strictly read-only.** The app never
modifies, renames, moves, deletes, or writes anything inside it. Everything the
app generates goes under `data/`:

```
data/
  cache/        decisions.sqlite  (your manual edits)
  processed/    unified_extraction.csv, combined_transactions.csv
  exports/      report downloads you save
  logs/         what was read, parser errors
```

On startup the sidebar shows:

> Source files are read-only. This app will not modify `all_bank_statements/`.
> Manual edits are stored separately in `data/cache/decisions.sqlite`.

---

## Setup

Requires Python 3.10+.

```bash
# 1. (recommended) create a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2. install dependencies
pip install -r requirements.txt
```

`xlrd` is required to read the old binary `.xls` exports from ICICI/HDFC.

## How to run

```bash
streamlit run app.py
```

Your browser opens at `http://localhost:8501`. All processing is local — no
cloud upload, no external API calls, no telemetry.

## Where to place bank statements

Drop exported statements under `all_bank_statements/<BANK>/`:

```
all_bank_statements/
  ICICI/   OpTransactionHistory*.xls
  HDFC/    Acct Statement_*.xls
```

The app auto-discovers files, picks the right parser per bank, and skips files
it cannot read (showing the problem in the UI rather than crashing).

---

## The pages

1. **Unified Extraction View** — exactly what each parser pulled from each file,
   with a per-file parse report (rows, warnings, errors, checksum). Verify
   extraction here.
2. **Combined Ledger** — the master transaction history across all sources, with
   filters (bank, date, direction, search), totals, and an inline editor.
3. **Name / Person Review** — transactions matching Benazir / Nazrana aliases,
   net paid/received, per-person review. You can also mark *any* transaction as
   related even when no alias matched.
4. **Large Payments** — everything at/above a dynamic threshold (default
   ₹3,000), editable live and saved.
5. **Classification Summary** — totals overall, per-person, and per-category,
   plus focused exports.
6. **Manual Entries** — record payments that don't appear with the person's name
   and link them to one or more bank transactions.

---

## How manual decisions are stored

All edits are written to a local SQLite database, `data/cache/decisions.sqlite`,
keyed by a stable `transaction_id`. Because the id is derived from the
transaction's own fields, your decisions re-attach to the right rows every time
you re-read the statements. The database keeps:

- `transaction_decisions` — your per-transaction category / comment / review
  status / flags / person mark
- `manual_entries` — payments you add by hand
- `transaction_links` — links between manual entries and bank transactions
- `categories`, `aliases` — additions you make from the UI
- `settings` — e.g. the saved large-payment threshold
- `audit_log` — every change, with old value, new value, timestamp, and reason

Auto-classification is **never** allowed to overwrite a manual decision. Use the
"Reset to auto" button on a transaction if you want to discard your manual
classification for it.

## How to export reports

Every table has **⬇ CSV** and **⬇ XLSX** download buttons. The Classification
Summary page additionally offers focused exports: Benazir-related,
Nazrana-related, large payments, unknown/review-later, manual entries, the full
ledger with comments, and a one-table summary report. Saved exports go to
`data/exports/`.

---

## How to add a new bank parser

1. Create `src/parsers/<bank>_<format>_parser.py`.
2. Subclass `BaseParser` (`src/parsers/base.py`), set `bank_name` and
   `supported_extensions`, and implement `can_parse(path)` and `parse(path)`.
3. `parse` must return a `ParseResult` whose DataFrame uses the
   `PARSER_OUTPUT_COLUMNS` from `src/models/transaction_schema.py`. Reuse
   `utils.dates.parse_date` and `utils.money.parse_amount`.
4. Register it in `build_parser_registry()` in
   `src/services/extraction_service.py` (bank-specific parsers before the
   generic fallback).

PDF parsers (`*_pdf_parser.py`, `generic_pdf_parser.py`) are present as
documented placeholders — see their docstrings for the intended pdfplumber-based
approach.

## How to add aliases / categories / thresholds

- **Aliases:** edit `config/aliases.yml`, or add them live on the Name Review
  page. Matching is case-insensitive and token-aware.
- **Categories:** edit `config/categories.yml`, or add them live (stored in the
  DB and merged with the config list).
- **Large-payment threshold:** edit `config/thresholds.yml`, or change it live on
  the Large Payments page (the saved value overrides the file).

---

## Project layout

See [`docs/REPOSITORY_GUIDE.md`](docs/REPOSITORY_GUIDE.md) for a full tour of the
folders, the parser/dashboard flow, where the cache and exports live, and how
transaction ids are generated. See [`docs/MEMORY.md`](docs/MEMORY.md) for the
project's remembered context (and the important caveat that it is seed
information, not proof).

## License

For personal use.

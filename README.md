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

The primary UI is a **FastAPI + Tabulator** web app — a real interactive
dashboard with right-click row actions and inline editing:

```bash
python run_web.py            # then open http://127.0.0.1:8000
```

A legacy Streamlit UI is still available (`streamlit run app.py`) but the web app
is the recommended interface.

All processing is local — no cloud upload, no external API calls, no telemetry.
Tabulator.js is vendored under `web/static/vendor/`, so the app runs fully
offline (nothing is fetched from a CDN at runtime).

### Working in the dashboard

- **Right-click any transaction row** for a context menu: reclassify, mark as a
  self-transfer, mark as related to Benazir / Nazrana, set a review status, add a
  note or flags, or reset to the automatic classification.
- **Double-click** a category, review-status, or note cell to edit it inline.
- Every edit is saved immediately to `data/cache/decisions.sqlite` and survives
  re-reads and restarts.

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

## The money model (important)

Headline totals reflect **real money in and out**, not internal shuffling:

- **Self-transfers are excluded.** Money moving between your own accounts/
  instruments (ICICI ↔ HDFC ↔ PNB ↔ SBI, loading your own UPI handle, moving to
  a Fixed Deposit, paying your own credit-card bill) is detected via
  `config/self_identity.yml` and left out of income/expense. Without this, the
  same rupee gets counted twice (a debit in one statement, a credit in another).
- **Exact duplicates are excluded.** Overlapping statement exports can list the
  same transaction twice; identical rows (including running balance) are flagged.
- **Income** = salary (KoiReader, Primus Global), tax refunds, interest, etc.
- **Investments** (Groww, Zerodha, SGB, PPF, NPS, stocks, FDs) are shown
  separately as *savings*, not counted as expense.
- **Real expense** = real money out that isn't an investment.

Classification is transparent regex (see `src/services/classification_rules.py`).
Each transaction gets one **primary category** plus any number of descriptive
**tags** (e.g. a Kotak premium → category `insurance`, tags `insurance,
tax_saving_80c`). Nothing about "owed" is ever inferred — that's manual only.

## The pages (web app)

1. **Ledger** — the master grid: filter by bank / direction / category / search,
   hide self-transfers, "pending only" view, right-click actions, inline edit,
   ✓ confirm / ✗ deny each auto-classification.
2. **Benazir** — dedicated relationship ledger organised as **masters**
   (SUMMARY-A, B, …). Each master is one logical expense (iPhone, Zara's iPhone,
   Axis loan, studies, Kotak, salary-replacement, rent, job-comp) with an
   **editable header** (title / details / base date / declared net) and its
   backing records sorted latest-first. *Historic* records (e.g. loan disbursal
   mechanics) are evidence only and don't add to the net. Confirm ✓ / deny ✗
   each record, and **export the whole page to CSV** (SUMMARY-A / A.1 / A.2 …).
   Masters are seeded from `config/benazir_masters.yml`
   (`python scripts/seed_benazir.py`).
3. **Search** — generic filter by keyword, amount range, date range, direction,
   category, and person.
4. **Family** — my mother (Husna) and sister (Zarinne) as *self-investment*,
   with a per-person **saved** override (default = net sent).
5. **Investments** — bank-detected (Groww, Zerodha, SGB, PPF, NPS) + 80C subtotal,
   plus your manually-recorded portfolio (Kotak, WazirX, MF accounts).
6. **Income** — sectioned by source: KoiReader salary, Primus freelancing, tax
   refunds, interest, insurance claims.
7. **Accident & Marriage** — the 08 Feb 2024 accident (ICICI Lombard claim +
   recovery spend, incl. physio "Hamid") and ~29 Apr 2023 marriage window,
   auto-classified for you to confirm.
8. **Large** — everything at/above a live, savable threshold.
9. **Manual** — record payments that don't show the person's name.
10. **Summary** — approval status (approved / unverified / unknown), interactive
    pie/bar/line charts, and data-coverage (missing months).

### The approval workflow

Every auto-classification starts **unverified**. Confirm (✓) keeps it, deny (✗)
sends it to `unknown`, or reclassify to any category — all from the right-click
menu or the ✓/✗ columns. The Summary tab shows how many remain to review.

> **People in the data:** `9471351129` = sister Zarinne, `9852378779` = mother
> Husna, `8617663869` = Benazir. Several Benazir payments were sent from PNB/SBI
> accounts not yet loaded — they appear as recalled manual entries (see
> `config/benazir_reasons.yml`). See
> [`docs/income_vs_spend_clarifications.md`](docs/income_vs_spend_clarifications.md)
> for how income vs expense reconciles.

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

You are a senior Python engineer. Build a simple, local, human-readable Streamlit or Flask dashboard for analyzing my bank statements and manually maintaining a transaction ledger.

Prefer **Streamlit** unless Flask is clearly better. Keep the app modular, readable, and boring. Avoid AI bloat, over-engineering, hidden magic, complex abstractions, or unnecessary frameworks.

## Core Principle

The folder `all_bank_statements/` is **STRICTLY READ ONLY**.

Never modify, rename, move, overwrite, delete, clean, convert, or write anything inside `all_bank_statements/`.

All generated files, caches, exports, logs, processed files, and user decisions must go outside it, preferably under:

```text
data/
  cache/
  processed/
  exports/
  logs/
docs/
```

The app must work locally only. No cloud upload, no external API calls, no telemetry.

---

# Project Purpose

I want to analyze and document all transactions involving:

* `Benazir`
* `Benazir Rahaman`
* `Nazrana`
* `Najrana`
* possible spelling variations of Nazrana/Najrana
* transactions that may indirectly relate to Benazir or her mother
* payments made on behalf of her, even if the transaction narration does not directly contain her name

The purpose is to build a documented ledger showing:

* what money was paid by me
* what money was received by me
* what may have been taken, given, repaid, owed, or unclear
* reasoning/comments for each classification
* manual review flags
* unknown or “do not remember” flags
* linked manual entries for transactions not directly obvious from bank statements

This is for personal internal documentation and review. The software must not make legal conclusions. It should help me organize evidence, notes, transaction history, and reasoning.

Known context to include as editable seed data, not as automatic proof:

* My name: Farhan Hai Khan.
* Benazir Rahaman is the relevant person.
* Nazrana/Najrana refers to her mother.
* There may be related payments such as Kotak Life Insurance or other payments made on behalf of her, even if the narration does not directly mention her.

These remembered details should be stored in an editable documentation/seed file, not hardcoded as final truth.

---

# Current Input Files

Create support for the following current structure:

```text
all_bank_statements/
  ICICI/
    OpTransactionHistory27-06-2026.xls-01-07-00.xls
    OpTransactionHistory27-06-2026.xls-01-08-42.xls
    OpTransactionHistory27-06-2026.xls-01-09-41.xls
    OpTransactionHistory27-06-2026.xls-01-11-01.xls
    OpTransactionHistory27-06-2026.xls-01-12-04.xls
    OpTransactionHistory27-06-2026.xls-01-12-46.xls

  HDFC/
    Statement_9965_27062026_01.15.56.xls
```

Current files are parseable Excel/XLS files in predefined formats, but the code must be designed so future PDF statements can be added.

Create separate parser files:

```text
src/parsers/icici_excel_parser.py
src/parsers/hdfc_excel_parser.py
src/parsers/icici_pdf_parser.py
src/parsers/hdfc_pdf_parser.py
src/parsers/generic_pdf_parser.py
```

PDF parser files can initially be placeholders, but they must have clear docstrings explaining the intended logic:

* assume readable PDFs first
* extract text
* extract tables using Python libraries
* normalize rows into the same transaction schema
* avoid OCR unless needed later
* keep parser code simple and replaceable

Suggested libraries:

* `pandas`
* `openpyxl`
* `xlrd`, if required for old `.xls`
* `pdfplumber` for readable PDFs
* optional `tabula-py` or `camelot` only if documented and clearly separated

---

# Required Repository Structure

Create a clean repo like this:

```text
bank-ledger-dashboard/
  app.py
  requirements.txt
  README.md

  all_bank_statements/
    # read-only input folder, never modified by code

  config/
    aliases.yml
    categories.yml
    thresholds.yml

  data/
    cache/
      decisions.sqlite
    processed/
      unified_extraction.csv
      combined_transactions.csv
    exports/
    logs/

  docs/
    MEMORY.md
    REPOSITORY_GUIDE.md

  src/
    __init__.py

    parsers/
      __init__.py
      base.py
      icici_excel_parser.py
      hdfc_excel_parser.py
      icici_pdf_parser.py
      hdfc_pdf_parser.py
      generic_pdf_parser.py

    services/
      __init__.py
      file_discovery.py
      extraction_service.py
      normalization_service.py
      classification_service.py
      decision_store.py
      export_service.py

    models/
      __init__.py
      transaction_schema.py

    utils/
      __init__.py
      hashing.py
      logging_setup.py
      money.py
      dates.py
```

Keep this flexible, but maintain separation between:

* parsing
* normalization
* classification
* manual decisions/cache
* dashboard UI
* exports

---

# Unified Transaction Schema

Every parser must transform data into a common schema.

At minimum:

```text
transaction_id
source_bank
source_file
source_folder
source_sheet
source_row_number
source_parser
source_format
extraction_timestamp

transaction_date
value_date
description
raw_description
reference_number
cheque_number

debit
credit
amount
direction
balance

counterparty_name
detected_names
matched_aliases

category
subcategory
classification_status
classification_reason
confidence

is_benazir_related
is_nazrana_related
is_large_payment
is_manual_entry
is_linked_entry

manual_comment
manual_review_status
manual_flags
linked_transaction_ids
created_at
updated_at
```

Rules:

* `debit` means money paid out.
* `credit` means money received.
* `amount` should be absolute transaction amount.
* `direction` should be one of:

  * `PAID_OUT`
  * `RECEIVED`
  * `UNKNOWN`
* Keep `raw_description` exactly as extracted.
* Keep `description` as cleaned readable text.
* Do not delete raw extracted fields.
* Generate stable `transaction_id` using a hash of key fields such as:

  * bank
  * date
  * description
  * debit
  * credit
  * balance
  * source file
  * source row number

---

# Dashboard Pages / Tabs

Build the dashboard with the following pages/tabs.

## Page 1: Unified Extraction View

This page shows the extracted data from all sources before heavy transformation.

It must show:

* source bank
* source file
* source sheet
* source row number
* parser used
* raw extracted columns
* normalized columns
* any parser warnings/errors

Purpose: I should be able to verify what was extracted from which file.

Features:

* filter by bank
* filter by file
* search description
* show parse warnings
* export current view to CSV/XLSX

---

## Page 2: Combined Transactions View

This page creates and displays one combined transformed transaction history across all sources.

It must show:

* all normalized transactions
* bank
* date
* description
* debit
* credit
* amount
* direction
* balance
* category
* detected names
* manual review status
* comments

Features:

* sort by date
* filter by bank
* filter by date range
* filter by debit/credit
* search description
* export combined data
* preserve manual classifications across runs

This page is the master ledger.

---

## Page 3: Name-Based Search / Person-Focused Review

This page must focus on transactions involving:

* Benazir
* Benazir Rahaman
* Nazrana
* Najrana
* spelling variations
* configurable aliases from `config/aliases.yml`

The alias system must be dynamic.

Example `aliases.yml`:

```yaml
people:
  benazir:
    display_name: "Benazir Rahaman"
    aliases:
      - "benazir"
      - "benazir rahaman"
      - "rahman benazir"
      - "b rahaman"

  nazrana:
    display_name: "Nazrana / Najrana"
    aliases:
      - "nazrana"
      - "najrana"
      - "nazrana khatun"
      - "najrana khatun"
```

This page must show:

* matched transactions
* which alias matched
* whether paid out or received
* net paid
* net received
* net difference
* manual comments
* classification dropdown
* checkbox/flag for:

  * confirmed related
  * probably related
  * not related
  * unknown
  * review later
  * do not remember

Allow me to manually mark a transaction as related even if no alias matched.

---

## Page 4: Large Payments Review

Create a section called `large_payments`.

Default threshold: ₹3,000.

The threshold must be dynamic and editable from the UI and/or `config/thresholds.yml`.

Example:

```yaml
large_payment_threshold: 3000
```

This page must show all transactions where absolute amount is greater than or equal to the threshold.

Features:

* edit threshold live
* filter by paid/received
* filter by bank
* filter by date
* mark as:

  * large expense
  * loan/repayment
  * Benazir-related
  * Nazrana-related
  * family expense
  * personal expense
  * business/work expense
  * unknown
  * review later
  * new category
* add comments
* link to manual entries
* export large payments report

Classification must be dynamic, not hardcoded.

---

## Page 5: Classification Summary

This page must summarize categories and people.

It must show:

* total paid out
* total received
* net paid
* net received
* net balance/difference
* net owed, if manually marked
* category-wise totals
* person-wise totals
* Benazir-related total paid
* Benazir-related total received
* Nazrana/Najrana-related total paid
* Nazrana/Najrana-related total received
* unknown/review-later totals

Important: “owed” must not be automatically assumed. It must come from manual classification.

Allow export based on each category:

* export Benazir-related transactions
* export Nazrana-related transactions
* export large payments
* export unknown/review-later transactions
* export manual entries
* export full ledger with comments
* export summary report

Export formats:

* CSV
* XLSX
* optional PDF report later

---

# Manual Editing Requirements

I will not edit Excel files directly.

All edits must happen live inside the dashboard.

The app must allow me to:

* add/edit comments
* change category
* mark person involved
* flag as unknown
* flag as review later
* mark as do not remember
* add reasoning
* mark whether transaction is confirmed/probable/not related
* create manual entries
* link manual entries to one or more bank transactions
* export updated results

Manual decisions must persist across app restarts.

Use SQLite for this:

```text
data/cache/decisions.sqlite
```

Tables should include:

```text
transaction_decisions
manual_entries
transaction_links
categories
aliases
audit_log
settings
```

Each decision should be tied to `transaction_id`.

Manual entries should have their own IDs.

Every user edit should preserve:

* transaction ID
* old value
* new value
* timestamp
* reason/comment if available

---

# Manual Entries

Manual entries are required because some payments may not directly appear with the relevant person’s name.

Example:

* Kotak Life Insurance payment made on behalf of Benazir
* cash payment
* UPI payment with unclear narration
* repayment made under another reference
* payment linked to family/member/context instead of direct name

Manual entry fields:

```text
manual_entry_id
entry_date
person
amount
direction
category
subcategory
description
reason
evidence_note
linked_transaction_ids
review_status
created_at
updated_at
```

Manual entries must be clearly marked as manual and never confused with bank-extracted transactions.

---

# Classification System

Use simple rule-based classification.

Do not use AI or external APIs.

Classification must be editable and dynamic.

Initial categories:

```yaml
categories:
  - benazir_payments
  - nazrana_payments
  - benazir_repayment
  - large_expenses
  - loan_or_emi
  - insurance
  - personal_expense
  - family_expense
  - cash_withdrawal
  - transfer
  - salary_or_income
  - unknown
  - review_later
```

The app must allow adding new categories from the UI or config file.

Classification rules should be transparent. For each classified transaction, show a simple reason like:

```text
Matched alias "benazir" in transaction description.
Amount above configured large payment threshold ₹3,000.
User manually marked this as Kotak Life Insurance related to Benazir.
```

Never overwrite a manual classification automatically unless I explicitly choose to reset/reclassify.

---

# Parser Requirements

Each bank parser should be simple and easy to understand.

Each parser must:

* read file safely
* detect sheets
* locate transaction rows
* map bank-specific columns into common schema
* preserve raw values
* return a DataFrame
* collect parser warnings
* not write to input files

Parser design:

```python
class BaseParser:
    bank_name: str
    supported_extensions: list[str]

    def can_parse(self, path: Path) -> bool:
        ...

    def parse(self, path: Path) -> ParseResult:
        ...
```

`ParseResult` should include:

```text
transactions_dataframe
warnings
errors
metadata
```

Create:

```text
icici_excel_parser.py
hdfc_excel_parser.py
icici_pdf_parser.py
hdfc_pdf_parser.py
generic_pdf_parser.py
```

PDF parser placeholders should include clear TODOs but should not break the app.

---

# Safety and Read-Only Guardrails

Implement safeguards:

* source folder path should be treated as read-only
* no write calls inside `all_bank_statements`
* all output goes to `data/`
* create file checksums for source files
* log what files were read
* log parser errors
* never crash the whole app if one file fails
* show parser failures in the UI

Add a startup warning:

```text
Source files are read-only. This app will not modify all_bank_statements/.
Manual edits are stored separately in data/cache/decisions.sqlite.
```

---

# Documentation

Create:

## README.md

Include:

* project purpose
* setup instructions
* how to run
* where to place bank statements
* read-only warning
* how manual decisions are stored
* how to export reports
* how to add a new bank parser
* how to add aliases/categories

## docs/MEMORY.md

Include project memory and context:

* purpose of documenting transactions involving Benazir/Nazrana/Najrana
* remembered repayment context
* Axis EMI context
* warning that remembered context is seed information, not automatic proof
* user should verify every transaction manually
* source bank files must remain untouched

## docs/REPOSITORY_GUIDE.md

Explain:

* folder structure
* parser flow
* dashboard flow
* where cache lives
* where exports go
* where categories/aliases live
* how transaction IDs are generated
* how to extend the system

---

# UI Expectations

The UI should be practical and simple.

Use:

* tables
* filters
* dropdowns
* checkboxes
* text areas for comments
* save buttons
* export buttons

Avoid fancy visuals unless useful.

Useful summary cards:

* total paid out
* total received
* Benazir-related paid
* Benazir-related received
* Nazrana-related paid
* Nazrana-related received
* large payments count
* review-later count
* unknown count

Use Indian rupee formatting.

---

# Acceptance Criteria

The project is complete when:

1. The app can scan `all_bank_statements/`.
2. It can parse ICICI XLS files.
3. It can parse HDFC XLS files.
4. It produces a unified extraction view.
5. It produces a combined transaction ledger.
6. It detects Benazir/Nazrana/Najrana-related transactions using aliases.
7. It flags large payments above a dynamic threshold, default ₹3,000.
8. It allows manual classification, comments, and review flags.
9. It allows manual entries and links them to source transactions.
10. Manual edits persist across app restarts.
11. It exports filtered/category-wise reports.
12. It never modifies original bank statement files.
13. The code is readable, modular, documented, and simple.
14. README.md, docs/MEMORY.md, and docs/REPOSITORY_GUIDE.md are created.
15. Parser placeholders exist for readable PDFs.

---

# Coding Style

Use clear Python.

Add docstrings where useful.

Prefer explicit simple logic over clever abstractions.

Avoid hiding important logic.

Keep functions short.

Use meaningful names.

Do not create unnecessary layers.

Do not use machine learning or AI classification.

Do not infer debts automatically.

Manual user decisions are the source of truth for owed/repayable classification.

The dashboard should help me review, document, classify, and export my financial transaction evidence safely.

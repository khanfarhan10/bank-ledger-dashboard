# Repository Guide

A tour of how the code is organised and how data flows through it.

---

## Folder structure

```
bank-ledger-dashboard/
├── app.py                     # Streamlit UI: data loading + 6 pages + router
├── requirements.txt
├── README.md
│
├── all_bank_statements/       # READ-ONLY source statements (never written to)
│   ├── ICICI/  OpTransactionHistory*.xls
│   └── HDFC/   Acct Statement_*.xls
│
├── config/                    # editable configuration
│   ├── aliases.yml            # people -> aliases for name matching
│   ├── categories.yml         # category list + review statuses
│   └── thresholds.yml         # large-payment threshold
│
├── data/                      # everything the app generates (gitignored)
│   ├── cache/decisions.sqlite # manual decisions, entries, links, settings, audit
│   ├── processed/             # unified_extraction.csv, combined_transactions.csv
│   ├── exports/               # saved report downloads
│   └── logs/                  # app-YYYY-MM-DD.log
│
├── docs/
│   ├── master_prompt.md       # the original build specification
│   ├── MEMORY.md              # project context (seed info, not proof)
│   └── REPOSITORY_GUIDE.md    # this file
│
└── src/
    ├── models/
    │   └── transaction_schema.py   # the unified schema (single source of truth)
    ├── parsers/
    │   ├── base.py                 # BaseParser + ParseResult contract
    │   ├── icici_excel_parser.py   # implemented
    │   ├── hdfc_excel_parser.py    # implemented
    │   ├── icici_pdf_parser.py     # documented placeholder
    │   ├── hdfc_pdf_parser.py      # documented placeholder
    │   └── generic_pdf_parser.py   # documented placeholder
    ├── services/
    │   ├── file_discovery.py       # find + checksum source files
    │   ├── extraction_service.py   # parser registry; run parsers; per-file reports
    │   ├── normalization_service.py# amount/direction, txn id, name detection
    │   ├── classification_service.py# transparent rule-based auto-classification
    │   ├── decision_store.py       # SQLite store + decision/entry overlay helpers
    │   ├── export_service.py       # CSV/XLSX bytes + saved exports
    │   └── pipeline.py             # orchestration tying the steps together
    └── utils/
        ├── config_loader.py        # read the YAML configs (safe defaults)
        ├── dates.py                # day-first date parsing -> ISO
        ├── money.py                # amount parsing + ₹ Indian formatting
        ├── hashing.py              # stable transaction_id / manual_entry_id
        └── logging_setup.py        # file + console logging
```

---

## Parser flow

```
all_bank_statements/  ──file_discovery──▶  [DiscoveredFile + sha256 checksum]
                                              │
                                  extraction_service.select_parser()
                                              │  (first parser whose can_parse() is True)
                                              ▼
                         IciciExcelParser / HdfcExcelParser / …  ──▶  ParseResult
                                              │   (DataFrame in PARSER_OUTPUT_COLUMNS
                                              │    + warnings + errors + metadata)
                                              ▼
                          extraction_service.extract_all()  ──▶  one raw DataFrame
                                                                 + per-file reports
```

Each parser:
- reads the file safely (a bad file yields an error result, never a crash),
- finds the header row, reads transaction rows, stops at legends/footers,
- preserves the raw narration in `raw_description`,
- maps bank-specific columns into the common schema,
- returns a `ParseResult`.

The PDF parsers are placeholders with docstrings describing the intended
pdfplumber-based approach. They return an explanatory error so the app keeps
working until you implement them.

---

## Dashboard flow

```
extract_all ─▶ normalize ─▶ classify ─▶ merge_decisions ─▶ + manual entries ─▶ ledger
   (raw)        (amount/        (auto       (overlay your      (append your
                direction,      category +   saved manual       manual rows,
                txn id,         large flag)  decisions)         clearly marked)
                name match)
```

- **Steps 1–3** (`pipeline.extract_normalize_classify`) depend only on the source
  files and config, so `app.py` caches them with `@st.cache_data`.
- **Steps 4–5** (`pipeline.finalize_ledger`) read the SQLite store and run on
  every interaction, so edits show up immediately.
- Auto-classification never overwrites a manual decision; manual values win in
  `merge_decisions`, and only where you actually set something.

---

## Where things live

| Thing | Location |
|---|---|
| Your manual edits | `data/cache/decisions.sqlite` |
| Raw extraction snapshot | `data/processed/unified_extraction.csv` |
| Combined ledger snapshot | `data/processed/combined_transactions.csv` |
| Saved report exports | `data/exports/` |
| Logs (files read, errors) | `data/logs/app-YYYY-MM-DD.log` |
| Categories & review statuses | `config/categories.yml` (+ DB additions) |
| Aliases | `config/aliases.yml` (+ DB additions) |
| Large-payment threshold | `config/thresholds.yml` (DB setting overrides) |

---

## How transaction IDs are generated

`utils.hashing.transaction_id` builds a stable id from the fields that identify a
transaction:

```
bank | transaction_date | description | debit | credit | balance |
source_file | source_row_number
```

These are joined and hashed (SHA-1, truncated) into `txn_<16 hex>`. Because the
id is deterministic, re-running extraction produces the same ids, which is what
lets manual decisions in SQLite re-attach to the correct rows after a re-read.
Manual entries get their own `man_<16 hex>` ids from
`utils.hashing.manual_entry_id`.

---

## The unified schema

`src/models/transaction_schema.py` is the single source of truth for columns.
`SCHEMA_COLUMNS` is the full ledger shape; `PARSER_OUTPUT_COLUMNS` is the subset
each parser must produce. `ensure_columns()` aligns any DataFrame to a column
list (adding missing columns, dropping extras) so downstream code never has to
defend against partial frames.

Key money rules: `debit` = paid out, `credit` = received, `amount` = absolute
value, `direction` ∈ {`PAID_OUT`, `RECEIVED`, `UNKNOWN`}. `raw_description` is
kept exactly as extracted; `description` is the cleaned, readable version.

---

## How to extend the system

- **New bank / format:** add a parser (subclass `BaseParser`), output
  `PARSER_OUTPUT_COLUMNS`, register it in `build_parser_registry()`. See the
  README section "How to add a new bank parser".
- **Implement a PDF parser:** follow the docstring in the relevant
  `*_pdf_parser.py`; use `pdfplumber` for readable PDFs, only reach for OCR if a
  PDF has no extractable text.
- **New classification rule:** add a transparent keyword rule in
  `classification_service.py` and give it a clear reason string. Keep auto-rules
  light — manual decisions are the source of truth.
- **New page / widget:** add a `page_*` function in `app.py` and register it in
  the `PAGES` dict.

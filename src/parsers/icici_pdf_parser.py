"""Placeholder parser for ICICI PDF statements.

Not implemented yet. The current inputs are .xls files; this stub exists so the
PDF path is obvious when you add ICICI PDFs later.

Intended logic (keep it simple, replaceable, no OCR unless forced):
    1. Open the PDF with pdfplumber (assume a readable, text-based PDF).
    2. Iterate pages; use page.extract_table()/extract_tables() to pull the
       transaction grid. ICICI PDFs typically repeat a column header on each
       page: S No / Value Date / Transaction Date / Cheque Number /
       Transaction Remarks / Withdrawal / Deposit / Balance.
    3. Drop header/footer/legend rows (same idea as the Excel parser).
    4. Map each row into PARSER_OUTPUT_COLUMNS, reusing utils.dates.parse_date
       and utils.money.parse_amount.
    5. Only consider OCR (e.g. pytesseract) if the PDF is a scanned image with
       no extractable text — and document it clearly when you do.

Until implemented, parse() returns a ParseResult carrying a single error so the
app surfaces "PDF parsing not implemented" in the UI instead of crashing.
"""

from __future__ import annotations

from pathlib import Path

from src.parsers.base import BaseParser, ParseResult


class IciciPdfParser(BaseParser):
    bank_name = "ICICI"
    supported_extensions = [".pdf"]

    def can_parse(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        folder = path.parent.name.lower()
        return "icici" in folder

    def parse(self, path: Path) -> ParseResult:
        # TODO: implement using pdfplumber as described in the module docstring.
        return self._empty_result(
            "ICICI PDF parsing is not implemented yet (placeholder). "
            "Add pdfplumber-based extraction in icici_pdf_parser.py.",
            path,
        )

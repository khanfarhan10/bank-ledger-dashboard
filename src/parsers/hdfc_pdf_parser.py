"""Placeholder parser for HDFC PDF statements.

Not implemented yet. The current inputs are .xls files; this stub exists so the
PDF path is obvious when you add HDFC PDFs later.

Intended logic (keep it simple, replaceable, no OCR unless forced):
    1. Open the PDF with pdfplumber (assume a readable, text-based PDF).
    2. HDFC statement tables use columns: Date / Narration / Chq./Ref.No. /
       Value Dt / Withdrawal Amt. / Deposit Amt. / Closing Balance.
       Narrations can wrap across lines, so you may need to merge continuation
       lines that have no date into the previous transaction row.
    3. Drop the header/asterisk/footer rows (same idea as the Excel parser).
    4. Map each row into PARSER_OUTPUT_COLUMNS, reusing utils.dates.parse_date
       and utils.money.parse_amount.
    5. Only consider OCR if the PDF has no extractable text — document it.

Until implemented, parse() returns a ParseResult carrying a single error so the
app surfaces "PDF parsing not implemented" in the UI instead of crashing.
"""

from __future__ import annotations

from pathlib import Path

from src.parsers.base import BaseParser, ParseResult


class HdfcPdfParser(BaseParser):
    bank_name = "HDFC"
    supported_extensions = [".pdf"]

    def can_parse(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        folder = path.parent.name.lower()
        return "hdfc" in folder

    def parse(self, path: Path) -> ParseResult:
        # TODO: implement using pdfplumber as described in the module docstring.
        return self._empty_result(
            "HDFC PDF parsing is not implemented yet (placeholder). "
            "Add pdfplumber-based extraction in hdfc_pdf_parser.py.",
            path,
        )

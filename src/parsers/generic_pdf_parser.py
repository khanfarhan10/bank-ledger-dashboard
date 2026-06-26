"""Placeholder generic PDF parser (fallback for unknown banks).

Not implemented yet. This is the last-resort parser used when a PDF does not
match a known bank's dedicated parser. Keep it conservative: it is better to
report "could not parse" than to guess wrong about someone's money.

Intended logic (keep it simple, replaceable, no OCR unless forced):
    1. Open with pdfplumber and try extract_tables() on each page.
    2. Heuristically locate a table whose header contains date + amount-like
       columns (e.g. 'date', 'narration'/'description', 'withdrawal'/'debit',
       'deposit'/'credit', 'balance').
    3. Best-effort map columns into PARSER_OUTPUT_COLUMNS using fuzzy header
       names; attach loud warnings so the user double-checks the result.
    4. If no plausible table is found, return an error result.
    5. Only consider OCR for scanned PDFs, and document it when added.

Until implemented, parse() returns a ParseResult carrying a single error.
"""

from __future__ import annotations

from pathlib import Path

from src.parsers.base import BaseParser, ParseResult


class GenericPdfParser(BaseParser):
    bank_name = "GENERIC"
    supported_extensions = [".pdf"]

    def can_parse(self, path: Path) -> bool:
        # Generic parser claims any PDF; the registry only falls back to it
        # after bank-specific PDF parsers decline.
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParseResult:
        # TODO: implement a best-effort table extraction as described above.
        return self._empty_result(
            "Generic PDF parsing is not implemented yet (placeholder). "
            "Add a bank-specific parser or implement generic_pdf_parser.py.",
            path,
        )

"""Parser for HDFC Bank account-statement .xls exports.

Observed layout (binary .xls, read with xlrd):

    * Single sheet named 'Sheet 1'.
    * A header/address block at the top.
    * The transaction header row reads:
        Date | Narration | Chq./Ref.No. | Value Dt | Withdrawal Amt. |
        Deposit Amt. | Closing Balance
    * The row immediately below the header is a row of asterisks ('****').
    * Transaction rows follow. Dates use a 2-digit year (dd/mm/yy).
    * A footer block follows ('Generated On:', 'State account branch ...',
      '--- End Of Statement'); these must NOT be treated as data.

Strategy: find the header row by looking for 'Date' + 'Narration' + 'Closing
Balance', skip the asterisk separator, then read rows while the Date column
parses as a date. Amounts arrive as floats (blank when empty).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import xlrd

from src.models.transaction_schema import PARSER_OUTPUT_COLUMNS
from src.parsers.base import BaseParser, ParseResult
from src.utils.dates import looks_like_date, parse_date
from src.utils.money import parse_amount


class HdfcExcelParser(BaseParser):
    bank_name = "HDFC"
    supported_extensions = [".xls", ".xlsx"]

    def can_parse(self, path: Path) -> bool:
        """Match HDFC by folder name or the 'Acct Statement' filename."""
        if path.suffix.lower() not in self.supported_extensions:
            return False
        name = path.name.lower()
        folder = path.parent.name.lower()
        return "hdfc" in folder or "statement" in name and "optransaction" not in name

    def parse(self, path: Path) -> ParseResult:
        try:
            book = xlrd.open_workbook(str(path))
        except Exception as exc:  # noqa: BLE001 - report, never crash the app
            return self._empty_result(f"Could not open HDFC workbook: {exc}", path)

        sheet = book.sheet_by_index(0)
        header_row = self._find_header_row(sheet)
        if header_row is None:
            return self._empty_result(
                "Could not locate the HDFC transaction header row.", path
            )

        rows, warnings = self._read_rows(sheet, header_row, path)
        df = pd.DataFrame(rows, columns=PARSER_OUTPUT_COLUMNS)
        return ParseResult(
            transactions=df,
            warnings=warnings,
            metadata={
                "sheet_name": sheet.name,
                "header_row_index": header_row,
                "rows_extracted": len(df),
            },
        )

    # -- internals -------------------------------------------------------------

    _COL_DATE = 0
    _COL_NARRATION = 1
    _COL_REF = 2
    _COL_VALUE_DATE = 3
    _COL_WITHDRAWAL = 4
    _COL_DEPOSIT = 5
    _COL_BALANCE = 6

    def _find_header_row(self, sheet) -> int | None:
        for r in range(min(sheet.nrows, 60)):
            joined = " ".join(
                str(sheet.cell_value(r, c)).lower()
                for c in range(sheet.ncols)
            )
            if "date" in joined and "narration" in joined and "closing balance" in joined:
                return r
        return None

    def _read_rows(self, sheet, header_row: int, path: Path):
        rows = []
        warnings = []
        skipped = 0

        for r in range(header_row + 1, sheet.nrows):
            date_cell = sheet.cell_value(r, self._COL_DATE)
            date_text = str(date_cell).strip()

            # Skip the asterisk separator row directly under the header.
            if date_text.startswith("*"):
                continue

            # Footer/blank rows have no parseable date -> stop at the footer.
            if not looks_like_date(date_cell):
                if date_text == "":
                    skipped += 1
                    continue
                break

            narration = str(sheet.cell_value(r, self._COL_NARRATION)).strip()
            rows.append(
                {
                    "source_bank": self.bank_name,
                    "source_file": path.name,
                    "source_folder": path.parent.name,
                    "source_sheet": sheet.name,
                    "source_row_number": r,
                    "source_parser": "hdfc_excel_parser",
                    "source_format": "xls",
                    "transaction_date": parse_date(date_cell),
                    "value_date": parse_date(sheet.cell_value(r, self._COL_VALUE_DATE)),
                    "description": _clean_text(narration),
                    "raw_description": narration,
                    "reference_number": str(sheet.cell_value(r, self._COL_REF)).strip(),
                    "cheque_number": "",
                    "debit": parse_amount(sheet.cell_value(r, self._COL_WITHDRAWAL)),
                    "credit": parse_amount(sheet.cell_value(r, self._COL_DEPOSIT)),
                    "balance": parse_amount(sheet.cell_value(r, self._COL_BALANCE)),
                }
            )

        if skipped:
            warnings.append(f"Skipped {skipped} blank row(s) inside the table.")
        if not rows:
            warnings.append("No transaction rows were extracted.")
        return rows, warnings


def _clean_text(text: str) -> str:
    return " ".join(text.split())

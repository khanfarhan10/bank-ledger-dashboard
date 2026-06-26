"""Parser for ICICI Bank 'OpTransactionHistory' .xls exports.

Observed layout (binary .xls, read with xlrd):

    * Single sheet named 'OpTransactionHistory'.
    * Column 0 is always blank; real data starts at column 1.
    * A metadata block at the top (account number, date range, ...).
    * The transaction header row reads:
        S No. | Value Date | Transaction Date | Cheque Number |
        Transaction Remarks | Withdrawal Amount(INR) | Deposit Amount(INR) |
        Balance(INR)
    * Transaction rows follow, each starting with an incrementing S No.
    * After the transactions there is a 'Legends' section explaining codes
      (rows like '20. VPS / IPS - ...'); these must NOT be treated as data.

Strategy: find the header row by looking for 'S No.' + 'Transaction Remarks',
then read rows below it for as long as the Value Date column looks like a date.
All amounts arrive as text and are parsed defensively.
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


class IciciExcelParser(BaseParser):
    bank_name = "ICICI"
    supported_extensions = [".xls", ".xlsx"]

    def can_parse(self, path: Path) -> bool:
        """Match ICICI by folder name or the 'OpTransactionHistory' filename."""
        if path.suffix.lower() not in self.supported_extensions:
            return False
        name = path.name.lower()
        folder = path.parent.name.lower()
        return "icici" in folder or "optransactionhistory" in name

    def parse(self, path: Path) -> ParseResult:
        try:
            book = xlrd.open_workbook(str(path))
        except Exception as exc:  # noqa: BLE001 - report, never crash the app
            return self._empty_result(f"Could not open ICICI workbook: {exc}", path)

        sheet = book.sheet_by_index(0)
        header_row = self._find_header_row(sheet)
        if header_row is None:
            return self._empty_result(
                "Could not locate the ICICI transaction header row.", path
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

    # Data sits one column to the right of the visible labels in these exports.
    _COL_SNO = 1
    _COL_VALUE_DATE = 2
    _COL_TXN_DATE = 3
    _COL_CHEQUE = 4
    _COL_REMARKS = 5
    _COL_WITHDRAWAL = 6
    _COL_DEPOSIT = 7
    _COL_BALANCE = 8

    def _find_header_row(self, sheet) -> int | None:
        """Return the index of the transaction header row, or None."""
        for r in range(min(sheet.nrows, 60)):
            joined = " ".join(
                str(sheet.cell_value(r, c)).lower()
                for c in range(sheet.ncols)
            )
            if "s no" in joined and "transaction remarks" in joined:
                return r
        return None

    def _read_rows(self, sheet, header_row: int, path: Path):
        """Read transaction rows below the header until data clearly ends."""
        rows = []
        warnings = []
        ts = datetime.now(timezone.utc).isoformat()
        skipped = 0

        for r in range(header_row + 1, sheet.nrows):
            value_date_cell = sheet.cell_value(r, self._COL_VALUE_DATE)

            # Stop conditions: the Legends section and trailing notes have no
            # date in the Value Date column. A blank S No. + no date means we
            # are past the transaction list.
            if not looks_like_date(value_date_cell):
                # Tolerate the occasional blank row inside the table, but bail
                # out once we hit the non-date legends/footer region.
                sno = str(sheet.cell_value(r, self._COL_SNO)).strip()
                if sno == "" or not sno.split(".")[0].isdigit():
                    break
                skipped += 1
                continue

            remarks = str(sheet.cell_value(r, self._COL_REMARKS)).strip()
            rows.append(
                {
                    "source_bank": self.bank_name,
                    "source_file": path.name,
                    "source_folder": path.parent.name,
                    "source_sheet": sheet.name,
                    "source_row_number": r,
                    "source_parser": "icici_excel_parser",
                    "source_format": "xls",
                    "transaction_date": parse_date(
                        sheet.cell_value(r, self._COL_TXN_DATE)
                    ),
                    "value_date": parse_date(value_date_cell),
                    "description": _clean_text(remarks),
                    "raw_description": remarks,
                    "reference_number": "",
                    "cheque_number": str(
                        sheet.cell_value(r, self._COL_CHEQUE)
                    ).strip(),
                    "debit": parse_amount(sheet.cell_value(r, self._COL_WITHDRAWAL)),
                    "credit": parse_amount(sheet.cell_value(r, self._COL_DEPOSIT)),
                    "balance": parse_amount(sheet.cell_value(r, self._COL_BALANCE)),
                }
            )

        if skipped:
            warnings.append(f"Skipped {skipped} row(s) without a valid date.")
        if not rows:
            warnings.append("No transaction rows were extracted.")
        return rows, warnings


def _clean_text(text: str) -> str:
    """Collapse whitespace for the human-readable description field."""
    return " ".join(text.split())

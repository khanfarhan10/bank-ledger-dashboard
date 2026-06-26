"""Base parser contract shared by all bank parsers.

A parser's only job is: read ONE file and return a ParseResult containing a
DataFrame of raw-but-structured rows (in PARSER_OUTPUT_COLUMNS shape), plus any
warnings/errors and a little metadata. Parsers never write to disk and never
touch the source folder beyond reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.models.transaction_schema import PARSER_OUTPUT_COLUMNS


@dataclass
class ParseResult:
    """Outcome of parsing a single file.

    Attributes:
        transactions: DataFrame with (at least) PARSER_OUTPUT_COLUMNS.
        warnings: non-fatal notes (e.g. "skipped 2 unparseable rows").
        errors: fatal problems for this file (the file may be empty/corrupt).
        metadata: free-form info (sheet names, header row index, row counts).
    """

    transactions: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True if no fatal errors were recorded."""
        return not self.errors

    @property
    def row_count(self) -> int:
        return 0 if self.transactions is None else len(self.transactions)


class BaseParser:
    """Interface every concrete parser implements.

    Subclasses set ``bank_name`` and ``supported_extensions`` and implement
    ``can_parse`` and ``parse``.
    """

    bank_name: str = "UNKNOWN"
    supported_extensions: list[str] = []

    def can_parse(self, path: Path) -> bool:
        """Cheap check: does this parser look applicable to ``path``?

        Default implementation matches on the file extension. Subclasses may
        also inspect the folder name or peek at the file contents.
        """
        return path.suffix.lower() in self.supported_extensions

    def parse(self, path: Path) -> ParseResult:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- helpers for subclasses ------------------------------------------------

    def _empty_result(self, error: str, path: Path) -> ParseResult:
        """Build a ParseResult representing a failed parse (no rows)."""
        return ParseResult(
            transactions=pd.DataFrame(columns=PARSER_OUTPUT_COLUMNS),
            errors=[error],
            metadata={"source_file": str(path), "bank": self.bank_name},
        )

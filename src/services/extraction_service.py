"""Run the right parser on every discovered file and collect the raw extraction.

The extraction service owns the parser registry. For each discovered file it
picks the first parser whose ``can_parse`` returns True, runs it, and gathers
the resulting rows plus any warnings/errors into one DataFrame and one
per-file report. Nothing here writes to the source folder.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.models.transaction_schema import PARSER_OUTPUT_COLUMNS
from src.parsers.base import BaseParser
from src.parsers.generic_pdf_parser import GenericPdfParser
from src.parsers.hdfc_excel_parser import HdfcExcelParser
from src.parsers.hdfc_pdf_parser import HdfcPdfParser
from src.parsers.icici_excel_parser import IciciExcelParser
from src.parsers.icici_pdf_parser import IciciPdfParser
from src.services.file_discovery import DiscoveredFile, discover_files
from src.utils.logging_setup import get_logger


def build_parser_registry() -> list[BaseParser]:
    """Return parsers in priority order.

    Bank-specific parsers come first; the generic PDF parser is the last resort.
    Excel parsers are listed before PDF parsers for the same bank because the
    current inputs are .xls.
    """
    return [
        IciciExcelParser(),
        HdfcExcelParser(),
        IciciPdfParser(),
        HdfcPdfParser(),
        GenericPdfParser(),
    ]


def select_parser(path: Path, registry: list[BaseParser]) -> BaseParser | None:
    """Return the first parser that claims ``path``, or None."""
    for parser in registry:
        if parser.can_parse(path):
            return parser
    return None


def extract_all(source_dir: Path | str = "all_bank_statements") -> dict:
    """Discover, parse, and combine every source file.

    Returns a dict with:
        transactions: DataFrame of raw extracted rows (PARSER_OUTPUT_COLUMNS).
        reports: list of per-file dicts (file, bank, parser, rows, warnings,
                 errors, status, checksum).
        extracted_at: ISO timestamp of this extraction run.
    """
    logger = get_logger()
    registry = build_parser_registry()
    discovered = discover_files(source_dir)

    frames: list[pd.DataFrame] = []
    reports: list[dict] = []

    for item in discovered:
        report = _extract_one(item, registry, logger)
        reports.append(report)
        if report["dataframe"] is not None and not report["dataframe"].empty:
            frames.append(report["dataframe"])

    if frames:
        combined = pd.concat(frames, ignore_index=True)
    else:
        combined = pd.DataFrame(columns=PARSER_OUTPUT_COLUMNS)

    # Drop the bulky DataFrame from the report dicts now that it is combined;
    # the per-file report keeps only lightweight, displayable fields.
    clean_reports = [{k: v for k, v in r.items() if k != "dataframe"} for r in reports]

    logger.info(
        "Extraction complete: %d file(s), %d total row(s)",
        len(discovered), len(combined),
    )
    return {
        "transactions": combined,
        "reports": clean_reports,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def _extract_one(item: DiscoveredFile, registry: list[BaseParser], logger) -> dict:
    """Parse a single discovered file, never raising on bad input."""
    parser = select_parser(item.path, registry)
    if parser is None:
        logger.warning("No parser matched %s", item.path)
        return _report(item, parser=None, rows=0,
                       warnings=[], errors=["No matching parser."],
                       status="no_parser", dataframe=None)

    try:
        result = parser.parse(item.path)
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
        logger.exception("Parser crashed on %s", item.path)
        return _report(item, parser=parser, rows=0,
                       warnings=[], errors=[f"Parser crashed: {exc}"],
                       status="error", dataframe=None)

    status = "ok" if result.ok else "error"
    if result.errors:
        for err in result.errors:
            logger.error("%s: %s", item.name, err)

    return _report(
        item,
        parser=parser,
        rows=result.row_count,
        warnings=result.warnings,
        errors=result.errors,
        status=status,
        dataframe=result.transactions,
    )


def _report(item: DiscoveredFile, *, parser, rows, warnings, errors, status, dataframe) -> dict:
    return {
        "file": item.name,
        "bank_folder": item.bank_folder,
        "parser": type(parser).__name__ if parser else "—",
        "rows": rows,
        "warnings": warnings,
        "errors": errors,
        "status": status,
        "checksum": item.checksum[:12],
        "dataframe": dataframe,
    }

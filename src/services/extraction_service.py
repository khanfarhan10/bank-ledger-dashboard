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
                 errors, status, checksum, stated_date_from, stated_date_to,
                 coverage_gaps).
        overall_gaps: list of 'YYYY-MM' months that have zero transactions
                      across the combined dataset (between first and last date).
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

    overall_gaps = _overall_coverage_gaps(combined)
    if overall_gaps:
        logger.warning(
            "Coverage gaps: %d month(s) with no transactions: %s",
            len(overall_gaps), ", ".join(overall_gaps[:6]) + ("…" if len(overall_gaps) > 6 else ""),
        )

    # Drop the bulky DataFrame from the report dicts now that it is combined.
    clean_reports = [{k: v for k, v in r.items() if k != "dataframe"} for r in reports]

    logger.info(
        "Extraction complete: %d file(s), %d total row(s)",
        len(discovered), len(combined),
    )
    return {
        "transactions": combined,
        "reports": clean_reports,
        "overall_gaps": overall_gaps,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def _extract_one(item: DiscoveredFile, registry: list[BaseParser], logger) -> dict:
    """Parse a single discovered file, never raising on bad input."""
    parser = select_parser(item.path, registry)
    if parser is None:
        logger.warning("No parser matched %s", item.path)
        return _report(item, parser=None, rows=0,
                       warnings=[], errors=["No matching parser."],
                       status="no_parser", dataframe=None, metadata={})

    try:
        result = parser.parse(item.path)
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
        logger.exception("Parser crashed on %s", item.path)
        return _report(item, parser=parser, rows=0,
                       warnings=[], errors=[f"Parser crashed: {exc}"],
                       status="error", dataframe=None, metadata={})

    status = "ok" if result.ok else "error"
    if result.errors:
        for err in result.errors:
            logger.error("%s: %s", item.name, err)

    # Per-file coverage gap detection using the stated date range (if available).
    meta = result.metadata or {}
    stated_from = meta.get("stated_date_from")
    stated_to = meta.get("stated_date_to")
    gaps = _file_coverage_gaps(result.transactions, stated_from, stated_to)
    if gaps:
        gap_msg = f"Missing months within stated range: {', '.join(gaps)}"
        logger.warning("%s: %s", item.name, gap_msg)
        result.warnings.append(gap_msg)

    return _report(
        item,
        parser=parser,
        rows=result.row_count,
        warnings=result.warnings,
        errors=result.errors,
        status=status,
        dataframe=result.transactions,
        metadata=meta,
    )


def _report(item: DiscoveredFile, *, parser, rows, warnings, errors, status, dataframe, metadata) -> dict:
    return {
        "file": item.name,
        "bank_folder": item.bank_folder,
        "parser": type(parser).__name__ if parser else "—",
        "rows": rows,
        "warnings": warnings,
        "errors": errors,
        "status": status,
        "checksum": item.checksum[:12],
        "stated_date_from": metadata.get("stated_date_from"),
        "stated_date_to": metadata.get("stated_date_to"),
        "coverage_gaps": metadata.get("coverage_gaps", []),
        "dataframe": dataframe,
    }


def _file_coverage_gaps(df: pd.DataFrame, stated_from: str | None, stated_to: str | None) -> list[str]:
    """Return months within the stated range that have no transactions.

    ICICI states the range as [from, to) — the to-date is the first day of
    the next period (e.g. '2023-01-01' means up to end of December 2022).
    We treat a to-date that falls on the 1st of a month as exclusive so we
    don't flag the boundary month as a spurious gap.
    """
    if not stated_from or not stated_to or df is None or df.empty:
        return []
    try:
        from_ts = pd.Timestamp(stated_from)
        to_ts = pd.Timestamp(stated_to)
        # Treat 1st-of-month to-dates as exclusive (open end of range).
        if to_ts.day == 1:
            to_ts = to_ts - pd.DateOffset(days=1)
        period_range = pd.period_range(from_ts, to_ts, freq="M")
    except Exception:
        return []
    actual = set(
        pd.to_datetime(df["transaction_date"], errors="coerce")
        .dropna()
        .dt.to_period("M")
    )
    return [str(m) for m in period_range if m not in actual]


def _overall_coverage_gaps(df: pd.DataFrame) -> list[str]:
    """Return months between first and last transaction date that have no rows."""
    if df is None or df.empty:
        return []
    dates = pd.to_datetime(df["transaction_date"], errors="coerce").dropna()
    if len(dates) < 2:
        return []
    try:
        all_months = pd.period_range(dates.min(), dates.max(), freq="M")
    except Exception:
        return []
    actual = set(dates.dt.to_period("M"))
    return [str(m) for m in all_months if m not in actual]

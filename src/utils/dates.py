"""Date parsing helpers.

Bank statements use a handful of day-first formats (dd/mm/yyyy, dd/mm/yy,
dd-Mon-yyyy). We normalise everything to ISO date strings (YYYY-MM-DD) so the
combined ledger sorts correctly and is unambiguous.
"""

from __future__ import annotations

from datetime import datetime

# Day-first formats seen in the ICICI and HDFC exports, most specific first.
_KNOWN_FORMATS = (
    "%d/%m/%Y",   # 28/12/2025  (ICICI)
    "%d/%m/%y",   # 05/01/26    (HDFC)
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d-%b-%Y",   # 27-Jun-2026 (footers)
    "%d-%b-%y",
    "%d %b %Y",
)


def parse_date(value) -> str | None:
    """Parse a bank date cell into an ISO 'YYYY-MM-DD' string, or None.

    Accepts strings in the known day-first formats and datetime objects.
    Returns None when the value is empty or not a recognisable date, so callers
    can distinguish "no date" from a wrong guess.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    text = str(value).strip()
    if text == "" or text.upper() in {"NA", "N/A"}:
        return None

    for fmt in _KNOWN_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def looks_like_date(value) -> bool:
    """True if ``value`` parses as one of the known date formats."""
    return parse_date(value) is not None

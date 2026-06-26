"""Money parsing and Indian-rupee formatting helpers.

Bank exports give amounts as strings ("1,234.56", "0.00", "") or floats. These
helpers turn anything into a clean float and format floats back into readable
rupee strings using the Indian grouping system (lakh/crore).
"""

from __future__ import annotations

import math
import re


def parse_amount(value) -> float:
    """Parse a money value from a bank cell into a float.

    Handles None/NaN, empty strings, thousands separators, currency symbols,
    and trailing 'Cr'/'Dr' markers. Returns 0.0 when the cell is empty or
    cannot be understood (callers decide what "empty" means for debit/credit).
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return 0.0 if (isinstance(value, float) and math.isnan(value)) else float(value)

    text = str(value).strip()
    if text == "" or text.upper() in {"NA", "N/A", "-"}:
        return 0.0

    # Drop currency symbols, commas, spaces and any Cr/Dr suffix.
    text = text.replace(",", "").replace("₹", "").replace("INR", "")
    text = re.sub(r"(?i)\b(cr|dr)\b", "", text).strip()

    try:
        return float(text)
    except ValueError:
        return 0.0


def format_inr(value, *, decimals: int = 2, symbol: bool = True) -> str:
    """Format a number as an Indian-grouped rupee string, e.g. ₹1,23,456.00.

    Returns an empty string for None/NaN so the UI shows blank rather than '₹nan'.
    """
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if math.isnan(number):
        return ""

    sign = "-" if number < 0 else ""
    number = abs(number)
    whole = int(number)
    frac = number - whole

    whole_str = _group_indian(whole)
    if decimals > 0:
        frac_str = f"{frac:.{decimals}f}"[2:]  # strip leading "0."
        body = f"{whole_str}.{frac_str}"
    else:
        body = whole_str

    prefix = "₹" if symbol else ""
    return f"{sign}{prefix}{body}"


def _group_indian(whole: int) -> str:
    """Group an integer using the Indian system: last 3 digits, then pairs."""
    s = str(whole)
    if len(s) <= 3:
        return s
    last3 = s[-3:]
    rest = s[:-3]
    # Insert a comma every 2 digits in the remaining part, from the right.
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    parts.insert(0, rest)
    return ",".join(parts) + "," + last3

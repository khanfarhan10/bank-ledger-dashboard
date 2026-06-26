"""Detect self-transfers: money moving between the account holder's OWN
accounts / instruments (HDFC <-> ICICI <-> PNB <-> SBI, FD moves, own UPI
handle loads, own credit-card bill payments).

Self-transfers are real ledger lines but they are NOT income or expense — the
same rupee is counted once as a debit in one statement and once as a credit in
another. Flagging them lets the dashboard exclude them from headline totals so
the numbers reflect actual money in/out, not internal shuffling.

Detection is config-driven (config/self_identity.yml) and transparent: it keys
off the account holder's own phone number, own UPI handles, own account
numbers, and explicit FD / credit-card narration markers. The account holder's
*name alone* is intentionally NOT a signal (employer credits carry it too).
"""

from __future__ import annotations

import re

from src.utils.config_loader import load_self_identity


class SelfTransferDetector:
    """Pre-compiles self-identity signals and tests narrations against them."""

    def __init__(self, identity: dict | None = None):
        identity = identity or load_self_identity()
        self.account_holder = identity.get("account_holder", "")

        # Literal fragments that, if present, mark the counterparty as "me".
        literals: list[str] = []
        literals += identity.get("own_phone_numbers", [])
        literals += identity.get("own_upi_handles", [])
        literals += identity.get("own_account_numbers", [])
        literals += identity.get("own_account_prefixes", [])
        self._literals = [s.lower() for s in literals if s]

        # Regex narration markers (FD/CC/cheque-clearing).
        patterns = identity.get("self_transfer_patterns", [])
        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns if p]

    def is_self_transfer(self, description: str) -> tuple[bool, str]:
        """Return (is_self, reason). reason is '' when not a self-transfer."""
        if not description:
            return False, ""
        text = str(description).lower()

        for lit in self._literals:
            if lit in text:
                return True, f"Counterparty is the account holder's own identifier ({lit})."

        for rx in self._patterns:
            if rx.search(text):
                return True, f"Self-transfer marker matched (/{rx.pattern}/)."

        return False, ""

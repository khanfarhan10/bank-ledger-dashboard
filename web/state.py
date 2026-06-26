"""In-process application state for the web server.

Unlike Streamlit's re-run model, FastAPI is a long-lived process, so we can
hold the DecisionStore and a cached pipeline result in module globals and
invalidate them precisely:

    * extraction (steps 1-3) is expensive  -> cached until "re-read files"
    * ledger (steps 4-5) overlays manual decisions -> cached until any edit

Every write endpoint calls ``invalidate_decisions()`` so the next read rebuilds
the ledger; ``refresh()`` additionally re-reads the source statements.
"""

from __future__ import annotations

import threading

import pandas as pd

from src.services.decision_store import DecisionStore
from src.services.pipeline import (
    THRESHOLD_SETTING_KEY,
    effective_aliases,
    effective_categories,
    effective_threshold,
    extract_normalize_classify,
    finalize_ledger,
)
from src.utils.config_loader import load_review_statuses

SOURCE_DIR = "all_bank_statements"

_DEFAULT_REVIEW_STATUSES = [
    "unreviewed", "confirmed_related", "probably_related",
    "not_related", "unknown", "review_later", "do_not_remember",
]


class AppState:
    """Holds the store and caches the pipeline output for the server."""

    def __init__(self) -> None:
        self.store = DecisionStore()
        self._extraction: dict | None = None
        self._ledger: pd.DataFrame | None = None
        # Reentrant: ledger() acquires the lock and then calls extraction(),
        # which acquires it again on the same thread.
        self._lock = threading.RLock()

    # -- config passthroughs --------------------------------------------------

    @property
    def threshold(self) -> float:
        return effective_threshold(self.store)

    @property
    def categories(self) -> list[str]:
        return effective_categories(self.store)

    @property
    def aliases(self) -> dict:
        return effective_aliases(self.store)

    @property
    def review_statuses(self) -> list[str]:
        return load_review_statuses() or _DEFAULT_REVIEW_STATUSES

    # -- cached pipeline ------------------------------------------------------

    def extraction(self) -> dict:
        with self._lock:
            if self._extraction is None:
                self._extraction = extract_normalize_classify(
                    SOURCE_DIR, self.aliases, self.threshold
                )
            return self._extraction

    def ledger(self) -> pd.DataFrame:
        with self._lock:
            if self._ledger is None:
                ext = self.extraction()
                self._ledger = finalize_ledger(ext["classified"], self.store, self.threshold)
            return self._ledger

    # -- invalidation ---------------------------------------------------------

    def invalidate_decisions(self) -> None:
        """Drop the ledger cache so the next read re-applies manual decisions."""
        with self._lock:
            self._ledger = None

    def refresh(self) -> None:
        """Re-read the source statements from scratch."""
        with self._lock:
            self._extraction = None
            self._ledger = None

    def set_threshold(self, value: float) -> None:
        self.store.set_setting(THRESHOLD_SETTING_KEY, value)
        self.invalidate_decisions()


# Single shared instance for the process.
STATE = AppState()

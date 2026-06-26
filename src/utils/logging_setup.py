"""Central logging configuration.

Logs go to both the console and a rotating-ish daily file under data/logs/.
We log which files were read and any parser errors, per the read-only safety
requirements. Nothing here writes anywhere near all_bank_statements/.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: Path | str = "data/logs", level: int = logging.INFO) -> logging.Logger:
    """Configure and return the application logger (idempotent)."""
    global _CONFIGURED
    logger = logging.getLogger("bank_ledger")

    if _CONFIGURED:
        return logger

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"app-{date.today().isoformat()}.log"

    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    logger.propagate = False
    _CONFIGURED = True
    logger.info("Logging initialised -> %s", log_file)
    return logger


def get_logger() -> logging.Logger:
    """Return the app logger, configuring it with defaults if needed."""
    return setup_logging()

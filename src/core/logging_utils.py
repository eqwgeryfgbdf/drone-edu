"""Logging helpers: console + CSV flight event log."""

from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_CSV_LOCK = threading.Lock()
_LOGGER: Optional[logging.Logger] = None


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> logging.Logger:
    """Configure root app logger once."""
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("codrone_gesture")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _LOGGER = logger
    return logger


def get_logger() -> logging.Logger:
    """Return the shared logger, initializing with defaults if needed."""
    if _LOGGER is None:
        return setup_logging()
    return _LOGGER


def append_csv_event(
    csv_path: Path,
    *,
    level: str,
    source: str,
    message: str,
    extra: Optional[dict[str, object]] = None,
) -> None:
    """Append one event row to the flight CSV log (thread-safe)."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "source": source,
        "message": message,
    }
    if extra:
        for key, value in extra.items():
            row[str(key)] = value

    fieldnames = list(row.keys())
    with _CSV_LOCK:
        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

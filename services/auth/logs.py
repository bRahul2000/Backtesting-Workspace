"""Bounded production logs (rotating files). Callers never pass passwords, hashes, tokens or secrets; the filter below
also masks anything shaped like them, as a second line of defence."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re

_SECRETISH = re.compile(r"\$argon2id?\$[^\s\"']+|\b[0-9a-f]{64,}\b|\b[A-Za-z0-9_\-]{40,}\b")


class _Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRETISH.sub("[redacted]", str(record.getMessage()))
        record.args = ()
        return True


def setup(name: str, log_dir: Path | str | None = None, *, max_bytes: int = 5_000_000, backups: int = 5) -> logging.Logger:
    """A logger writing to <log_dir>/<name>.log (5 MB x 5 files); console only when no log dir is configured."""
    logger = logging.getLogger(f"zoneflow.{name}")
    directory = str(log_dir or os.environ.get("ZONEFLOW_LOG_DIR") or "")
    if getattr(logger, "_zoneflow_dir", None) == directory:
        return logger
    for old in list(logger.handlers):                        # (re)configure for this directory
        logger.removeHandler(old)
        old.close()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(Path(directory) / f"{name}.log", maxBytes=max_bytes,
                                                       backupCount=backups, encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(_Redact())
    logger.addHandler(handler)
    logger._zoneflow_dir = directory
    return logger

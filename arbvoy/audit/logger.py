from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "event_type": getattr(record, "event_type", record.levelname),
            "message": record.getMessage(),
        }
        payload.update(
            {
                k: v
                for k, v in record.__dict__.items()
                if k not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__
                and k not in {"event_type"}
                and not k.startswith("_")
            }
        )
        return json.dumps(payload, default=str)


class _HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        extras = []
        for key, value in record.__dict__.items():
            if key in {"msg", "args", "levelname", "levelno", "name", "pathname", "filename", "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs", "relativeCreated", "thread", "threadName", "processName", "process", "message"}:
                continue
            if key.startswith("_"):
                continue
            if key == "event_type":
                continue
            extras.append(f"{key}={value}")
        tail = " ".join(extras)
        message = record.getMessage()
        return f"{ts} [{record.levelname}] [{record.name}] {message}" + (f" {tail}" if tail else "")


def configure_logging(log_file_path: str, level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    Path(log_file_path).parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_HumanFormatter())
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(_JsonFormatter())

    root.addHandler(console)
    root.addHandler(file_handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, event_type: str, message: str, **context: Any) -> None:
    logger.log(level, message, extra={"event_type": event_type, **context})


audit_log = get_logger("arbvoy")


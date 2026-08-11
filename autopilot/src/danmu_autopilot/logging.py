"""JSON logging helpers that recursively redact credentials and token paths."""

from __future__ import annotations

import json
import logging as std_logging
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any


_SECRET_KEY = re.compile(
    r"(?:token|cookie|authorization|password|secret|api[_-]?key|control[_-]?key)",
    re.IGNORECASE,
)
_TOKEN_PATH = re.compile(r"(?<=/)(?:token|key|secret)[-_][^/?#]+", re.IGNORECASE)


def _redact_string(value: str) -> str:
    return _TOKEN_PATH.sub("[TOKEN]", value)


def redact(value: object, *, _key: str | None = None) -> object:
    """Return a recursively redacted copy suitable for logs or diagnostics.

    Mappings are copied, sequence values are converted to lists, and the
    original object is never mutated.  Key names are matched case-insensitively
    so nested JSON from different upstream providers receives the same policy.
    """

    if _key is not None and _SECRET_KEY.search(_key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(key): redact(item, _key=str(key)) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


class RedactingJsonFormatter(std_logging.Formatter):
    """Compact JSON formatter with a stable set of non-sensitive fields."""

    def format(self, record: std_logging.LogRecord) -> str:
        message = record.msg if isinstance(record.msg, Mapping) else {"message": record.getMessage()}
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            **dict(message),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: int = std_logging.INFO) -> None:
    """Install one redacting stream handler for the application root logger."""

    root = std_logging.getLogger("danmu_autopilot")
    root.setLevel(level)
    if not any(isinstance(handler, std_logging.StreamHandler) for handler in root.handlers):
        handler = std_logging.StreamHandler()
        handler.setFormatter(RedactingJsonFormatter())
        root.addHandler(handler)


__all__ = ["RedactingJsonFormatter", "configure_logging", "redact"]


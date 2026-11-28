import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    _EXTRA_FIELDS = (
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "tenant_id",
        "job",
        "trace_id",
        "outcome",
        "error_type",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=True, default=str)


def configure_logging(name: str = "app.access") -> None:
    """Install a single JSON handler for the named logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

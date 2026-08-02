import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

URL_BEARING_DEPENDENCY_LOGGERS = (
    "httpcore",
    "httpx",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        if hasattr(record, "extra_data"):
            payload.update(getattr(record, "extra_data"))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in URL_BEARING_DEPENDENCY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def log_extra(logger: logging.Logger, level: int, message: str, **kwargs: Any) -> None:
    logger.log(level, message, extra={"extra_data": kwargs})

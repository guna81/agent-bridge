import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
             "logger": record.name, "msg": record.getMessage()}  # fmt: skip
        d.update(getattr(record, "fields", {}))
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d, default=str)


def setup_logging() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger("proxy")
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)
    root.propagate = False


def log(event: str, **fields) -> None:  # noqa: ANN003
    logging.getLogger("proxy").info(event, extra={"fields": fields})

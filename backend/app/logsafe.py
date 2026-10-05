"""Keep keys and tokens out of the logs.

The HTTP client libraries log full request URLs at INFO level; those are turned
down to warnings. As a second line of defence, every log record is scrubbed of
anything that looks like an API key, bearer token or password in a URL.
"""

import logging
import re

_PATTERNS = [
    (re.compile(r"(?i)(apikey|api_key|token|access_token|password|secret)=([^&\s\"']+)"), r"\1=[hidden]"),
    (re.compile(r"(?i)(bearer|apikey)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [hidden]"),
    (re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+@"), r"\1[hidden]@"),
    (re.compile(r"/bot\d+:[A-Za-z0-9_-]{20,}"), "/bot[hidden]"),  # Telegram puts the bot token in the address
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


_installed = False


def install_log_redaction() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    flt = RedactingFilter()
    # Filters on handlers see records from every logger that reaches them.
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.addFilter(flt)
        for handler in logger.handlers:
            handler.addFilter(flt)

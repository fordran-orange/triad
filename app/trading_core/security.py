"""Secret-safe serialization at every provider/storage boundary."""

import json
import os
import re

from dotenv import dotenv_values

from trading_core.settings import ROOT


def secrets():
    from trading_core.providers.secrets import redaction_values

    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    return list(redaction_values()) + [
        v
        for k, v in values.items()
        if v
        and len(v) >= 8
        and any(s in k.upper() for s in ("API_KEY", "PASSWORD", "TOKEN", "PRODUCT_KEY"))
    ]


def redact(value):
    text = json.dumps(value, default=str)
    for secret in secrets():
        text = text.replace(json.dumps(secret)[1:-1], "[REDACTED]")
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"(?:sk-[A-Za-z0-9_-]{12,}|xai-[A-Za-z0-9_-]{12,}|Bearer [A-Za-z0-9_.-]{12,})",
        "[REDACTED]",
        text,
    )
    return json.loads(text)


def ensure_no_secret(value):
    original = json.dumps(value, default=str)
    if json.dumps(redact(value), default=str) != original:
        raise PermissionError("Secret material rejected at runtime boundary")

"""Credential loading and redaction. Values are never printed, logged or persisted."""

import hashlib
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_ENV = ROOT / ".env.local"


def _private_text(path):
    path = Path(path)
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise PermissionError(f"{path} 权限过宽：凭证文件只能由所有者读写（chmod 600）")
    return path.read_text()


def dotenv(path=LOCAL_ENV):
    """Parse KEY=VALUE lines from a private file; missing file means no values."""
    path = Path(path)
    if not path.exists():
        return {}
    values = {}
    for line in _private_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load(env_name, credential_name=None):
    """Return a secret, or "" when unset.

    Order: systemd credential ($CREDENTIALS_DIRECTORY/<credential_name>),
    a private file named by <ENV_NAME>_FILE, the environment variable, and
    finally this project's .env.local (development only).
    """
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if directory and credential_name:
        path = Path(directory) / credential_name
        if path.is_file():
            # systemd owns this directory and its permissions.
            return path.read_text().strip()
    named = os.environ.get(env_name + "_FILE")
    if named:
        return _private_text(named).strip()
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    return dotenv().get(env_name, "")


def setting(name, default=""):
    """Non-secret setting from the environment or .env.local."""
    return os.environ.get(name) or dotenv().get(name, default)


PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)\b((?:api[_-]?key|token|secret|password)=)[^&\s\"']+"),
        r"\1[REDACTED]",
    ),
]


def redact(text, secrets=()):
    text = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def fingerprint(value):
    """Short, non-reversible identifier for status output."""
    return hashlib.sha256(value.encode()).hexdigest()[:8] if value else None

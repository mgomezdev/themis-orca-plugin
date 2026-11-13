"""Connection settings; the host owns configuration persistence."""

import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit


def api_base_url(value: str) -> str:
    """Accept a deployment root or its /api/v1 URL, including proxy prefixes."""
    if not isinstance(value, str) or any(ord(c) < 32 or c.isspace() for c in value):
        raise ValueError("Enter a Themis HTTP or HTTPS URL without whitespace.")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError("Enter a valid Themis hostname and port.") from None
    if (url.scheme not in {"http", "https"} or not url.hostname
            or url.username is not None or url.password is not None
            or url.query or url.fragment or "\\" in value or port == 0):
        raise ValueError("Use a Themis HTTP or HTTPS URL without credentials, query, or fragment.")
    path = url.path.rstrip("/")
    if not path.endswith("/api/v1"):
        path += "/api/v1"
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


@dataclass(frozen=True)
class Settings:
    url: str
    api_key: str = field(repr=False)

    @classmethod
    def from_json(cls, raw: str) -> "Settings":
        try:
            config = json.loads(raw)
        except (TypeError, ValueError):
            raise ValueError("Restore the Themis configuration defaults and enter your settings.") from None
        if not isinstance(config, dict):
            raise ValueError("Themis configuration must be a JSON object.")
        key = config.get("api_key", "")
        if not isinstance(key, str) or not key.strip() or any(ord(c) < 32 or ord(c) > 126 for c in key):
            raise ValueError("Paste your Themis API key in Connection settings.")
        return cls(api_base_url(config.get("url", "")), key.strip())

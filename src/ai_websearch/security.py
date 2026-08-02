from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import quote, urlsplit


def safe_model_label(model: str | None) -> str | None:
    if model is None:
        return None
    path = Path(model).expanduser()
    return path.name if path.is_absolute() else model


def safe_url_label(url: str) -> str:
    """Return an origin plus an opaque identifier without path or query data."""

    digest = sha256(url.encode("utf-8", errors="replace")).hexdigest()[:12]
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or "unknown"
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        origin = f"{parsed.scheme}://{host}{port}" if parsed.scheme else host
    except ValueError:
        origin = "invalid-url"
    return f"{origin}#sha256:{digest}"


def markdown_citation(title: str, url: str) -> str:
    """Render one single-line Markdown link without destination breakout."""

    label = " ".join((title or "Source").split())
    label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    destination = quote(
        url,
        safe=":/?&=#%+;,@!$'*~-._",
    )
    return f"[{label}]({destination})"

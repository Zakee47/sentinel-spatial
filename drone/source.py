from urllib.parse import urlsplit, urlunsplit


def safe_source(source: str) -> str:
    try:
        parsed = urlsplit(source)
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return source
    if not parsed.netloc:
        return source
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if port is not None:
        netloc += f":{port}"
    path = parsed.path
    if parsed.scheme.lower() in {"rtmp", "rtmps"}:
        parent, separator, tail = path.rstrip("/").rpartition("/")
        if tail:
            path = f"{parent}{separator}[REDACTED]"
    return urlunsplit((parsed.scheme, netloc, path, "", ""))

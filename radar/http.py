"""Minimal HTTP helpers (stdlib only) that raise one typed error.

Sources let FetchError propagate so `radar sync` can tell a failed fetch (keep stored jobs)
from a company that really has no openings (deactivate them).
"""

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

DEFAULT_UA = "JobRadar/2.0"


class FetchError(Exception):
    """A request failed or returned something unusable. `status` is the HTTP code, if any."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def http_get_text(
    url: str,
    *,
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 20,
    context: Optional[ssl.SSLContext] = None,
    retry_429: bool = False,
    opener: Optional[urllib.request.OpenerDirector] = None,
) -> str:
    """GET (POST when `data` is given) and return the decoded body; raise FetchError on any failure.

    `opener` lets a source keep cookies between requests (urllib.request.build_opener(...)).
    """
    req = urllib.request.Request(url, data=data, headers={"User-Agent": DEFAULT_UA, **(headers or {})})
    for attempt in range(2 if retry_429 else 1):
        try:
            if opener is not None:
                ctx = opener.open(req, timeout=timeout)
            else:
                ctx = urllib.request.urlopen(req, timeout=timeout, context=context)
            with ctx as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0 and retry_429:
                time.sleep(1.5)
                continue
            raise FetchError(f"{url}: HTTP {e.code}", status=e.code) from e
        except (urllib.error.URLError, OSError, ValueError) as e:  # timeouts, DNS, TLS, bad URL
            raise FetchError(f"{url}: {e}") from e
    raise AssertionError("unreachable")


def http_get_json(url: str, *, json_body: Any = None, **kwargs) -> Any:
    """Like http_get_text but parses JSON; `json_body` sends a JSON POST."""
    headers = dict(kwargs.pop("headers", None) or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    text = http_get_text(url, data=data, headers=headers, **kwargs)
    try:
        return json.loads(text)
    except ValueError as e:
        raise FetchError(f"{url}: invalid JSON: {e}") from e

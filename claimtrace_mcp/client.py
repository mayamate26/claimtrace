"""HTTP client for the hosted ClaimTrace API.

Endpoints:

- ``POST /api/check``: JSON ``{document, sources: [{kind: "text"|"url", value}], share}``, or a
  multipart form with the same fields (``sources`` as a JSON string) plus PDF file uploads.
  Optional ``Authorization: Bearer <key>``.
- ``GET /r/{id}.json``: a shared report.
- ``GET /badge/{id}.svg``: a shared report's badge.

Errors come back as ``{"error": "<message>"}`` with a status code; ``check`` raises
``AuthError`` (401), ``RateLimitError`` (429), ``UnavailableError`` (503) or ``APIError``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Union

import httpx

DEFAULT_API_BASE = "https://claimtrace-api.fly.dev"
USER_AGENT = "claimtrace-python/0.1.2"

Source = Union[str, dict]
Pdf = Union[str, os.PathLike, tuple]


class ClaimTraceError(Exception):
    """Base error. ``status`` is the HTTP status (0 for network failures)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status

    def __str__(self) -> str:
        return f"{self.message} (HTTP {self.status})" if self.status else self.message


class AuthError(ClaimTraceError):
    """401: the API key was not recognised."""


class RateLimitError(ClaimTraceError):
    """429: the daily claim allowance is used up."""


class UnavailableError(ClaimTraceError):
    """503: the free tier is paused for today, or the service is down."""


class APIError(ClaimTraceError):
    """Any other non-2xx answer (bad input, server error) or a network failure."""


_BY_STATUS = {401: AuthError, 429: RateLimitError, 503: UnavailableError}


def is_url(value: str) -> bool:
    v = value.strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def source_spec(source: Source) -> dict:
    """``{"kind", "value"}`` for a source. A string is a URL if it starts with http(s)://, else text."""
    if isinstance(source, dict):
        kind = str(source.get("kind", "")).lower()
        if kind not in ("text", "url"):
            raise ValueError("a source dict needs kind 'text' or 'url'")
        return {"kind": kind, "value": str(source.get("value", ""))}
    if not isinstance(source, str):
        raise TypeError(f"a source must be a string or a dict, not {type(source).__name__}")
    return {"kind": "url" if is_url(source) else "text", "value": source.strip() if is_url(source) else source}


def resolve_api_base(api_base: str | None = None) -> str:
    return (api_base or os.environ.get("CLAIMTRACE_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def resolve_api_key(api_key: str | None = None) -> str | None:
    key = api_key if api_key is not None else os.environ.get("CLAIMTRACE_API_KEY")
    return key.strip() if key and key.strip() else None


def _headers(api_key: str | None) -> dict:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _pdf_part(pdf: Pdf) -> tuple[str, bytes]:
    if isinstance(pdf, tuple):
        name, data = pdf
        return str(name), bytes(data)
    p = Path(pdf)
    return p.name, p.read_bytes()


def _raise_for(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
        message = body.get("error") if isinstance(body, dict) else None
    except ValueError:
        message = None
    message = str(message or resp.text[:300] or resp.reason_phrase or "request failed")
    raise _BY_STATUS.get(resp.status_code, APIError)(message, resp.status_code)


def _client(timeout: float, transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)


def check(document: str, sources: Iterable[Source], share: bool = False, pdfs: Iterable[Pdf] | None = None,
          api_base: str | None = None, api_key: str | None = None, timeout: float = 180,
          transport: httpx.BaseTransport | None = None) -> dict:
    """Check every number in ``document`` against ``sources`` (URLs, pasted text or ``{kind, value}``
    dicts) and optional ``pdfs`` (paths or ``(filename, bytes)``). Returns the API's ledger dict:
    ``claims``, ``summary``, ``notices``, ``limits_remaining`` and, when ``share``, ``share_url`` /
    ``badge_url`` / ``json_url``."""
    specs = [source_spec(s) for s in (sources or [])]
    parts = [_pdf_part(p) for p in (pdfs or [])]
    url = resolve_api_base(api_base) + "/api/check"
    headers = _headers(resolve_api_key(api_key))
    try:
        with _client(timeout, transport) as http:
            if parts:
                data = {"document": document, "sources": json.dumps(specs), "share": "true" if share else "false"}
                files = [("pdf", (name, blob, "application/pdf")) for name, blob in parts]
                resp = http.post(url, data=data, files=files, headers=headers)
            else:
                resp = http.post(url, json={"document": document, "sources": specs, "share": bool(share)},
                                 headers=headers)
    except httpx.HTTPError as exc:
        raise APIError(f"could not reach {url}: {exc}") from exc
    _raise_for(resp)
    try:
        return resp.json()
    except ValueError as exc:
        raise APIError("the API answered with something that is not JSON", resp.status_code) from exc


def _get(path: str, api_base: str | None, timeout: float, transport) -> httpx.Response:
    url = resolve_api_base(api_base) + path
    try:
        with _client(timeout, transport) as http:
            resp = http.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        raise APIError(f"could not reach {url}: {exc}") from exc
    _raise_for(resp)
    return resp


def get_report(report_id: str, api_base: str | None = None, timeout: float = 30,
               transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """A shared report as JSON (shared reports are deleted after 30 days)."""
    return _get(f"/r/{report_id}.json", api_base, timeout, transport).json()


def get_badge(report_id: str, api_base: str | None = None, timeout: float = 30,
              transport: httpx.BaseTransport | None = None) -> str:
    """A shared report's SVG badge."""
    return _get(f"/badge/{report_id}.svg", api_base, timeout, transport).text

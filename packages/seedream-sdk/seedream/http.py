"""Low-level HTTP helpers: requests, retry, and response parsing.

Intentionally uses stdlib urllib only — zero extra dependencies.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any
from urllib import error, request

from .config import MAX_RETRIES, SUBMIT_TIMEOUT
from .exceptions import APIError

logger = logging.getLogger("seedream")


def _do_request(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = SUBMIT_TIMEOUT,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload else None
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            parsed: dict[str, Any] = json.loads(resp.read().decode())
            return parsed
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")
        raise APIError(f"HTTP {exc.code}: {detail}", status_code=exc.code) from exc
    except error.URLError as exc:
        raise APIError(f"Network error: {exc.reason}") from exc


def request_with_retry(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = SUBMIT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    correlation_id: str = "",
) -> dict[str, Any]:
    tag = f"[{correlation_id}] " if correlation_id else ""
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            return _do_request(url, method=method, headers=headers, payload=payload, timeout=timeout)
        except APIError as exc:
            last_exc = exc
            # 4xx errors are not retryable (bad request, auth failure, etc.)
            if exc.status_code is not None and 400 <= exc.status_code < 500:
                raise
            if method.upper() == "POST":
                raise APIError(
                    f"Submission outcome may be unknown; automatic resubmission is disabled. "
                    f"Inspect the provider outcome before retrying. Original error: {exc}",
                    status_code=exc.status_code,
                ) from exc
            wait = (2 ** attempt) + random.random()
            logger.warning(
                "%sRetrying in %.1fs (attempt %d/%d): %s",
                tag, wait, attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                time.sleep(wait)

    raise APIError(
        f"Request failed after {max_retries} attempts: {last_exc}"
    ) from last_exc


# Fields a layer_decomposition response carries per entry, on top of the usual
# url/size. z_index orders the stack (0 is the flattened base image); name and
# description identify what was cut out; bounding_box locates it in the source.
_LAYER_FIELDS = ("output_format", "z_index", "name", "description", "bounding_box")


def extract_images(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize the /images/generations response `data` array.

    Each item is returned as {url?, b64_json?, size?} plus any layer metadata the
    API included. Order is preserved (matters for sequential image sets, and for
    layer stacks where the API returns layers out of z_index order).
    """
    data = resp.get("data") or []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        if item.get("url"):
            entry["url"] = item["url"]
        if item.get("b64_json"):
            entry["b64_json"] = item["b64_json"]
        if item.get("size"):
            entry["size"] = item["size"]
        for field in _LAYER_FIELDS:
            # z_index 0 is the base image, so test presence rather than truthiness.
            if item.get(field) is not None:
                entry[field] = item[field]
        if entry:
            out.append(entry)
    return out

"""Low-level HTTP helpers: requests, retry, and response parsing.

Intentionally uses stdlib urllib only — zero extra dependencies.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any
from urllib import error, request

from .config import MAX_RETRIES, POLL_TIMEOUT
from .exceptions import APIError, SubmitTimeoutError, TaskTypeConstraintError

logger = logging.getLogger("seedance")

TASK_TYPE_CONSTRAINT_CODE = "InvalidParameter.TaskTypeConstraint"

# "Issues: [0] first detail. [1] second detail." -> ["first detail.", ...]
_ISSUE_RE = re.compile(r"\[\d+\]\s*([^\[]+)")
# The message ends with a trailing correlation id that is not part of the last issue.
_REQUEST_ID_RE = re.compile(r"\s*Request id:.*$", re.IGNORECASE | re.DOTALL)


def error_payload(detail: str) -> dict[str, Any]:
    """Parse an API error body into a dict, tolerating non-JSON responses."""
    try:
        parsed = json.loads(detail)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    err = parsed.get("error")
    return err if isinstance(err, dict) else parsed


def parse_issues(message: str) -> list[str]:
    """Extract the per-violation 'Issues: [0] ... [1] ...' lines from a message."""
    _, _, tail = message.partition("Issues:")
    if not tail:
        return []
    tail = _REQUEST_ID_RE.sub("", tail)
    return [m.strip() for m in _ISSUE_RE.findall(tail) if m.strip()]


def error_for_body(detail: str, status_code: int) -> APIError:
    """Build the most specific exception the error body supports."""
    body = error_payload(detail)
    code = str(body.get("code") or "")
    message = str(body.get("message") or "") or detail
    if code == TASK_TYPE_CONSTRAINT_CODE:
        return TaskTypeConstraintError(
            f"HTTP {status_code}: {message}",
            status_code=status_code,
            issues=parse_issues(message),
        )
    return APIError(f"HTTP {status_code}: {detail}", status_code=status_code)


def _do_request(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = POLL_TIMEOUT,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload else None
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode())
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")
        raise error_for_body(detail, exc.code) from exc
    except TimeoutError as exc:
        # urlopen raises a bare TimeoutError on socket timeout — it is NOT a
        # URLError, so it would otherwise escape as a non-SeedanceError and
        # bypass every caller's error handling.
        if method == "POST":
            raise SubmitTimeoutError(
                f"Timed out after {timeout}s waiting for a response from {url}. "
                "The request was most likely accepted, so a task may have been "
                "created and billed even though no task_id came back — check "
                "`seedance list` / seedance_list_tasks before resubmitting, or you "
                "will pay for the job twice. Requests carrying several reference "
                "videos are the usual cause; raise SEEDANCE_SUBMIT_TIMEOUT if this "
                "recurs."
            ) from exc
        raise APIError(f"Timed out after {timeout}s waiting for {url}.") from exc
    except error.URLError as exc:
        raise APIError(f"Network error: {exc.reason}") from exc
    except ValueError as exc:
        raise APIError(f"Malformed JSON in response from {url}: {exc}") from exc

    # A proxy or error page can return valid JSON that is not an object; catching
    # it here beats an AttributeError surfacing far from the cause.
    if not isinstance(parsed, dict):
        raise APIError(
            f"Expected a JSON object from {url}, got {type(parsed).__name__}."
        )
    return parsed


def request_with_retry(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = POLL_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    correlation_id: str = "",
) -> dict[str, Any]:
    tag = f"[{correlation_id}] " if correlation_id else ""
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            return _do_request(url, method=method, headers=headers, payload=payload, timeout=timeout)
        except SubmitTimeoutError:
            # Task creation is not idempotent. The server most likely accepted
            # the request, so retrying would create — and bill — a second task.
            raise
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


def extract_nested(data: dict[str, Any], *keys: str) -> str:
    """Safely extract a string from a nested dict without raising."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return "" if current is None else str(current)


# Response envelopes vary across API versions; probe each in order.
_OUTPUT_CONTAINERS = ("content", "result", "output")


def extract_output_field(task: dict[str, Any], field: str) -> Any:
    """Pull a field out of whichever output container the response uses.

    Falls back to the top level, where Seedance echoes request parameters such
    as ratio and duration on some responses.
    """
    for container in _OUTPUT_CONTAINERS:
        block = task.get(container)
        if isinstance(block, dict):
            value = block.get(field)
            if value not in (None, ""):
                return value
    value = task.get(field)
    return None if value in (None, "") else value


def extract_video_url(task: dict[str, Any]) -> str | None:
    url = extract_output_field(task, "video_url")
    return str(url) if url else None

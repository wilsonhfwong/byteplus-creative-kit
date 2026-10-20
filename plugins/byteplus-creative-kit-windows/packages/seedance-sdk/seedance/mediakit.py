"""BytePlus AI MediaKit client — video enhancement / upscaling.

A simple Bearer-token JSON API on a dedicated host (distinct from both the
ModelArk generation API and the AK/SK-signed asset library). Submitting an
enhancement task is asynchronous: POST returns a task_id, then you poll
GET /tasks/{task_id} until status is terminal (completed | failed).

Idempotency is handled two ways, layered for defence in depth:
  1. A deterministic ``client_token`` derived from the request parameters is sent
     to the server, which dedups identical requests for 24h (same token → same task).
  2. A small local cache (token → task_id) short-circuits duplicate submissions
     before any network call. ``force_new`` bypasses both.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import string
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .config import (
    MAX_RETRIES,
    MEDIAKIT_BASE_URL,
    MEDIAKIT_BITRATE_LEVELS,
    MEDIAKIT_CACHE_PATH,
    MEDIAKIT_CACHE_TTL,
    MEDIAKIT_CLIENT_TOKEN_MAXLEN,
    MEDIAKIT_FPS_RANGE,
    MEDIAKIT_RESOLUTION_LIMIT_RANGE,
    MEDIAKIT_RESOLUTIONS,
    MEDIAKIT_SCENES,
    MEDIAKIT_TOOL_VERSIONS,
    POLL_TIMEOUT,
    SUBMIT_TIMEOUT,
)
from .exceptions import ValidationError
from .http import request_with_retry

logger = logging.getLogger("seedance")

_PRINTABLE_ASCII = set(string.printable) - set("\t\n\r\x0b\x0c")


# ---------------------------------------------------------------------------
# Idempotency: deterministic token + local cache
# ---------------------------------------------------------------------------

def make_client_token(core_params: dict[str, Any]) -> str:
    """Deterministic idempotency token from normalized core request params.

    Same inputs → same token (order-independent), so retries dedup on both the
    server and the local cache. Always ≤64 printable ASCII chars.
    """
    normalized = {k: v for k, v in sorted(core_params.items()) if v is not None}
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"amk-{digest[:40]}"


class TaskCache:
    """Best-effort local cache mapping idempotency token → task_id.

    Never fatal: a missing, corrupt, or unwritable cache simply degrades to "no
    cache" — the server's own idempotency still prevents duplicate tasks.
    """

    def __init__(self, path: Path | None = None, ttl: int | None = None) -> None:
        self._path = path if path is not None else MEDIAKIT_CACHE_PATH
        self._ttl = ttl if ttl is not None else MEDIAKIT_CACHE_TTL

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            with self._path.open() as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, token: str) -> str | None:
        entry = self._load().get(token)
        if not entry:
            return None
        if time.time() - entry.get("created_at", 0) >= self._ttl:
            return None
        return entry.get("task_id") or None

    def put(self, token: str, task_id: str) -> None:
        if not token or not task_id:
            return
        data = self._load()
        now = time.time()
        # Prune expired entries while we hold the (re)written file.
        data = {
            k: v for k, v in data.items()
            if now - v.get("created_at", 0) < self._ttl
        }
        data[token] = {"task_id": task_id, "created_at": now}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: temp file in the same dir + os.replace.
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("Upscale cache write failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# MediaKit client
# ---------------------------------------------------------------------------

class MediaKitClient:
    def __init__(self, api_key: str, *, cache: TaskCache | None = None) -> None:
        self._api_key = api_key
        self._cache = cache if cache is not None else TaskCache()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _validate(
        video_url: str,
        tool_version: str,
        scene: str | None,
        resolution: str | None,
        resolution_limit: int | None,
        bitrate_level: str | None,
        fps: float | None,
        client_token: str | None,
    ) -> None:
        if not video_url:
            raise ValidationError("video_url is required.")
        if tool_version not in MEDIAKIT_TOOL_VERSIONS:
            raise ValidationError(
                f"Invalid tool_version {tool_version!r}. "
                f"Must be one of: {', '.join(sorted(MEDIAKIT_TOOL_VERSIONS))}"
            )
        if resolution is not None and resolution_limit is not None:
            raise ValidationError(
                "resolution and resolution_limit are mutually exclusive — set only one."
            )
        if resolution is not None and resolution not in MEDIAKIT_RESOLUTIONS:
            raise ValidationError(
                f"Invalid resolution {resolution!r}. "
                f"Must be one of: {', '.join(sorted(MEDIAKIT_RESOLUTIONS))}"
            )
        if resolution_limit is not None:
            lo, hi = MEDIAKIT_RESOLUTION_LIMIT_RANGE
            if not lo <= resolution_limit <= hi:
                raise ValidationError(
                    f"Invalid resolution_limit {resolution_limit}. Must be in [{lo}, {hi}]."
                )
        if bitrate_level is not None and bitrate_level not in MEDIAKIT_BITRATE_LEVELS:
            raise ValidationError(
                f"Invalid bitrate_level {bitrate_level!r}. "
                f"Must be one of: {', '.join(sorted(MEDIAKIT_BITRATE_LEVELS))}"
            )
        if fps is not None:
            lo, hi = MEDIAKIT_FPS_RANGE
            if not lo <= fps <= hi:
                raise ValidationError(f"Invalid fps {fps}. Must be in [{lo}, {hi}].")
        if scene is not None:
            if tool_version != "standard":
                raise ValidationError(
                    "scene only applies when tool_version='standard' "
                    "(professional uses its own algorithm set)."
                )
            if scene not in MEDIAKIT_SCENES:
                raise ValidationError(
                    f"Invalid scene {scene!r}. "
                    f"Must be one of: {', '.join(sorted(MEDIAKIT_SCENES))}"
                )
        if client_token is not None:
            if len(client_token) > MEDIAKIT_CLIENT_TOKEN_MAXLEN:
                raise ValidationError(
                    f"client_token must be ≤{MEDIAKIT_CLIENT_TOKEN_MAXLEN} characters."
                )
            if any(c not in _PRINTABLE_ASCII for c in client_token):
                raise ValidationError("client_token must be printable ASCII only.")

    def submit_enhance(
        self,
        video_url: str,
        *,
        tool_version: str = "standard",
        scene: str | None = None,
        resolution: str | None = None,
        resolution_limit: int | None = None,
        bitrate_level: str | None = None,
        fps: float | None = None,
        client_token: str | None = None,
        callback_args: str | None = None,
        force_new: bool = False,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        """Submit a video-enhancement task. Returns the parsed JSON response.

        Adds an ``idempotent_hit`` boolean to the returned dict when the result
        came from the local cache instead of a fresh API call.
        """
        self._validate(
            video_url, tool_version, scene, resolution, resolution_limit,
            bitrate_level, fps, client_token,
        )

        # Resolve the idempotency token: explicit > deterministic (+optional salt).
        if client_token:
            token = client_token
        else:
            core = {
                "video_url": video_url,
                "tool_version": tool_version,
                "scene": scene,
                "resolution": resolution,
                "resolution_limit": resolution_limit,
                "bitrate_level": bitrate_level,
                "fps": fps,
            }
            token = make_client_token(core)
            if force_new:
                token = f"{token[:40]}-{uuid.uuid4().hex[:16]}"

        # Local cache short-circuit (skipped on force_new).
        if not force_new:
            cached = self._cache.get(token)
            if cached:
                logger.info("[%s] Upscale idempotent hit (cache): %s", correlation_id, cached)
                return {"success": True, "task_id": cached, "idempotent_hit": True}

        payload: dict[str, Any] = {"video_url": video_url, "tool_version": tool_version}
        if scene is not None:
            payload["scene"] = scene
        if resolution is not None:
            payload["resolution"] = resolution
        if resolution_limit is not None:
            payload["resolution_limit"] = resolution_limit
        if bitrate_level is not None:
            payload["bitrate_level"] = bitrate_level
        if fps is not None:
            payload["fps"] = fps
        if callback_args is not None:
            payload["callback_args"] = callback_args
        payload["client_token"] = token

        logger.info(
            "[%s] Upscale submit | tool=%s res=%s limit=%s fps=%s",
            correlation_id, tool_version, resolution, resolution_limit, fps,
        )
        resp = request_with_retry(
            f"{MEDIAKIT_BASE_URL}/tools/enhance-video",
            method="POST",
            headers=self._headers(),
            payload=payload,
            timeout=SUBMIT_TIMEOUT,
            max_retries=MAX_RETRIES,
            correlation_id=correlation_id,
        )
        task_id = resp.get("task_id", "")
        if task_id:
            self._cache.put(token, task_id)
        resp.setdefault("idempotent_hit", False)
        return resp

    def get_task(self, task_id: str, *, correlation_id: str = "") -> dict[str, Any]:
        """Fetch task details by id."""
        if not task_id:
            raise ValidationError("task_id is required.")
        return request_with_retry(
            f"{MEDIAKIT_BASE_URL}/tasks/{task_id}",
            method="GET",
            headers=self._headers(),
            timeout=POLL_TIMEOUT,
            max_retries=MAX_RETRIES,
            correlation_id=correlation_id,
        )

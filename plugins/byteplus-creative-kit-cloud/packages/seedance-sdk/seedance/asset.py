"""BytePlus Asset Library client — HMAC-SHA256 signed requests."""
from __future__ import annotations

import datetime
import hashlib
import hmac as hmac_lib
import json
import logging
import os
import time
from typing import Any
from urllib import error, parse
from urllib import request as urllib_request

from .config import (
    ASSET_CONTENT_TYPE,
    ASSET_HOST,
    ASSET_POLL_INTERVAL,
    ASSET_POLL_TIMEOUT,
    ASSET_REGION,
    ASSET_SERVICE,
    ASSET_VERSION,
    MAX_RETRIES,
    POLL_TIMEOUT,
)
from .exceptions import APIError, AssetError, TimeoutError
from .http import extract_nested

logger = logging.getLogger("seedance")


# ---------------------------------------------------------------------------
# HMAC-SHA256 signing
# ---------------------------------------------------------------------------

def _hmac_sha256(key: bytes, content: str) -> bytes:
    return hmac_lib.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _norm_query(params: dict[str, Any]) -> str:
    parts = []
    for key in sorted(params.keys()):
        values = params[key] if isinstance(params[key], list) else [params[key]]
        for v in values:
            parts.append(
                parse.quote(key, safe="-_.~") + "=" + parse.quote(str(v), safe="-_.~")
            )
    return "&".join(parts)


def _sign_request(ak: str, sk: str, action: str, body_str: str) -> tuple[str, str, str, str]:
    """Return (x_date, content_sha256, canonical_query, authorization)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    content_sha256 = _sha256_hex(body_str)

    query_params = {"Action": action, "Version": ASSET_VERSION}
    canonical_query = _norm_query(query_params)

    canonical_headers = (
        f"content-type:{ASSET_CONTENT_TYPE}\n"
        f"host:{ASSET_HOST}\n"
        f"x-content-sha256:{content_sha256}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    token = os.getenv("ARK_SESSION_TOKEN", "")
    if token:
        canonical_headers += f"x-security-token:{token}\n"
        signed_headers += ";x-security-token"

    canonical_request = "\n".join([
        "POST", "/", canonical_query, canonical_headers, signed_headers, content_sha256,
    ])

    credential_scope = f"{short_date}/{ASSET_REGION}/{ASSET_SERVICE}/request"
    string_to_sign = "\n".join([
        "HMAC-SHA256", x_date, credential_scope, _sha256_hex(canonical_request),
    ])

    k_date    = _hmac_sha256(sk.encode(), short_date)
    k_region  = _hmac_sha256(k_date, ASSET_REGION)
    k_service = _hmac_sha256(k_region, ASSET_SERVICE)
    k_signing = _hmac_sha256(k_service, "request")
    signature = _hmac_sha256(k_signing, string_to_sign).hex()

    authorization = (
        f"HMAC-SHA256 Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    return x_date, content_sha256, canonical_query, authorization


# ---------------------------------------------------------------------------
# Asset API client
# ---------------------------------------------------------------------------

class AssetClient:
    def __init__(self, ak: str, sk: str) -> None:
        self._ak = ak
        self._sk = sk

    def _call(
        self,
        action: str,
        body: dict[str, Any],
        *,
        timeout: int = POLL_TIMEOUT,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        body = dict(body)
        body.setdefault("ProjectName", os.getenv("SEEDANCE_PROJECT_NAME", "default"))
        body_str = json.dumps(body)
        x_date, content_sha256, canonical_query, authorization = _sign_request(
            self._ak, self._sk, action, body_str
        )
        url = f"https://{ASSET_HOST}/?{canonical_query}"
        headers = {
            "Authorization": authorization,
            "Content-Type": ASSET_CONTENT_TYPE,
            "X-Content-Sha256": content_sha256,
            "X-Date": x_date,
            "Host": ASSET_HOST,
            "Accept": "application/json",
        }
        if os.getenv("ARK_SESSION_TOKEN"):
            headers["X-Security-Token"] = os.environ["ARK_SESSION_TOKEN"]
        req = urllib_request.Request(url, data=body_str.encode(), headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                parsed = json.loads(resp.read().decode())
        except error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")
            raise APIError(f"Asset API HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except error.URLError as exc:
            raise APIError(f"Asset API network error: {exc.reason}") from exc
        except ValueError as exc:
            raise APIError(f"Malformed JSON in Asset API response: {exc}") from exc

        if not isinstance(parsed, dict):
            raise APIError(
                f"Expected a JSON object from the Asset API, got {type(parsed).__name__}."
            )
        provider_error = (parsed.get("ResponseMetadata") or {}).get("Error")
        if provider_error:
            raise AssetError(f"{provider_error.get("Code", "AssetError")}: {provider_error.get("Message", "Asset operation failed")}")
        return parsed

    def _call_with_retry(
        self,
        action: str,
        body: dict[str, Any],
        *,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        tag = f"[{correlation_id}] " if correlation_id else ""
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return self._call(action, body, correlation_id=correlation_id)
            except APIError as exc:
                last_exc = exc
                if exc.status_code is not None and 400 <= exc.status_code < 500:
                    raise
                import random
                wait = (2 ** attempt) + random.random()
                logger.warning(
                    "%sAsset API retry in %.1fs (attempt %d/%d): %s",
                    tag, wait, attempt + 1, MAX_RETRIES, exc,
                )
                import time as _time
                if attempt < MAX_RETRIES - 1:
                    _time.sleep(wait)
        raise APIError(
            f"Asset API failed after {MAX_RETRIES} attempts: {last_exc}"
        ) from last_exc

    def create_group(self, name: str, description: str = "", *, correlation_id: str = "") -> str:
        """Create an asset group. Returns group_id."""
        resp = self._call(
            "CreateAssetGroup",
            {"Name": name, "Description": description, "GroupType": "AIGC"},
            correlation_id=correlation_id,
        )
        group_id = (
            extract_nested(resp, "Result", "Id")
            or extract_nested(resp, "Result", "GroupId")
            or extract_nested(resp, "Id")
            or extract_nested(resp, "GroupId")
        )
        if not group_id:
            raise AssetError(f"CreateAssetGroup did not return a group_id. Keys: {list(resp.keys())}")
        return group_id

    def create_asset(self, image_url: str, group_id: str, *, asset_type: str = "Image", name: str = "", correlation_id: str = "") -> str:
        """Upload an image URL to the asset library. Returns asset_id."""
        if asset_type not in {"Image", "Video"}:
            raise AssetError("asset_type must be Image or Video")
        payload = {"GroupId": group_id, "URL": image_url, "AssetType": asset_type}
        if name:
            payload["Name"] = name
        resp = self._call(
            "CreateAsset",
            payload,
            correlation_id=correlation_id,
        )
        asset_id = (
            extract_nested(resp, "Result", "Id")
            or extract_nested(resp, "Result", "AssetId")
            or extract_nested(resp, "Id")
            or extract_nested(resp, "AssetId")
        )
        if not asset_id:
            raise AssetError("CreateAsset did not return an asset_id.")
        return asset_id

    def get_asset_status(self, asset_id: str, *, correlation_id: str = "") -> tuple[str, dict[str, Any]]:
        """Return (status, raw_response) for an asset."""
        resp = self._call_with_retry(
            "GetAsset", {"Id": asset_id}, correlation_id=correlation_id
        )
        status = (
            extract_nested(resp, "Result", "Status")
            or extract_nested(resp, "Status")
        )
        return status, resp

    def upload_and_wait(
        self,
        image_url: str,
        group_id: str,
        *,
        poll_interval: int = ASSET_POLL_INTERVAL,
        poll_timeout: int = ASSET_POLL_TIMEOUT,
        correlation_id: str = "",
        on_poll: Any = None,          # optional callback(asset_id, status) for progress reporting
    ) -> str:
        """Upload image_url to asset library and poll until Active. Returns asset_id.

        Raises AssetError on failure, TimeoutError if the deadline is exceeded.
        The optional on_poll callback is invoked after each status check — used by
        the CLI to stream progress without coupling the SDK to any output library.
        """
        asset_id = self.create_asset(image_url, group_id, correlation_id=correlation_id)
        logger.info("[%s] Asset created: %s — polling until Active (max %ds)", correlation_id, asset_id, poll_timeout)

        deadline = time.monotonic() + poll_timeout
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            try:
                status, _ = self.get_asset_status(asset_id, correlation_id=correlation_id)
            except APIError as exc:
                logger.warning("[%s] GetAsset poll error (will retry): %s", correlation_id, exc)
                continue

            logger.info("[%s] Asset %s status: %s", correlation_id, asset_id, status)
            if on_poll:
                on_poll(asset_id, status)

            if status == "Active":
                return asset_id
            if status == "Failed":
                raise AssetError(f"Asset {asset_id} processing failed.")

        raise TimeoutError(
            f"Asset {asset_id} did not become Active within {poll_timeout}s. "
            f"Use get_asset_status('{asset_id}') to continue polling."
        )

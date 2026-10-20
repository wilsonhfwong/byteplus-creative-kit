"""BytePlus TOS (object storage) client — TOS4-HMAC-SHA256 signed requests.

Uploads local files to a TOS bucket and returns a public URL that the
generation / asset-library APIs can fetch. Pure stdlib (urllib + hmac), no
runtime dependencies — mirrors the signing machinery in ``asset.py`` but with
the TOS-specific algorithm prefix, header names, and service.

Signing reference: the official ve-tos-python-sdk V4 signer —
  algorithm "TOS4-HMAC-SHA256", headers x-tos-date / x-tos-content-sha256,
  credential scope {date}/{region}/tos/request.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac as hmac_lib
import logging
from typing import cast
from urllib import error, parse
from urllib import request as urllib_request
from xml.etree import ElementTree

from .config import TOS_ENDPOINT, TOS_REGION, TOS_SERVICE, TOS_TIMEOUT
from .exceptions import APIError, StorageError

logger = logging.getLogger("seedance")

_ALGORITHM = "TOS4-HMAC-SHA256"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# TOS4-HMAC-SHA256 signing
# ---------------------------------------------------------------------------

def _hmac_sha256(key: bytes, content: str) -> bytes:
    return hmac_lib.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _quote_path(key: str) -> str:
    # Preserve "/" so nested keys keep their structure; "~" is unreserved.
    return parse.quote(key, safe="/~")


def _sign(
    ak: str,
    sk: str,
    *,
    method: str,
    host: str,
    path: str,
    payload_sha256: str,
    headers: dict[str, str],
) -> dict[str, str]:
    """Return the full set of headers (incl. Authorization) for a signed request.

    ``headers`` holds any caller-supplied request headers (e.g. content-type,
    x-tos-acl); host / x-tos-date / x-tos-content-sha256 are added here.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]

    signed = {k.lower(): v for k, v in headers.items()}
    signed["host"] = host
    signed["x-tos-date"] = x_date
    signed["x-tos-content-sha256"] = payload_sha256

    # Signed headers: host, content-type (if present), and every x-tos-* header.
    names = sorted(
        n for n in signed
        if n == "host" or n == "content-type" or n.startswith("x-tos-")
    )
    canonical_headers = "".join(f"{n}:{signed[n].strip()}\n" for n in names)
    signed_headers = ";".join(names)

    canonical_request = "\n".join([
        method, path, "", canonical_headers, signed_headers, payload_sha256,
    ])

    credential_scope = f"{short_date}/{TOS_REGION}/{TOS_SERVICE}/request"
    string_to_sign = "\n".join([
        _ALGORITHM,
        x_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    k_date    = _hmac_sha256(sk.encode(), short_date)
    k_region  = _hmac_sha256(k_date, TOS_REGION)
    k_service = _hmac_sha256(k_region, TOS_SERVICE)
    k_signing = _hmac_sha256(k_service, "request")
    signature = _hmac_sha256(k_signing, string_to_sign).hex()

    authorization = (
        f"{_ALGORITHM} Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    out = dict(headers)
    out["Host"] = host
    out["X-Tos-Date"] = x_date
    out["X-Tos-Content-Sha256"] = payload_sha256
    out["Authorization"] = authorization
    return out


def _strip_ns(tag: str) -> str:
    """Drop an XML namespace prefix: '{ns}Bucket' -> 'Bucket'."""
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# TOS client
# ---------------------------------------------------------------------------

class TOSClient:
    """Minimal TOS object-storage client: list buckets and put objects."""

    def __init__(
        self,
        ak: str,
        sk: str,
        *,
        region: str = TOS_REGION,
        endpoint: str = TOS_ENDPOINT,
    ) -> None:
        self._ak = ak
        self._sk = sk
        self._region = region
        self._endpoint = endpoint

    # -- internal request helpers ------------------------------------------

    def _request(
        self,
        method: str,
        host: str,
        path: str,
        *,
        body: bytes = b"",
        payload_sha256: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> bytes:
        if payload_sha256 is None:
            payload_sha256 = hashlib.sha256(body).hexdigest() if body else _EMPTY_SHA256
        headers = self._sign_headers(
            method, host, path, payload_sha256, extra_headers or {}
        )
        url = f"https://{host}{path}"
        data = body if method in ("PUT", "POST") else None
        req = urllib_request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib_request.urlopen(req, timeout=TOS_TIMEOUT) as resp:
                # urlopen is Any-typed in typeshed; the body is bytes.
                return cast(bytes, resp.read())
        except error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")
            raise APIError(f"TOS HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except error.URLError as exc:
            raise APIError(f"TOS network error: {exc.reason}") from exc

    def _sign_headers(
        self,
        method: str,
        host: str,
        path: str,
        payload_sha256: str,
        extra_headers: dict[str, str],
    ) -> dict[str, str]:
        return _sign(
            self._ak, self._sk,
            method=method, host=host, path=path,
            payload_sha256=payload_sha256, headers=extra_headers,
        )

    # -- public API ---------------------------------------------------------

    def list_buckets(self) -> list[dict[str, str]]:
        """Return the account's buckets: [{name, location, creation_date}, ...].

        BytePlus TOS returns a JSON body ({"Buckets": [...]}); some S3-compatible
        deployments return XML (ListAllMyBucketsResult). Both are handled.
        """
        raw = self._request("GET", self._endpoint, "/")
        text = raw.decode(errors="ignore").lstrip()
        if text.startswith("{"):
            return self._parse_buckets_json(text)
        return self._parse_buckets_xml(raw)

    @staticmethod
    def _parse_buckets_json(text: str) -> list[dict[str, str]]:
        import json
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StorageError(f"Could not parse TOS ListBuckets JSON: {exc}") from exc
        buckets: list[dict[str, str]] = []
        for b in data.get("Buckets") or []:
            name = (b.get("Name") or "").strip()
            if not name:
                continue
            buckets.append({
                "name": name,
                "location": (b.get("Location") or "").strip(),
                "creation_date": (b.get("CreationDate") or "").strip(),
            })
        return buckets

    @staticmethod
    def _parse_buckets_xml(raw: bytes) -> list[dict[str, str]]:
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise StorageError(f"Could not parse TOS ListBuckets response: {exc}") from exc
        buckets: list[dict[str, str]] = []
        for elem in root.iter():
            if _strip_ns(elem.tag) != "Bucket":
                continue
            entry: dict[str, str] = {}
            for child in elem:
                tag = _strip_ns(child.tag)
                if tag == "Name":
                    entry["name"] = (child.text or "").strip()
                elif tag == "Location":
                    entry["location"] = (child.text or "").strip()
                elif tag == "CreationDate":
                    entry["creation_date"] = (child.text or "").strip()
            if entry.get("name"):
                buckets.append(entry)
        return buckets

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        public: bool = True,
    ) -> str:
        """Upload bytes to bucket/key. Returns the object URL.

        When ``public`` is set the object is written with a public-read ACL, so
        the returned URL is directly fetchable. If the bucket forbids public
        ACLs, set public=False and use a presigned URL via presign_get().
        """
        if not bucket:
            raise StorageError("bucket is required.")
        if not key:
            raise StorageError("key is required.")
        host = f"{bucket}.{self._endpoint}"
        path = "/" + _quote_path(key.lstrip("/"))
        extra = {"Content-Type": content_type}
        if public:
            extra["X-Tos-Acl"] = "public-read"
        self._request("PUT", host, path, body=data, extra_headers=extra)
        return f"https://{host}{path}"

    def presign_get(self, bucket: str, key: str, *, expires: int = 86400) -> str:
        """Build a presigned GET URL (query-string V4 signature), default 24h."""
        if not bucket or not key:
            raise StorageError("bucket and key are required.")
        host = f"{bucket}.{self._endpoint}"
        path = "/" + _quote_path(key.lstrip("/"))
        now = datetime.datetime.now(datetime.timezone.utc)
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        short_date = x_date[:8]
        scope = f"{short_date}/{self._region}/{TOS_SERVICE}/request"

        q = {
            "X-Tos-Algorithm": _ALGORITHM,
            "X-Tos-Credential": f"{self._ak}/{scope}",
            "X-Tos-Date": x_date,
            "X-Tos-Expires": str(expires),
            "X-Tos-SignedHeaders": "host",
        }
        canonical_query = "&".join(
            f"{parse.quote(k, safe='-_.~')}={parse.quote(v, safe='-_.~')}"
            for k, v in sorted(q.items())
        )
        canonical_headers = f"host:{host}\n"
        canonical_request = "\n".join([
            "GET", path, canonical_query, canonical_headers, "host", "UNSIGNED-PAYLOAD",
        ])
        string_to_sign = "\n".join([
            _ALGORITHM, x_date, scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])
        k_date    = _hmac_sha256(self._sk.encode(), short_date)
        k_region  = _hmac_sha256(k_date, self._region)
        k_service = _hmac_sha256(k_region, TOS_SERVICE)
        k_signing = _hmac_sha256(k_service, "request")
        signature = _hmac_sha256(k_signing, string_to_sign).hex()
        return f"https://{host}{path}?{canonical_query}&X-Tos-Signature={signature}"

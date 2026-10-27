"""Asset lifecycle extension, reusing Mittul's signed AssetClient.

API bodies are adapted from the supplied Seed Studio asset client and checked
against the official Assets API. No retries are made for remote creations.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .settings import DATA_DIR, redact

FORMATS = {
    "Image": {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif", ".heic", ".heif"},
    "Video": {".mp4", ".mov"},
}
MAX_BYTES = {"Image": 30 * 1024 * 1024, "Video": 200 * 1024 * 1024}


def media_type(source: str, requested: str = "") -> str:
    suffix = Path(urlsplit(source).path if source.startswith("https://") else source).suffix.lower()
    inferred = next((kind for kind, suffixes in FORMATS.items() if suffix in suffixes), "")
    if requested and requested not in FORMATS:
        raise ValueError("asset_type must be Image or Video.")
    if requested and inferred and requested != inferred:
        raise ValueError("The explicit asset type does not match the file extension.")
    kind = requested or inferred
    if not kind:
        raise ValueError("Use a supported image/video extension or specify asset_type for an HTTPS URL.")
    return kind


def validate_https(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Provide a direct HTTPS media URL without embedded credentials.")


class LibraryAPI:
    def __init__(self, settings: dict):
        from seedance.asset import AssetClient
        ak, sk = settings.get("access_key", ""), settings.get("secret_key", "")
        if not ak or not sk:
            raise ValueError("Configure ARK_AK and ARK_SK as cloud environment secrets for the asset library.")
        self.client = AssetClient(ak, sk)

    def call(self, action: str, payload: dict) -> dict:
        # The shared transport checks ResponseMetadata.Error even on HTTP 200.
        response = self.client._call(action, payload)
        result = response.get("Result")
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected result shape from {action}.")
        return result

    def create_group(self, name: str, description: str = "") -> dict:
        if not name.strip():
            raise ValueError("A group name is required.")
        return self.call("CreateAssetGroup", {"Name": name, "Description": description, "GroupType": "AIGC"})

    def get_group(self, group_id: str) -> dict:
        return self.call("GetAssetGroup", {"Id": group_id})

    def create_asset(self, group_id: str, url: str, asset_type: str, operation_id: str) -> str:
        return self.client.create_asset(url, group_id, asset_type=asset_type, name=f"byteplus-creative-kit-{operation_id}")

    def get_asset(self, asset_id: str) -> dict:
        return self.call("GetAsset", {"Id": asset_id})

    def list_groups(self, next_token: str = "", max_results: int = 50) -> dict:
        body = {"Filter": {"GroupType": "AIGC"}, "MaxResults": min(max(max_results, 1), 100)}
        if next_token:
            body["NextToken"] = next_token
        return self.call("ListAssetGroups", body)

    def list_assets(self, group_id: str, next_token: str = "", max_results: int = 50) -> dict:
        if not group_id:
            raise ValueError("A group ID is required.")
        group = self.get_group(group_id)
        body = {"Filter": {"GroupIds": [group_id], "GroupType": group.get("GroupType", "AIGC")}, "MaxResults": min(max(max_results, 1), 100)}
        if next_token:
            body["NextToken"] = next_token
        return self.call("ListAssets", body)

    def update_asset(self, asset_id: str, name: str) -> dict:
        # The live API persisted Name; it did not return a supplied Description.
        # Expose the verified operation rather than silently accepting that field.
        return self.call("UpdateAsset", {"Id": asset_id, "Name": name})

    def delete_asset(self, asset_id: str) -> dict:
        return self.call("DeleteAsset", {"Id": asset_id})


class Storage:
    def __init__(self, settings: dict):
        import tos
        self.tos = tos
        self.bucket = settings.get("tos_bucket", "")
        if not self.bucket:
            raise ValueError("Configure SEEDANCE_TOS_BUCKET before importing workspace files.")
        ak = settings.get("tos_access_key") or settings.get("access_key", "")
        sk = settings.get("tos_secret_key") or settings.get("secret_key", "")
        token = settings.get("tos_session_token") or settings.get("session_token", "")
        if not ak or not sk:
            raise ValueError("TOS upload requires IAM/TOS Access Key and Secret Key.")
        self.client = tos.TosClientV2(ak, sk, settings["tos_endpoint"], settings["tos_region"], security_token=token or None)
        self.ttl = min(max(int(settings.get("presign_seconds", 86400)), 60), 604800)

    def upload(self, path: Path, key: str) -> None:
        # No public-read ACL is sent: the object inherits the bucket's policy.
        self.client.put_object_from_file(self.bucket, key, file_path=str(path), content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def presign(self, key: str) -> str:
        return self.client.pre_signed_url(self.tos.HttpMethodType.Http_Method_Get, self.bucket, key, expires=self.ttl).signed_url


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS imports (operation_id TEXT PRIMARY KEY, fingerprint TEXT, group_id TEXT, asset_type TEXT, object_key TEXT, asset_id TEXT, state TEXT, error TEXT, created REAL)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        return db

    def reserve(self, fingerprint: str, group_id: str, asset_type: str, operation_id: str = "") -> tuple[dict, bool]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM imports WHERE operation_id = ?", (operation_id,)).fetchone() if operation_id else db.execute("SELECT * FROM imports WHERE fingerprint = ? AND group_id = ? AND state != 'deleted' ORDER BY created DESC LIMIT 1", (fingerprint, group_id)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint or existing["group_id"] != group_id or existing["asset_type"] != asset_type:
                    raise ValueError("That operation ID belongs to a different source, type or group.")
                return dict(existing), False
            op = operation_id or uuid.uuid4().hex
            db.execute("INSERT INTO imports VALUES (?, ?, ?, ?, '', '', 'prepared', '', ?)", (op, fingerprint, group_id, asset_type, time.time()))
        return self.get(op), True

    def get(self, operation_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM imports WHERE operation_id = ?", (operation_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown import operation ID.")
        return dict(row)

    def patch(self, operation_id: str, **values) -> dict:
        if not set(values) <= {"object_key", "asset_id", "state", "error"}:
            raise ValueError("Invalid import state field.")
        with self.connect() as db:
            db.execute("UPDATE imports SET " + ", ".join(f"{key} = ?" for key in values) + " WHERE operation_id = ?", (*values.values(), operation_id))
        return self.get(operation_id)

    def mark_asset(self, asset_id: str, state: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE imports SET state = ? WHERE asset_id = ?", (state, asset_id))


class Library:
    def __init__(self, settings: dict, *, api=None, storage=None, db_path: Path | None = None):
        self.settings, self._api, self._storage = settings, api, storage
        self.store = Store(db_path or DATA_DIR / "library.sqlite3")

    @property
    def api(self):
        if self._api is None:
            self._api = LibraryAPI(self.settings)
        return self._api

    @property
    def storage(self):
        if self._storage is None:
            self._storage = Storage(self.settings)
        return self._storage

    @staticmethod
    def describe(row: dict) -> dict:
        result = dict(row)
        if row.get("asset_id"):
            result["asset_ref"] = "asset://" + row["asset_id"]
        result["message"] = "Retained for reuse. Poll seedance_library_get_asset until Status is Active."
        if row["state"] in {"registering", "submission_unresolved", "uploading", "upload_unresolved", "prepared", "failed"}:
            result["message"] = "This import is incomplete. Do not repeat remote creation automatically. Inspect this operation and the group's recent assets; a lost response may still have created an asset."
        return result

    def import_asset(self, group_id: str, file_path: str = "", source_url: str = "", asset_type: str = "", operation_id: str = "") -> dict:
        if bool(file_path) == bool(source_url):
            raise ValueError("Supply exactly one of file_path or source_url.")
        if not group_id:
            raise ValueError("Choose an existing group ID, or create a group first.")
        kind = media_type(file_path or source_url, asset_type)
        path = Path(file_path).expanduser().resolve() if file_path else None
        if path:
            if not path.is_file():
                raise ValueError("The local media file does not exist.")
            size = path.stat().st_size
            if size == 0 or size > MAX_BYTES[kind] or (kind == "Image" and size == MAX_BYTES[kind]):
                raise ValueError(f"Invalid file size for {kind}: images must be under 30 MiB; videos at most 200 MiB.")
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
        else:
            validate_https(source_url)
            digest = hashlib.sha256(source_url.encode()).hexdigest()
        # Reject the wrong group before uploading any bytes.
        self.api.get_group(group_id)
        row, fresh = self.store.reserve(digest, group_id, kind, operation_id)
        if not fresh:
            return self.describe(row)
        op = row["operation_id"]
        stage = "prepared"
        asset_id = ""
        try:
            url = source_url
            if path:
                key = f"byteplus-creative-kit/{op}{path.suffix.lower()}"
                storage = self.storage
                self.store.patch(op, object_key=key, state="uploading")
                stage = "uploading"
                storage.upload(path, key)
                self.store.patch(op, state="uploaded")
                stage = "uploaded"
                url = storage.presign(key)
            self.store.patch(op, state="registering")
            stage = "registering"
            asset_id = self.api.create_asset(group_id, url, kind, op)
            row = self.store.patch(op, asset_id=asset_id, state="Processing")
            return self.describe(row)
        except Exception as exc:
            state = "submission_unresolved" if stage == "registering" else "upload_unresolved" if stage == "uploading" else "failed"
            error = redact(str(exc), self.settings)
            row = self.store.patch(op, state=state, error=error, **({"asset_id": asset_id} if asset_id else {}))
            return {**self.describe(row), "error": error}

    def get_asset(self, asset_id: str) -> dict:
        result = self.api.get_asset(asset_id)
        status = result.get("Status", "Unknown")
        self.store.mark_asset(asset_id, status)
        # The raw GetAsset URL is temporary. Keep it out of normal tool output.
        result = {k: v for k, v in result.items() if k not in {"URL", "Url", "AssetUrl"}}
        return {**result, "asset_id": asset_id, "asset_ref": "asset://" + asset_id, "usable": status == "Active"}

    def reconcile(self, operation_id: str, asset_id: str) -> dict:
        row = self.store.get(operation_id)
        asset = self.api.get_asset(asset_id)
        if asset.get("GroupId") != row["group_id"] or asset.get("AssetType") != row["asset_type"]:
            raise ValueError("The asset does not match this import's group and media type.")
        return self.describe(self.store.patch(operation_id, asset_id=asset_id, state=asset.get("Status", "Unknown"), error=""))

    def delete_asset(self, asset_id: str, confirm: bool) -> dict:
        if not confirm:
            raise ValueError("Deletion is permanent. Supply confirm=true only for an explicitly requested asset deletion.")
        result = self.api.delete_asset(asset_id)
        self.store.mark_asset(asset_id, "deleted")
        return {"asset_id": asset_id, "delete_request_succeeded": True, "result": result, "source_object_deleted": False}

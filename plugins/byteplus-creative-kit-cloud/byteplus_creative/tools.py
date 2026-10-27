"""Small MCP adapters for the new asset workflow and local output saving."""
from __future__ import annotations

import functools
import json
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .library import Library, Storage, media_type, validate_https
from .settings import OUTPUT_DIR, redact


def guarded(function, settings):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            if isinstance(result, dict) and result.get("status") == "error":
                result = {**result, "error": redact(str(result.get("error", "Operation failed")), settings)}
            return result
        except Exception as exc:
            return {"status": "error", "error": redact(str(exc), settings)}
    return wrapped


def register(server, settings: dict) -> None:
    from mcp.types import ToolAnnotations
    instance = None

    def library():
        nonlocal instance
        if instance is None:
            instance = Library(settings)
        return instance

    def tool(*, read_only=False, destructive=False):
        def decorate(function):
            server.tool(annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive, idempotentHint=read_only))(guarded(function, settings))
            return function
        return decorate

    @tool()
    def seedance_library_create_group(name: str, description: str = "") -> dict:
        """Create one persistent AIGC group for a fictional subject. Reuse its returned Id. For real people use a previously console-verified group; this tool does not verify people."""
        return library().api.create_group(name, description)

    @tool(read_only=True)
    def seedance_library_list_groups(next_token: str = "", max_results: int = 50) -> dict:
        """List virtual AIGC groups. Follow NextToken to see more pages. These are account/project-owned groups."""
        return library().api.list_groups(next_token, max_results)

    @tool(read_only=True)
    def seedance_library_get_group(group_id: str) -> dict:
        """Inspect an existing group, including a known console-verified real-person group."""
        return library().api.get_group(group_id)

    @tool()
    def seedance_library_import(group_id: str, file_path: str = "", source_url: str = "", asset_type: str = "", operation_id: str = "") -> dict:
        """Import exactly one local image/video or direct HTTPS media URL into an existing group. Local files use private TOS plus a signed GET URL. Explicit types: Image or Video. Saves the operation and asset IDs; returns Processing promptly. Poll seedance_library_get_asset separately until Active. Repeating the same source/group reuses its recorded operation. Never automatically retry an unresolved creation."""
        return library().import_asset(group_id, file_path, source_url, asset_type, operation_id)

    @tool(read_only=True)
    def seedance_library_get_asset(asset_id: str) -> dict:
        """Get an asset's type, status and asset:// reference. Only usable=true / Status=Active permits generation; Processing needs another poll, Failed needs reporting."""
        return library().get_asset(asset_id)

    @tool(read_only=True)
    def seedance_library_list_assets(group_id: str, next_token: str = "", max_results: int = 50) -> dict:
        """List one group's assets with a real group filter. Follow NextToken for all pages. IDs persist across chats; source TOS objects are distinct from library assets."""
        result = library().api.list_assets(group_id, next_token, max_results)
        # Avoid returning temporary provider preview grants in routine listings.
        for key in ("Items", "Assets"):
            if isinstance(result.get(key), list):
                result[key] = [{k: v for k, v in item.items() if k not in {"URL", "Url", "AssetUrl"}} for item in result[key]]
        return result

    @tool()
    def seedance_library_update_asset(asset_id: str, name: str) -> dict:
        """Update an asset's remote name. The model still references the asset by asset:// ID and media position, not its name."""
        return library().api.update_asset(asset_id, name)

    @tool(destructive=True)
    def seedance_library_delete_asset(asset_id: str, confirm: bool = False) -> dict:
        """Permanently delete the exact library asset explicitly requested by the user. confirm=true is required. Ensure no active/unknown generation still depends on it. Does not delete its TOS source object."""
        return library().delete_asset(asset_id, confirm)

    @tool(read_only=True)
    def seedance_library_import_status(operation_id: str) -> dict:
        """Read a persisted import after restart or timeout. An unresolved submission must be reconciled, not recreated."""
        return library().describe(library().store.get(operation_id))

    @tool()
    def seedance_library_reconcile_import(operation_id: str, asset_id: str) -> dict:
        """Attach an existing cloud asset ID found after an interrupted import. Checks matching group and type; creates no cloud asset."""
        return library().reconcile(operation_id, asset_id)

    @tool()
    def seed_media_upload(file_path: str) -> dict:
        """Upload a local image/video to TOS without registering it in the asset library. Returns a temporary signed HTTPS source_url, suitable for Seedream image references. Use seedance_library_import for reusable Seedance assets."""
        path = Path(file_path).expanduser().resolve()
        kind = media_type(str(path))
        from .library import MAX_BYTES
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES[kind]:
            raise ValueError("The file is missing, empty or exceeds the supported size limit.")
        storage = Storage(settings)
        key = f"byteplus-creative-kit/source-{uuid.uuid4().hex}{path.suffix.lower()}"
        storage.upload(path, key)
        return {"source_url": storage.presign(key), "object_key": key, "expires_seconds": storage.ttl, "asset_type": kind}

    @tool()
    def seed_media_download(url: str, filename: str = "") -> dict:
        """Save a provider-generated HTTPS result into the configured cloud workspace output directory. Existing files are never overwritten. Download output promptly because provider URLs expire."""
        validate_https(url)
        suffix = Path(urlsplit(url).path).suffix
        filename = filename or f"generated-{uuid.uuid4().hex[:12]}{suffix or '.bin'}"
        if filename != Path(filename).name or "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ValueError("Use a filename without directory paths.")
        directory = OUTPUT_DIR
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / filename
        if target.exists() or target.is_symlink():
            raise ValueError("That output filename already exists; choose another.")
        temporary = directory / (".download-" + uuid.uuid4().hex)
        size = 0
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("xb") as output:
                if urlsplit(response.url).scheme != "https":
                    raise ValueError("The download redirected away from HTTPS.")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 1024 * 1024 * 1024:
                        raise ValueError("The output exceeds the 1 GiB download limit.")
                    output.write(chunk)
            if size == 0:
                raise ValueError("The provider returned an empty output.")
            # A hard link atomically claims the final name without overwriting.
            import os
            os.link(temporary, target)
            return {"local_path": str(target), "bytes": size}
        finally:
            temporary.unlink(missing_ok=True)

    if settings.get("seed_model"):
        @tool()
        def seed_text(prompt: str, max_output_tokens: int = 2048) -> dict:
            """Call the configured optional Seed text model for prompt planning or text assistance. This is a billed model call; Codex remains the orchestrator."""
            payload = {"model": settings["seed_model"], "input": prompt, "max_output_tokens": min(max(max_output_tokens, 1), 16384)}
            request = urllib.request.Request(settings["ark_base_url"].rstrip("/") + "/responses", data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + settings["api_key"], "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)

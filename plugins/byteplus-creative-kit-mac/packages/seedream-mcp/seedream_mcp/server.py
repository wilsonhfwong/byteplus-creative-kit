"""Seedream MCP Server — thin MCP adapter over seedream-sdk.

Each tool is a minimal wrapper: validate inputs, call SeedreamClient, return dict.
All business logic (retry, signing, TOS upload) lives in seedream-sdk.

Environment variables (all optional if ~/.seedream/credentials is configured):
    ARK_API_KEY      BytePlus ModelArk bearer token (required for generation)
    ARK_AK           IAM Access Key ID  (required only for TOS upload tools)
    ARK_SK           IAM Secret Key     (required only for TOS upload tools)
    MCP_TRANSPORT    "stdio" (default) | "sse"
    MCP_AUTH_TOKEN   Bearer token for SSE transport auth (optional)
    PORT             HTTP port for SSE transport (default: 8000)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError as exc:
    raise SystemExit(
        "mcp package not found. Install it: pip install mcp"
    ) from exc

from seedream import SeedreamClient
from seedream.config import __version__
from seedream.exceptions import SeedreamError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("seedream_mcp")

mcp = FastMCP(
    name="seedream",
    instructions=(
        "Tools for generating images with BytePlus Seedream 4.5, 5.0 Lite and 5.0 Pro. "
        "PREFERRED: use seedream_generate for most tasks — it is synchronous and returns "
        "the finished image URLs directly (no polling needed). "
        "For text-to-image, pass just a prompt. For editing or reference-based generation, "
        "pass image_urls (public HTTPS URLs) and describe what to change and what to keep. "
        "For consistent multi-panel sets, set sequential=true and num_images=N. "
        "When the user has a LOCAL image file (a filesystem path) that needs to be used as a "
        "reference, first upload it with seedream_upload_image_to_tos to get a public URL. If "
        "the user has not said which bucket, call seedream_list_tos_buckets and ASK which to use. "
        "To split an image into separate layers (text groups, subjects, background), set "
        "layer_decomposition=true with model='5.0-pro' and the source image in image_urls. "
        "Model IDs: seedream-4-5-251128 (Seedream 4.5), seedream-5-0-260128 (Seedream 5.0 "
        "Lite), dola-seedream-5-0-pro-260628 (Seedream 5.0 Pro). "
        "Note: Seedream 4.5 does not support the 1K size — use 2K or 4K. Seedream 5.0 Pro "
        "supports only 1K/2K and has no sequential sets or guidance_scale."
    ),
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _client() -> SeedreamClient:
    return SeedreamClient()


def _err(exc: Exception) -> dict[str, Any]:
    logger.error("Tool error: %s", exc)
    return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

@mcp.tool()
def seedream_generate(
    prompt: str,
    model: str = "",
    size: str = "",
    image_urls: list[str] | None = None,
    seed: int | None = None,
    guidance_scale: float | None = None,
    sequential: bool = False,
    num_images: int = 1,
    response_format: str = "url",
    watermark: bool = False,
    optimize_prompt: bool = False,
    output_format: str = "",
    layer_decomposition: bool = False,
) -> dict:
    """Generate image(s) with BytePlus Seedream. Synchronous — returns image URLs directly.

    Handles all four modes in one call:
      1. Text-to-image: pass only a prompt.
      2. Edit / reference / composition: pass image_urls (public HTTPS URLs) and
         describe what to change and what to preserve.
      3. Sequential image set: set sequential=true and num_images=N for a
         consistent multi-panel series.
      4. Layer decomposition: set layer_decomposition=true with model="5.0-pro"
         to split one input image into separate layers.

    Args:
        prompt: Natural-language description. For text-in-image, wrap the exact
                words in double quotes. For editing, state what to change and keep.
        model: Model ID or alias. "4.5" / seedream-4-5-251128 (default),
               "5.0-lite" / seedream-5-0-260128,
               "5.0-pro" / dola-seedream-5-0-pro-260628.
               Seedream 4.5 has no 1K size; 5.0 Pro has no 4K/adaptive size, no
               sequential sets and no guidance_scale, and caps refs at 10.
        size: "1K" | "2K" | "4K" | "adaptive" | explicit "WxH" (e.g. 2048x2048).
              Defaults to the model's default (2K).
        image_urls: Reference image URLs (public HTTPS). Local files must be
                    uploaded first via seedream_upload_image_to_tos.
        seed: Random seed for reproducible results.
        guidance_scale: Prompt adherence 1.0–20.0 (higher = stricter).
        sequential: Enable sequential image-set generation (consistent panels).
        num_images: Number of images when sequential is enabled (refs + outputs ≤ 15).
        response_format: "url" (default) or "b64_json".
        watermark: Add a watermark to the output.
        optimize_prompt: Ask the API to expand/optimize the prompt.
        output_format: "png" or "jpeg" (5.0 Pro / 5.0 Lite only; API default jpeg).
        layer_decomposition: Split the image in image_urls into separate layers,
                returning one image per layer. Seedream 5.0 Pro only, and requires
                image_urls. In the prompt, say how many layers and name each with
                its bounding box, e.g. 'Split the content in the image into three
                layers, including two text groups: <bbox>179 58 809 197</bbox>,
                <bbox>65 216 319 280</bbox>; and one parrot: <bbox>330 274 641
                991</bbox>'. bbox coordinates are left top right bottom on a
                0–1000 scale. Use output_format="png" to keep transparency.

    Returns:
        dict with model, count, and images (each with url or b64_json).
        With layer_decomposition: n+1 images — a flattened base image at
        z_index 0 plus one per layer at z_index 1..n, each carrying name,
        description and bounding_box. Layers are PNG with transparency even
        when output_format is jpeg. The decomposition is intermittent: if no
        image has a z_index it silently did not apply, so retry once.
    """
    try:
        result = _client().generate(
            prompt,
            model=model,
            size=size,
            image_urls=image_urls,
            seed=seed,
            guidance_scale=guidance_scale,
            sequential=sequential,
            num_images=num_images,
            response_format=response_format,
            watermark=watermark,
            optimize_prompt=optimize_prompt,
            output_format=output_format,
            layer_decomposition=layer_decomposition,
        )
    except SeedreamError as exc:
        return _err(exc)

    out = result.to_dict()
    if layer_decomposition and result.urls:
        if result.layers:
            out["message"] = (
                f"{len(result.layers)} layer(s) ready, plus the flattened base image. "
                "Layers are listed with z_index (1 = bottom) and are transparent PNGs."
            )
        else:
            out["message"] = (
                "Decomposition did not apply — the API returned a single flattened "
                "image with no layers. This is intermittent; retry the same request."
            )
    elif result.urls:
        out["message"] = "Image(s) ready. Display or download the url(s)."
    else:
        out["message"] = "Image(s) generated as base64 (response_format=b64_json)."
    return out


# ---------------------------------------------------------------------------
# TOS object storage tools (upload local reference images)
# ---------------------------------------------------------------------------

@mcp.tool()
def seedream_list_tos_buckets() -> dict:
    """List the TOS (object storage) buckets available to your AK/SK.

    Call this first when the user wants to use a local image as a reference but
    has not said which bucket — show the list and ask which bucket to use, then
    pass that bucket to seedream_upload_image_to_tos.

    Returns:
        dict with a `buckets` list (name, location, creation_date).
    """
    try:
        buckets = _client().list_tos_buckets()
    except SeedreamError as exc:
        return _err(exc)

    return {
        "status": "ok",
        "count": len(buckets),
        "buckets": buckets,
        "message": (
            "Ask the user which bucket to upload to, then call "
            "seedream_upload_image_to_tos(file_path=..., bucket=...)."
            if buckets else "No buckets found for these credentials."
        ),
    }


@mcp.tool()
def seedream_upload_image_to_tos(file_path: str, bucket: str = "", key: str = "") -> dict:
    """Upload a LOCAL image file to a TOS bucket and return its public URL.

    Reads the file from the local filesystem (this server runs locally), uploads
    it with a public-read ACL, and returns a directly fetchable URL that can be
    passed as one of the image_urls in seedream_generate.

    If `bucket` is empty and no default (SEEDREAM_TOS_BUCKET) is configured, call
    seedream_list_tos_buckets first and ask the user which bucket to use.

    Args:
        file_path: Absolute path to a local image (e.g. /Users/you/photo.png).
        bucket: Target TOS bucket. Optional if SEEDREAM_TOS_BUCKET is set.
        key: Object key within the bucket. Defaults to the filename.

    Returns:
        dict with bucket, key, and the public url.
    """
    try:
        result = _client().upload_to_tos(file_path, bucket, key)
    except SeedreamError as exc:
        return _err(exc)

    return {
        **result.to_dict(),
        "message": (
            f"Uploaded. Public URL: {result.url}\n"
            "Pass this URL in image_urls of seedream_generate."
        ),
    }


@mcp.tool()
def seedream_list_models() -> dict:
    """List available Seedream models and their capabilities."""
    return _client().list_models()


@mcp.tool()
def seedream_ping() -> dict:
    """Check server liveness and current configuration."""
    return _client().ping()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    port = int(os.getenv("PORT", "8000"))
    auth_token = os.getenv("MCP_AUTH_TOKEN", "").strip()

    if transport == "sse":
        try:
            import uvicorn
        except ImportError as exc:
            raise SystemExit("SSE transport requires uvicorn: pip install uvicorn") from exc

        mcp_app = mcp.streamable_http_app()

        class _Gateway:
            """ASGI middleware: health check, bearer-token auth, host-header rewrite."""

            def __init__(self, app: Any) -> None:
                self._app = app

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                if scope["type"] != "http":
                    await self._app(scope, receive, send)
                    return

                path = scope.get("path", "")

                if path == "/health":
                    body = json.dumps({"status": "ok", "version": __version__}).encode()
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": body})
                    return

                if auth_token:
                    hdrs = {k.lower(): v for k, v in scope.get("headers", [])}
                    auth = hdrs.get(b"authorization", b"").decode()
                    if auth != f"Bearer {auth_token}":
                        body = json.dumps({"error": "Unauthorized"}).encode()
                        await send({"type": "http.response.start", "status": 401,
                                    "headers": [(b"content-type", b"application/json")]})
                        await send({"type": "http.response.body", "body": body})
                        return

                new_hdrs = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"host"]
                new_hdrs.append((b"host", b"localhost"))
                await self._app({**scope, "headers": new_hdrs}, receive, send)

        logger.info("Starting Seedream MCP server v%s on :%d (streamable-http, auth=%s)",
                    __version__, port, bool(auth_token))
        uvicorn.run(_Gateway(mcp_app), host="0.0.0.0", port=port)
    else:
        logger.info("Starting Seedream MCP server v%s (stdio)...", __version__)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    _main()

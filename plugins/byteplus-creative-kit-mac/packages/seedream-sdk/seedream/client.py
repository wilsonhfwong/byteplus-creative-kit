"""SeedreamClient — the primary entry point for the Seedream SDK."""
from __future__ import annotations

import base64
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from .config import (
    BASE_URL,
    DEFAULT_MODEL,
    DOWNLOAD_TIMEOUT,
    INCLUDE_RAW,
    MAX_REFERENCE_IMAGES,
    MAX_SEQUENTIAL_IMAGES,
    MODELS,
    OUTPUT_FORMATS,
    SIZE_WH_RE,
    SUBMIT_TIMEOUT,
    TOS_DEFAULT_BUCKET,
    TOS_ENDPOINT,
    TOS_REGION,
    __version__,
    model_caps,
    resolve_model,
)
from .credentials import (
    credentials_configured,
    load_api_key,
    load_asset_credentials,
)
from .exceptions import ValidationError
from .http import extract_images, request_with_retry
from .tos import TOSClient
from .types import GenerateResult, ImageResult, TOSUploadResult

logger = logging.getLogger("seedream")


class SeedreamClient:
    """Client for BytePlus Seedream 4.5 / 5.0 Lite / 5.0 Pro image generation.

    Credentials are resolved in priority order: explicit args → env vars →
    ~/.seedream/credentials file.

    Usage:
        client = SeedreamClient()   # picks up creds automatically
        result = client.generate(prompt="A sunrise over mountains", size="2K")
        print(result.urls)

    The Seedream image API is synchronous — generate() returns the finished
    image URLs directly. There is no task to poll.
    """

    def __init__(
        self,
        api_key: str | None = None,
        ak: str | None = None,
        sk: str | None = None,
        *,
        profile: str = "default",
    ) -> None:
        self._api_key_override = api_key
        self._ak_override = ak
        self._sk_override = sk
        self._profile = profile

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        return load_api_key(self._api_key_override, profile=self._profile)

    def _tos_client(self) -> TOSClient:
        ak, sk = load_asset_credentials(self._ak_override, self._sk_override, profile=self._profile)
        return TOSClient(ak, sk)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _cid() -> str:
        return str(uuid.uuid4())[:8]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_size(size: str, model: str) -> None:
        caps = model_caps(model)
        # Accept a named preset the model supports, or an explicit WxH string.
        if size in caps["sizes"] or SIZE_WH_RE.match(size):
            return
        raise ValidationError(
            f"Invalid size {size!r} for model {model}. "
            f"Use one of {', '.join(caps['sizes'])} or an explicit WxH like 2048x2048."
        )

    @staticmethod
    def _validate_guidance(guidance_scale: float | None) -> None:
        if guidance_scale is None:
            return
        if not 1.0 <= guidance_scale <= 20.0:
            raise ValidationError(
                f"Invalid guidance_scale {guidance_scale}. Must be between 1.0 and 20.0."
            )

    @staticmethod
    def _validate_references(
        image_urls: list[str] | None, n_sequential: int, model: str
    ) -> None:
        caps = model_caps(model)
        max_refs = caps.get("max_reference_images", MAX_REFERENCE_IMAGES)
        n_refs = len(image_urls or [])
        if image_urls and not all(image_urls):
            raise ValidationError("image contains an empty entry.")
        if n_refs > max_refs:
            raise ValidationError(
                f"Too many reference images: {n_refs} (max {max_refs} for {model})."
            )
        # Seedream rule: input references + generated images must total ≤ 15.
        if n_refs + max(1, n_sequential) > MAX_SEQUENTIAL_IMAGES:
            raise ValidationError(
                f"reference images ({n_refs}) + generated images ({n_sequential}) "
                f"exceeds the limit of {MAX_SEQUENTIAL_IMAGES}. Reduce one of them."
            )

    @staticmethod
    def _validate_features(
        model: str,
        *,
        sequential: bool,
        guidance_scale: float | None,
        output_format: str,
        layer_decomposition: bool,
        image_urls: list[str] | None,
    ) -> None:
        """Reject parameters the chosen model does not accept.

        Seedream 5.0 Pro returns InvalidParameter for sequential generation and
        guidance_scale; failing here names the parameter and the model instead.
        """
        caps = model_caps(model)
        label = caps["label"]

        if sequential and not caps.get("supports_sequential", False):
            raise ValidationError(
                f"{label} does not support sequential image sets. "
                f"Drop sequential/num_images, or use a model that supports them."
            )
        if guidance_scale is not None and not caps.get("supports_guidance_scale", False):
            raise ValidationError(f"{label} does not support guidance_scale.")

        if output_format:
            if output_format not in OUTPUT_FORMATS:
                raise ValidationError(
                    f"Invalid output_format {output_format!r}. "
                    f"Use one of {', '.join(OUTPUT_FORMATS)}."
                )
            if not caps.get("supports_output_format", False):
                raise ValidationError(f"{label} does not support output_format.")

        if layer_decomposition:
            if not caps.get("supports_layer_decomposition", False):
                raise ValidationError(
                    f"{label} does not support layer_decomposition. "
                    f"Use model='5.0-pro'."
                )
            if not image_urls:
                raise ValidationError(
                    "layer_decomposition needs an input image to decompose — "
                    "pass it in image_urls."
                )

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
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
    ) -> GenerateResult:
        """Generate one or more images. Returns finished image URLs directly.

        Args:
            prompt: Natural-language description. For editing/reference tasks,
                    say exactly what to change and what to preserve.
            model: Model ID or alias ("4.5", "5.0-lite", "5.0-pro"). Defaults to 4.5.
            size: "1K" | "2K" | "4K" | "adaptive" | explicit "WxH". Model default if empty.
            image_urls: Reference image URLs (HTTPS). For editing / style / multi-image
                        composition. Local files must be uploaded first (upload_to_tos).
            seed: Random seed for reproducibility.
            guidance_scale: Prompt adherence 1.0–20.0 (higher = stricter).
            sequential: Enable sequential image-set generation (consistent multi-panel).
            num_images: Images to generate when sequential is enabled.
            response_format: "url" (default) or "b64_json".
            watermark: Add a watermark to outputs.
            optimize_prompt: Ask the API to expand/optimize the prompt.
            output_format: "png" or "jpeg". 5.0 Pro / 5.0 Lite only. API default jpeg.
            layer_decomposition: Split the input image into separate layers, one
                    generated image per layer. Seedream 5.0 Pro only, and needs
                    image_urls. Name each layer in the prompt with its bounding box,
                    e.g. "Split the content into three layers: two text groups
                    <bbox>179 58 809 197</bbox>, <bbox>65 216 319 280</bbox>; and one
                    parrot <bbox>330 274 641 991</bbox>". Pair with
                    output_format="png" to keep per-layer transparency.
        """
        cid = self._cid()
        model_id = resolve_model(model)
        caps = model_caps(model_id)
        size = size or caps["default_size"]

        if not prompt or not prompt.strip():
            raise ValidationError("prompt is required.")
        if response_format not in ("url", "b64_json"):
            raise ValidationError("response_format must be 'url' or 'b64_json'.")

        self._validate_size(size, model_id)
        self._validate_guidance(guidance_scale)
        self._validate_features(
            model_id,
            sequential=sequential,
            guidance_scale=guidance_scale,
            output_format=output_format,
            layer_decomposition=layer_decomposition,
            image_urls=image_urls,
        )

        n_sequential = num_images if sequential else 1
        self._validate_references(image_urls, n_sequential, model_id)

        payload: dict[str, Any] = {
            "model": model_id,
            "prompt": prompt,
            "size": size,
            "response_format": response_format,
            "watermark": watermark,
        }
        if seed is not None:
            payload["seed"] = seed
        if guidance_scale is not None:
            payload["guidance_scale"] = guidance_scale
        if optimize_prompt:
            # 5.0 Pro takes {"mode": ...}; 4.5 and 5.0 Lite take {"enabled": true}.
            payload["optimize_prompt_options"] = (
                {"mode": "standard"}
                if caps.get("optimize_prompt_shape") == "mode"
                else {"enabled": True}
            )
        if output_format:
            payload["output_format"] = output_format
        if layer_decomposition:
            payload["layer_decomposition"] = True
        if image_urls:
            payload["image"] = image_urls
        if sequential:
            payload["sequential_image_generation"] = "enabled"
            if num_images > 1:
                payload["sequential_image_generation_options"] = {"n": num_images}
        elif image_urls and caps.get("supports_sequential", False):
            # Explicitly disable when references are present but no set is wanted.
            # Omitted on models without batch support — 5.0 Pro rejects the key
            # outright, even set to "disabled".
            payload["sequential_image_generation"] = "disabled"

        mode = (
            "layer-decomposition" if layer_decomposition
            else "sequential" if sequential
            else "edit/reference" if image_urls
            else "text-to-image"
        )
        logger.info(
            "[%s] generate | model=%s size=%s refs=%d mode=%s",
            cid, model_id, size, len(image_urls or []), mode,
        )

        resp = request_with_retry(
            f"{BASE_URL}/images/generations",
            method="POST",
            headers=self._auth_headers(),
            payload=payload,
            timeout=SUBMIT_TIMEOUT,
            correlation_id=cid,
        )

        images = [
            ImageResult(
                url=i.get("url"),
                b64_json=i.get("b64_json"),
                size=i.get("size"),
                output_format=i.get("output_format"),
                z_index=i.get("z_index"),
                name=i.get("name"),
                description=i.get("description"),
                bounding_box=i.get("bounding_box"),
            )
            for i in extract_images(resp)
        ]
        if not images:
            raise ValidationError(
                f"No images returned. Response keys: {list(resp.keys())}"
            )

        return GenerateResult(
            model=model_id,
            images=images,
            mode=mode,
            usage=resp.get("usage"),
            raw=resp if INCLUDE_RAW else {},
        )

    def generate_and_download(
        self,
        prompt: str,
        output_dir: str,
        *,
        prefix: str = "seedream",
        **kwargs: Any,
    ) -> GenerateResult:
        """generate() plus download every image URL to output_dir.

        Populates ImageResult.local_path for each saved file. b64_json responses
        are decoded and written too.

        Layer-decomposition results are named by z_index — `<prefix>-base.jpg`
        for the flattened composite and `<prefix>-layer1.png` upward — so the
        stack reassembles in filename order. Each file takes the extension the
        API reports for it: layers come back as PNG even when output_format is
        jpeg, because they carry an alpha channel.
        """
        result = self.generate(prompt, **kwargs)
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        default_ext = "jpg" if kwargs.get("output_format") == "jpeg" else "png"
        for idx, img in enumerate(result.images):
            ext = {"jpeg": "jpg", "png": "png"}.get(img.output_format or "", default_ext)
            if img.z_index is None:
                stem = f"{prefix}-{idx + 1}"
            elif img.is_base_image:
                stem = f"{prefix}-base"
            else:
                stem = f"{prefix}-layer{img.z_index}"
            dest = out / f"{stem}.{ext}"
            if img.url:
                self._download(img.url, dest)
                img.local_path = str(dest)
            elif img.b64_json:
                dest.write_bytes(base64.b64decode(img.b64_json))
                img.local_path = str(dest)
        return result

    @staticmethod
    def _download(url: str, dest: Path) -> None:
        from urllib import request as urllib_request
        with urllib_request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as resp:
            dest.write_bytes(resp.read())

    # ------------------------------------------------------------------
    # TOS object storage (upload local reference images)
    # ------------------------------------------------------------------

    def list_tos_buckets(self) -> list[dict[str, str]]:
        """List the buckets available to the configured TOS credentials."""
        return self._tos_client().list_buckets()

    def upload_to_tos(
        self,
        file_path: str,
        bucket: str = "",
        key: str = "",
        *,
        public: bool = True,
        content_type: str = "",
    ) -> TOSUploadResult:
        """Upload a local file to a TOS bucket and return its public URL."""
        bucket = bucket or TOS_DEFAULT_BUCKET
        if not bucket:
            raise ValidationError(
                "No TOS bucket specified. Pass bucket=... or set SEEDREAM_TOS_BUCKET. "
                "Call list_tos_buckets() to see available buckets."
            )

        path = Path(file_path).expanduser()
        if not path.is_file():
            raise ValidationError(f"File not found: {file_path}")

        data = path.read_bytes()
        if not data:
            raise ValidationError(f"File is empty: {file_path}")

        key = (key or path.name).lstrip("/")
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        tos = self._tos_client()
        url = tos.put_object(bucket, key, data, content_type=ctype, public=public)
        logger.info("[%s] Uploaded %s to TOS %s/%s", self._cid(), file_path, bucket, key)
        return TOSUploadResult(
            bucket=bucket,
            key=key,
            url=url,
            region=TOS_REGION,
            size=len(data),
            content_type=ctype,
        )

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    def list_models(self) -> dict[str, Any]:
        return {
            "default_model": DEFAULT_MODEL,
            "models": [
                {
                    "model_id": mid,
                    "label": caps["label"],
                    "alias": caps["alias"],
                    "sizes": caps["sizes"],
                    "default_size": caps["default_size"],
                    "max_reference_images": caps.get(
                        "max_reference_images", MAX_REFERENCE_IMAGES
                    ),
                    "features": {
                        "reference_images": caps.get("supports_reference_images", False),
                        "sequential": caps.get("supports_sequential", False),
                        "guidance_scale": caps.get("supports_guidance_scale", False),
                        "seed": caps.get("supports_seed", False),
                        "optimize_prompt": caps.get("supports_optimize_prompt", False),
                        "output_format": caps.get("supports_output_format", False),
                        "layer_decomposition": caps.get(
                            "supports_layer_decomposition", False
                        ),
                    },
                }
                for mid, caps in MODELS.items()
            ],
        }

    def ping(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "default_model": DEFAULT_MODEL,
            "base_url": BASE_URL,
            "credentials": credentials_configured(profile=self._profile),
            "tos": {
                "region": TOS_REGION,
                "endpoint": TOS_ENDPOINT,
                "default_bucket": TOS_DEFAULT_BUCKET,
            },
        }

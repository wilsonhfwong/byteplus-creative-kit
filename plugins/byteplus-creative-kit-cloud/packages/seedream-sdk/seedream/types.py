"""Typed result dataclasses returned by SeedreamClient methods."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageResult:
    """A single generated image, or one layer of a decomposed image.

    The layer fields are populated only by layer_decomposition responses:
    z_index orders the stack (0 is the flattened base image, 1..n the layers
    bottom-to-top), name/description say what was cut out, and bounding_box
    locates it in the source as {"absolute": [l, t, r, b], "normalized": [...]}
    with normalized coordinates on a 0–1000 scale.
    """
    url: str | None = None
    b64_json: str | None = None
    size: str | None = None
    local_path: str | None = None
    output_format: str | None = None
    z_index: int | None = None
    name: str | None = None
    description: str | None = None
    bounding_box: dict[str, Any] | None = None

    @property
    def is_base_image(self) -> bool:
        """True for the flattened composite the API returns alongside the layers."""
        return self.z_index == 0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.url:
            out["url"] = self.url
        if self.b64_json:
            out["b64_json"] = self.b64_json
        if self.size:
            out["size"] = self.size
        if self.local_path:
            out["local_path"] = self.local_path
        if self.output_format:
            out["output_format"] = self.output_format
        # z_index 0 identifies the base image — presence, not truthiness.
        if self.z_index is not None:
            out["z_index"] = self.z_index
        if self.name:
            out["name"] = self.name
        if self.description:
            out["description"] = self.description
        if self.bounding_box:
            out["bounding_box"] = self.bounding_box
        return out


@dataclass
class GenerateResult:
    """Result of a synchronous /images/generations call."""
    model: str
    images: list[ImageResult] = field(default_factory=list)
    mode: str = ""
    usage: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def urls(self) -> list[str]:
        return [img.url for img in self.images if img.url]

    @property
    def base_image(self) -> ImageResult | None:
        """The flattened composite from a layer_decomposition response, if any."""
        return next((img for img in self.images if img.is_base_image), None)

    @property
    def layers(self) -> list[ImageResult]:
        """Decomposed layers, bottom-to-top, excluding the base image.

        The API does not return layers in z_index order, so sort rather than
        trusting the response order.
        """
        return sorted(
            (img for img in self.images if img.z_index),
            key=lambda img: img.z_index or 0,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "model": self.model,
            "count": len(self.images),
            "images": [img.to_dict() for img in self.images],
        }
        if self.mode:
            out["mode"] = self.mode
        if self.usage:
            out["usage"] = self.usage
        return out


@dataclass
class TOSUploadResult:
    """Result of uploading a local file to a TOS bucket."""
    bucket: str
    key: str
    url: str
    region: str = ""
    size: int = 0
    content_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "bucket": self.bucket,
            "key": self.key,
            "url": self.url,
        }
        if self.region:
            out["region"] = self.region
        if self.size:
            out["size"] = self.size
        if self.content_type:
            out["content_type"] = self.content_type
        return out

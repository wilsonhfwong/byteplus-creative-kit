"""SDK-wide constants and model capability registry."""
from __future__ import annotations

import os
import re
from typing import Any

__version__ = "1.0.0"

# Image generation API (BytePlus ModelArk — synchronous /images/generations)
BASE_URL = os.getenv("SEEDREAM_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")
DEFAULT_MODEL = os.getenv("SEEDREAM_MODEL", "seedream-4-5-251128")

SUBMIT_TIMEOUT = int(os.getenv("SEEDREAM_SUBMIT_TIMEOUT", "600"))
DOWNLOAD_TIMEOUT = int(os.getenv("SEEDREAM_DOWNLOAD_TIMEOUT", "120"))
MAX_RETRIES = int(os.getenv("SEEDREAM_MAX_RETRIES", "3"))
INCLUDE_RAW = os.getenv("SEEDREAM_DEBUG_RAW", "").lower() in ("1", "true", "yes")

# Reference-image budget. The Seedream image-set rule is: input reference images
# plus generated images must total ≤ 15. We cap references conservatively; the
# combined-with-outputs check is enforced separately in the client.
MAX_REFERENCE_IMAGES = 14
MAX_SEQUENTIAL_IMAGES = 15
SIZE_WH_RE = re.compile(r"^\d{3,5}x\d{3,5}$")

# Model capability registry. Sizes list the named presets each model accepts;
# explicit WxH strings (e.g. "2048x2048") are also accepted for any model.
# The supports_* flags are enforced by the client, which rejects an unsupported
# parameter up front rather than letting the API return an opaque
# InvalidParameter — Seedream 5.0 Pro hard-errors on several of them.
MODELS: dict[str, dict[str, Any]] = {
    "seedream-4-5-251128": {
        "label": "Seedream 4.5",
        "alias": "4.5",
        "sizes": ["2K", "4K"],           # 4.5 does not support 1K
        "default_size": "2K",
        "supports_seed": True,
        "supports_guidance_scale": True,
        "supports_reference_images": True,
        "supports_sequential": True,
        "supports_optimize_prompt": True,
        "supports_output_format": False,
        "supports_layer_decomposition": False,
        "max_reference_images": MAX_REFERENCE_IMAGES,
    },
    "seedream-5-0-260128": {
        "label": "Seedream 5.0 Lite",
        "alias": "5.0-lite",
        "sizes": ["1K", "2K", "4K", "adaptive"],
        "default_size": "2K",
        "supports_seed": True,
        "supports_guidance_scale": True,
        "supports_reference_images": True,
        "supports_sequential": True,
        "supports_optimize_prompt": True,
        "supports_output_format": True,
        "supports_layer_decomposition": False,
        "max_reference_images": MAX_REFERENCE_IMAGES,
    },
    "dola-seedream-5-0-pro-260628": {
        "label": "Seedream 5.0 Pro",
        "alias": "5.0-pro",
        "sizes": ["1K", "2K"],           # 4K / adaptive are rejected by Pro
        "default_size": "2K",
        # seed is accepted by Pro but silently ignored, so it is not advertised.
        "supports_seed": False,
        "supports_guidance_scale": False,
        "supports_reference_images": True,
        "supports_sequential": False,
        "supports_optimize_prompt": True,
        # Pro takes {"mode": "standard"|"fast"}, not the {"enabled": true} the
        # older models take. Sending the wrong shape is an InvalidParameter.
        "optimize_prompt_shape": "mode",
        "supports_output_format": True,
        "supports_layer_decomposition": True,
        "max_reference_images": 10,
    },
}

# Friendly aliases → canonical model IDs (so callers can pass "4.5" / "5.0-lite").
MODEL_ALIASES: dict[str, str] = {
    "4.5": "seedream-4-5-251128",
    "4-5": "seedream-4-5-251128",
    "seedream-4.5": "seedream-4-5-251128",
    "5.0": "seedream-5-0-260128",
    "5-0": "seedream-5-0-260128",
    "5.0-lite": "seedream-5-0-260128",
    "5-0-lite": "seedream-5-0-260128",
    "lite": "seedream-5-0-260128",
    "seedream-5.0-lite": "seedream-5-0-260128",
    "5.0-pro": "dola-seedream-5-0-pro-260628",
    "5-0-pro": "dola-seedream-5-0-pro-260628",
    "pro": "dola-seedream-5-0-pro-260628",
    "seedream-5.0-pro": "dola-seedream-5-0-pro-260628",
    # BytePlus documents this as the public alias of the dola- prefixed ID.
    "seedream-5-0-pro-260628": "dola-seedream-5-0-pro-260628",
}

# Output container formats accepted by models that support `output_format`.
OUTPUT_FORMATS = ("png", "jpeg")


def resolve_model(model: str) -> str:
    """Map a friendly alias to a canonical model ID, or pass through an ID."""
    if not model:
        return DEFAULT_MODEL
    return MODEL_ALIASES.get(model.strip().lower(), model)


def model_caps(model: str) -> dict[str, Any]:
    return MODELS.get(model, MODELS[DEFAULT_MODEL])


# TOS object storage (HMAC-SHA256 / "TOS4" V4 signing, reuses ARK_AK / ARK_SK).
# Used to upload local reference images to a bucket and hand back a public URL
# that the image-generation API can fetch.
TOS_REGION = os.getenv("SEEDREAM_TOS_REGION", "ap-southeast-1")
TOS_ENDPOINT = os.getenv("SEEDREAM_TOS_ENDPOINT", f"tos-{TOS_REGION}.bytepluses.com")
TOS_SERVICE = "tos"
TOS_TIMEOUT = int(os.getenv("SEEDREAM_TOS_TIMEOUT", "120"))
TOS_DEFAULT_BUCKET = os.getenv("SEEDREAM_TOS_BUCKET", "")

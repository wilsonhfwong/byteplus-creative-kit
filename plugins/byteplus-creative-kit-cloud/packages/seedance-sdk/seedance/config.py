"""SDK-wide constants and model capability registry."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

__version__ = "2.1.0"

# Video generation API
BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3").rstrip("/")
DEFAULT_MODEL = "dreamina-seedance-2-5-260628"
LEGACY_MODEL = "dreamina-seedance-2-0-260128"
# No Seedance 2.5 "fast" variant exists; fast_mode always resolves to 2.0 fast.
FAST_MODEL = "dreamina-seedance-2-0-fast-260128"

# Task creation blocks while the API validates and fetches every reference
# URL, so a multi-video request can take well over a minute to acknowledge.
# Observed live: 3 reference videos exceeded 30s and orphaned a billed task.
SUBMIT_TIMEOUT = int(os.getenv("SEEDANCE_SUBMIT_TIMEOUT", "120"))
POLL_TIMEOUT = int(os.getenv("SEEDANCE_POLL_TIMEOUT", "15"))
MAX_RETRIES = int(os.getenv("SEEDANCE_MAX_RETRIES", "3"))
INCLUDE_RAW = os.getenv("SEEDANCE_DEBUG_RAW", "").lower() in ("1", "true", "yes")

TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
PAGE_SIZE_MAX = 50

# Multi-reference (all-round reference) budgets for Seedance 2.0.
# The create-task content[] array accepts image / video / audio reference items
# bound by their `role` field. Kept as module constants for backward
# compatibility; validation reads the per-model values from MODELS instead.
MAX_REFERENCE_IMAGES = 9
MAX_REFERENCE_VIDEOS = 3
MAX_REFERENCE_AUDIO = 3

# Sentinel meaning "let the model choose the duration within its range".
DURATION_AUTO = -1
# Sentinel meaning "caller did not specify a ratio" — resolved per task type.
RATIO_AUTO = "auto"

RATIOS_ALL = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"]

# Task types. Seedance 2.5 infers these from the prompt server-side; we track
# them locally only to validate ratio/duration constraints before submitting,
# turning asynchronous InvalidParameter.TaskTypeConstraint failures into
# synchronous ValidationErrors. Never sent in the request payload.
TASK_TYPE_AUTO = "auto"
TASK_TYPE_REFERENCE = "reference"
TASK_TYPE_EDIT = "edit"
TASK_TYPE_EXTEND = "extend"
TASK_TYPE_FIRST_FRAME = "first_frame"
TASK_TYPES: frozenset[str] = frozenset({
    TASK_TYPE_AUTO, TASK_TYPE_REFERENCE, TASK_TYPE_EDIT,
    TASK_TYPE_EXTEND, TASK_TYPE_FIRST_FRAME,
})

OUTPUT_FORMATS: frozenset[str] = frozenset({"mp4", "mov"})

# ---------------------------------------------------------------------------
# Task-intent detection
# ---------------------------------------------------------------------------
# When content.role is reference_*, Seedance 2.5 decides between reference-to-
# video, video editing, and video extension by reading the PROMPT. That decision
# happens after the task is queued, so a parameter clash is only reported once
# the task has been consumed — minutes later.
#
# We mirror the documented trigger words locally to catch the clash up front.
# The docs give these lists as "such as", so they are illustrative rather than
# exhaustive; near-synonyms and the Chinese equivalents are included because the
# model reads intent, not a fixed vocabulary. Detection is advisory: it only ever
# produces an error when the caller ALSO passed parameters the detected task type
# forbids, so a false positive on a compatible request costs nothing.
#
# Docs: https://docs.byteplus.com/en/docs/ModelArk/2607688#2.5_param_constraints

# "edit the video, add, delete/remove, or modify/replace/change"
EDIT_TRIGGER_PATTERNS: tuple[str, ...] = (
    r"\bedit(s|ed|ing)?\b",
    r"\badd(s|ed|ing)?\b",
    r"\bdelete(s|d|ing)?\b",
    r"\bremove(s|d|ing)?\b",
    r"\bmodif(y|ies|ied|ying)\b",
    r"\breplace(s|d|ing)?\b",
    r"\bchange(s|d|ing)?\b",
    r"\bswap(s|ped|ping)?\b",
    r"\bredraw(s|n|ing)?\b",
    r"\brepair(s|ed|ing)?\b",
    r"\berase(s|d|ing)?\b",
    r"编辑|添加|删除|移除|修改|替换|更换|重绘|修复",
)

# "extend forward/backward, continue, or continue the story"
EXTEND_TRIGGER_PATTERNS: tuple[str, ...] = (
    r"\bextend(s|ed|ing)?\b",
    r"\bextension\b",
    r"\bcontinue(s|d)?\b",
    r"\bcontinuing\b",
    r"\bcontinuation\b",
    r"\bprolong(s|ed|ing)?\b",
    r"延长|续写|扩展|继续|延续",
)

_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Extension first: its verbs are more specific, so "extend @Video1 and add a
    # bird" reads as an extension rather than an edit.
    (TASK_TYPE_EXTEND, EXTEND_TRIGGER_PATTERNS),
    (TASK_TYPE_EDIT, EDIT_TRIGGER_PATTERNS),
)


def detect_task_intent(prompt: str) -> list[tuple[str, str]]:
    """Return [(task_type, matched_phrase), ...] for intents the prompt implies.

    Both can match at once ("extend @Video1, then remove the crowd"); the caller
    decides what to do with an ambiguous result rather than us guessing.
    """
    import re

    found: list[tuple[str, str]] = []
    for task_type, patterns in _TRIGGERS:
        for pattern in patterns:
            m = re.search(pattern, prompt, re.IGNORECASE)
            if m:
                found.append((task_type, m.group(0)))
                break
    return found

MODELS: dict[str, dict[str, Any]] = {
    "dreamina-seedance-2-5-260628": {
        "label": "Seedance 2.5",
        "alias": "2.5",
        "resolutions": ["480p", "720p"],
        "ratios": RATIOS_ALL,
        "duration_range": [4, 30],
        "supports_first_frame": True,
        "supports_last_frame": True,
        "supports_camerafixed": True,
        "supports_seed": True,
        "supports_duration_auto": True,
        "supports_output_format": True,
        "supports_audio_only": True,
        "max_reference_images": 30,
        "max_reference_videos": 10,
        "max_reference_audio": 10,
        # Per-clip and aggregate limits on reference media, in seconds. Not
        # enforced client-side (we do not probe media); documented for callers.
        "max_reference_media_seconds": 30,
        "max_reference_media_total_seconds": 30,
        # Task types whose output ratio is locked to the source material and
        # therefore only accept ratio="adaptive".
        "adaptive_only_task_types": [
            TASK_TYPE_FIRST_FRAME, TASK_TYPE_EDIT, TASK_TYPE_EXTEND,
        ],
        # Task types whose output duration is locked to the source material and
        # therefore only accept duration=-1.
        "auto_duration_only_task_types": [TASK_TYPE_EDIT],
    },
    "dreamina-seedance-2-0-260128": {
        "label": "Seedance 2.0 Standard",
        "alias": "2.0",
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": RATIOS_ALL,
        "duration_range": [4, 15],
        "supports_first_frame": True,
        "supports_last_frame": False,
        "supports_camerafixed": True,
        "supports_seed": True,
        "supports_duration_auto": True,
        "supports_output_format": False,
        "supports_audio_only": False,
        "max_reference_images": MAX_REFERENCE_IMAGES,
        "max_reference_videos": MAX_REFERENCE_VIDEOS,
        "max_reference_audio": MAX_REFERENCE_AUDIO,
        "max_reference_media_seconds": 15,
        "max_reference_media_total_seconds": 15,
        "adaptive_only_task_types": [],
        "auto_duration_only_task_types": [],
    },
    "dreamina-seedance-2-0-fast-260128": {
        "label": "Seedance 2.0 Fast",
        "alias": "2.0-fast",
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": RATIOS_ALL,
        "duration_range": [4, 15],
        "supports_first_frame": True,
        "supports_last_frame": False,
        "supports_camerafixed": True,
        "supports_seed": True,
        "supports_duration_auto": True,
        "supports_output_format": False,
        "supports_audio_only": False,
        "max_reference_images": MAX_REFERENCE_IMAGES,
        "max_reference_videos": MAX_REFERENCE_VIDEOS,
        "max_reference_audio": MAX_REFERENCE_AUDIO,
        "max_reference_media_seconds": 15,
        "max_reference_media_total_seconds": 15,
        "adaptive_only_task_types": [],
        "auto_duration_only_task_types": [],
    },
}

# Short names accepted wherever a model is selected (CLI --model, SDK model=).
MODEL_ALIASES: dict[str, str] = {
    "2.5": "dreamina-seedance-2-5-260628",
    "2-5": "dreamina-seedance-2-5-260628",
    "seedance-2.5": "dreamina-seedance-2-5-260628",
    "2.0": "dreamina-seedance-2-0-260128",
    "2-0": "dreamina-seedance-2-0-260128",
    "standard": "dreamina-seedance-2-0-260128",
    "seedance-2.0": "dreamina-seedance-2-0-260128",
    "2.0-fast": "dreamina-seedance-2-0-fast-260128",
    "2-0-fast": "dreamina-seedance-2-0-fast-260128",
    "fast": "dreamina-seedance-2-0-fast-260128",
}


def resolve_model(model: str) -> str:
    """Map an alias ('2.5', 'fast') or a full model ID to a full model ID.

    Unknown values are returned unchanged so a newly released model ID can be
    passed through without an SDK upgrade; capability lookups then fall back to
    the default model's caps.
    """
    if not model:
        return DEFAULT_MODEL
    return MODEL_ALIASES.get(model.strip().lower(), model)


def model_caps(model: str) -> dict[str, Any]:
    return MODELS.get(model, MODELS[DEFAULT_MODEL])


def is_seedance_25(model: str) -> bool:
    return resolve_model(model) == "dreamina-seedance-2-5-260628"


# Asset library API (HMAC-SHA256 AK/SK auth)
# Host matches the byteplus-go-sdk-v2 default endpoint (open.* prefix, not ark.*)
ASSET_HOST = os.getenv("SEEDANCE_ASSET_HOST", "ark.ap-southeast-1.byteplusapi.com")
ASSET_CONTENT_TYPE = "application/json; charset=utf-8"
ASSET_SERVICE = "ark"
ASSET_REGION = "ap-southeast-1"
ASSET_VERSION = "2024-01-01"
ASSET_POLL_INTERVAL = int(os.getenv("SEEDANCE_ASSET_POLL_INTERVAL", "10"))
ASSET_POLL_TIMEOUT = int(os.getenv("SEEDANCE_ASSET_POLL_TIMEOUT", "120"))


# TOS object storage (HMAC-SHA256 / "TOS4" V4 signing, reuses ARK_AK / ARK_SK)
# Used to upload local images to a bucket and hand back a public URL that the
# generation / asset-library APIs can fetch. Region matches the asset API.
TOS_REGION = os.getenv("SEEDANCE_TOS_REGION", "ap-southeast-1")
# Service endpoint (ListBuckets). Object requests use the virtual-hosted form
# {bucket}.{TOS_ENDPOINT}. Override the whole host with SEEDANCE_TOS_ENDPOINT.
TOS_ENDPOINT = os.getenv("SEEDANCE_TOS_ENDPOINT", f"tos-{TOS_REGION}.bytepluses.com")
TOS_SERVICE = "tos"
TOS_TIMEOUT = int(os.getenv("SEEDANCE_TOS_TIMEOUT", "120"))
# Default bucket — optional. When set, uploads use it unless overridden, so the
# caller need not be asked which bucket every time.
TOS_DEFAULT_BUCKET = os.getenv("SEEDANCE_TOS_BUCKET", "")


# AI MediaKit video-enhancement API (Bearer auth, separate host + API key)
# Docs: https://docs.byteplus.com/en/docs/byteplus-vod/ai-mediakit-create-a-video-enhancement-task
MEDIAKIT_BASE_URL = os.getenv(
    "SEEDANCE_MEDIAKIT_BASE_URL",
    "https://mediakit.ap-southeast-1.bytepluses.com/api/v1",
)
MEDIAKIT_TOOL_VERSIONS = frozenset({"standard", "professional"})
MEDIAKIT_SCENES = frozenset({"common", "ugc", "short_series", "aigc", "old_film"})
MEDIAKIT_RESOLUTIONS = frozenset({"240p", "360p", "480p", "540p", "720p", "1080p", "2k", "4k"})
MEDIAKIT_BITRATE_LEVELS = frozenset({"low", "medium", "high"})
MEDIAKIT_RESOLUTION_LIMIT_RANGE = (128, 2160)
MEDIAKIT_FPS_RANGE = (15, 120)
MEDIAKIT_CLIENT_TOKEN_MAXLEN = 64
# In-progress statuses vary across docs (running / processing); terminal is fixed.
MEDIAKIT_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})

# Local idempotency cache (token -> task_id); TTL matches the server's 24h dedup window.
MEDIAKIT_CACHE_PATH = Path.home() / ".seedance" / "upscale_cache.json"
MEDIAKIT_CACHE_TTL = int(os.getenv("SEEDANCE_MEDIAKIT_CACHE_TTL", str(24 * 3600)))

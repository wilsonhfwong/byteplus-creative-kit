"""Environment-only cloud configuration. No browser, profiles or secret files."""
from __future__ import annotations
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ.get("BYTEPLUS_CREATIVE_WORKSPACE", "/workspace")).resolve()
DATA_DIR = Path(os.environ.get("BYTEPLUS_CREATIVE_DATA_DIR") or WORKSPACE / ".byteplus-creative-kit").resolve()
OUTPUT_DIR = Path(os.environ.get("BYTEPLUS_CREATIVE_OUTPUT_DIR") or WORKSPACE / "output" / "byteplus-creative-kit").resolve()
SETTINGS_PATH = DATA_DIR / "unused-settings.json"  # compatibility only; never read
DEFAULTS = {
    "ark_base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
    "project": "default", "tos_region": "ap-southeast-1",
    "tos_endpoint": "tos-ap-southeast-1.bytepluses.com",
    "presign_seconds": 86400, "seed_model": "",
    "seedream_model": "seedream-4-5-251128",
}
ENV_FIELDS = {
    "ARK_API_KEY": "api_key", "ARK_AK": "access_key", "ARK_SK": "secret_key",
    "ARK_SESSION_TOKEN": "session_token", "ARK_BASE_URL": "ark_base_url",
    "SEEDANCE_PROJECT_NAME": "project", "SEEDANCE_TOS_BUCKET": "tos_bucket",
    "SEEDANCE_TOS_REGION": "tos_region", "SEEDANCE_TOS_ENDPOINT": "tos_endpoint",
    "BYTEPLUS_TOS_AK": "tos_access_key", "BYTEPLUS_TOS_SK": "tos_secret_key",
    "BYTEPLUS_TOS_SESSION_TOKEN": "tos_session_token",
    "BYTEPLUS_SEED_MODEL": "seed_model", "SEEDREAM_MODEL": "seedream_model",
}


def load_settings(path=None) -> dict:
    if path is not None:
        raise ValueError("Cloud credentials must be configured as environment secrets, not a settings file.")
    return {**DEFAULTS, **{field: os.environ[env] for env, field in ENV_FIELDS.items() if env in os.environ}}


def configure_environment(settings: dict) -> None:
    for env, field in ENV_FIELDS.items():
        if env in {"BYTEPLUS_TOS_AK", "BYTEPLUS_TOS_SK", "BYTEPLUS_TOS_SESSION_TOKEN", "BYTEPLUS_SEED_MODEL"}:
            continue
        os.environ[env] = str(settings.get(field, ""))
    os.environ["SEED_KIT_ISOLATED"] = "1"
    os.environ["MCP_TRANSPORT"] = "stdio"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["SEEDANCE_ASSET_HOST"] = "ark.ap-southeast-1.byteplusapi.com"
    os.environ["SEEDREAM_BASE_URL"] = settings["ark_base_url"].rstrip("/")
    os.environ["SEEDANCE_DEBUG_RAW"] = "0"
    os.environ["SEEDREAM_DEBUG_RAW"] = "0"
    os.environ.pop("BYTEPLUS_API_KEY", None)
    os.environ.pop("MEDIAKIT_API_KEY", None)


def redact(message: str, settings: dict) -> str:
    for name in ("api_key", "access_key", "secret_key", "session_token", "tos_access_key", "tos_secret_key", "tos_session_token"):
        value = str(settings.get(name, ""))
        if value:
            message = message.replace(value, "[redacted]")
    return re.sub(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]+", r"\1?[redacted]", message)

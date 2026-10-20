"""Project-local configuration. No credentials are embedded in Codex config."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BYTEPLUS_CREATIVE_DATA_DIR") or ROOT / ".runtime")
SETTINGS_PATH = DATA_DIR / "settings.json"
OUTPUT_DIR = Path(os.environ.get("BYTEPLUS_CREATIVE_OUTPUT_DIR") or Path.home() / "Downloads" / "BytePlus Creative Kit")

DEFAULTS = {
    "ark_base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
    "project": "default",
    "tos_region": "ap-southeast-1",
    "tos_endpoint": "tos-ap-southeast-1.bytepluses.com",
    "presign_seconds": 86400,
    "seed_model": "",
}


def load_settings(path: Path | None = None) -> dict:
    target = path or SETTINGS_PATH
    if not target.is_file():
        raise RuntimeError("Open creative_kit_setup and configure your BytePlus credentials in the local browser page.")
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Settings must contain a JSON object. Open creative_kit_setup to configure the plugin.")
    return {**DEFAULTS, **data}


def configure_environment(settings: dict) -> None:
    """Select this kit's account explicitly, without using personal SDK profiles."""
    mapping = {
        "ARK_API_KEY": "api_key", "ARK_AK": "access_key", "ARK_SK": "secret_key",
        "ARK_SESSION_TOKEN": "session_token", "ARK_BASE_URL": "ark_base_url",
        "SEEDANCE_PROJECT_NAME": "project", "SEEDANCE_TOS_BUCKET": "tos_bucket",
        "SEEDANCE_TOS_REGION": "tos_region", "SEEDANCE_TOS_ENDPOINT": "tos_endpoint",
    }
    for env_name, field in mapping.items():
        os.environ[env_name] = str(settings.get(field, ""))
    os.environ["SEED_KIT_ISOLATED"] = "1"
    os.environ["MCP_TRANSPORT"] = "stdio"
    os.environ["SEEDANCE_ASSET_HOST"] = "ark.ap-southeast-1.byteplusapi.com"
    # Do not let an unrelated .env in a parent directory select another account.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["SEEDREAM_BASE_URL"] = settings["ark_base_url"].rstrip("/")
    os.environ["SEEDREAM_MODEL"] = "seedream-4-5-251128"
    os.environ["SEEDANCE_DEBUG_RAW"] = "0"
    os.environ["SEEDREAM_DEBUG_RAW"] = "0"
    os.environ.pop("BYTEPLUS_API_KEY", None)
    os.environ.pop("MEDIAKIT_API_KEY", None)


def redact(message: str, settings: dict) -> str:
    for name in ("api_key", "access_key", "secret_key", "session_token", "tos_access_key", "tos_secret_key", "tos_session_token"):
        value = str(settings.get(name, ""))
        if value:
            message = message.replace(value, "[redacted]")
    # SDK failures can embed signed URLs. Keep the host/path, remove query grants.
    import re
    return re.sub(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]+", r"\1?[redacted]", message)

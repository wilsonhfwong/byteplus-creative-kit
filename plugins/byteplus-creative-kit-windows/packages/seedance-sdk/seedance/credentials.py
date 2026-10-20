"""Credential loading with a priority chain.

Resolution order (first non-empty value wins):
  1. Explicit constructor arguments
  2. Environment variables  (ARK_API_KEY, ARK_AK, ARK_SK)
  3. ~/.seedance/credentials  INI file  [default] section
  4. .env file in CWD  (loaded only when python-dotenv is installed)
  5. Legacy ark_api_key.txt  next to the calling module  (backwards compat)
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path

from .exceptions import AuthError

CREDENTIALS_PATH = Path.home() / ".seedance" / "credentials"
CONFIG_PATH = Path.home() / ".seedance" / "config"


def _load_dotenv() -> None:
    if os.getenv("SEED_KIT_ISOLATED") == "1":
        return
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _read_ini(path: Path, section: str, key: str) -> str:
    if os.getenv("SEED_KIT_ISOLATED") == "1" or not path.exists():
        return ""
    parser = configparser.ConfigParser()
    parser.read(path)
    return parser.get(section, key, fallback="").strip()


def load_api_key(
    explicit: str | None = None,
    *,
    profile: str = "default",
) -> str:
    """Return the ModelArk API key, or raise AuthError."""
    _load_dotenv()

    value = (
        (explicit or "").strip()
        or os.getenv("ARK_API_KEY", "").strip()
        or _read_ini(CREDENTIALS_PATH, profile, "ark_api_key")
    )

    # Legacy fallback: ark_api_key.txt placed next to the old server.py
    if not value and os.getenv("SEED_KIT_ISOLATED") != "1":
        legacy = Path(__file__).parent / "ark_api_key.txt"
        if legacy.exists():
            value = legacy.read_text().strip()

    if not value:
        raise AuthError(
            "ARK_API_KEY is not configured.\n"
            "Set it via one of:\n"
            "  export ARK_API_KEY=<key>\n"
            "  seedance auth login\n"
            "  echo '[default]\\nark_api_key=<key>' > ~/.seedance/credentials"
        )
    return value


def load_mediakit_api_key(
    explicit: str | None = None,
    *,
    profile: str = "default",
) -> str:
    """Return the AI MediaKit API key, or raise AuthError.

    This is a *separate* credential from ARK_API_KEY — created in the AI MediaKit
    console — so there is no fallback to the ModelArk key.
    """
    _load_dotenv()

    value = (
        (explicit or "").strip()
        or os.getenv("MEDIAKIT_API_KEY", "").strip()
        or _read_ini(CREDENTIALS_PATH, profile, "mediakit_api_key")
    )

    if not value:
        raise AuthError(
            "MEDIAKIT_API_KEY is not configured.\n"
            "This is required for video upscaling (AI MediaKit) and is separate from "
            "ARK_API_KEY. Create one in the AI MediaKit console, then set it via one of:\n"
            "  export MEDIAKIT_API_KEY=<key>\n"
            "  seedance auth login\n"
            "  echo '[default]\\nmediakit_api_key=<key>' >> ~/.seedance/credentials"
        )
    return value


def load_asset_credentials(
    explicit_ak: str | None = None,
    explicit_sk: str | None = None,
    *,
    profile: str = "default",
) -> tuple[str, str]:
    """Return (ak, sk) for the asset library, or raise AuthError."""
    _load_dotenv()

    ak = (
        (explicit_ak or "").strip()
        or os.getenv("ARK_AK", "").strip()
        or _read_ini(CREDENTIALS_PATH, profile, "ark_ak")
    )
    sk = (
        (explicit_sk or "").strip()
        or os.getenv("ARK_SK", "").strip()
        or _read_ini(CREDENTIALS_PATH, profile, "ark_sk")
    )

    if not ak or not sk:
        missing = []
        if not ak:
            missing.append("ark_ak (ARK_AK)")
        if not sk:
            missing.append("ark_sk (ARK_SK)")
        raise AuthError(
            f"Asset library credentials missing: {', '.join(missing)}.\n"
            "Run 'seedance auth login' or set ARK_AK / ARK_SK environment variables."
        )
    return ak, sk


def write_credentials(
    api_key: str,
    ak: str,
    sk: str,
    *,
    mediakit_api_key: str = "",
    profile: str = "default",
) -> None:
    """Persist credentials to ~/.seedance/credentials."""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)

    parser = configparser.ConfigParser()
    if CREDENTIALS_PATH.exists():
        parser.read(CREDENTIALS_PATH)

    if not parser.has_section(profile):
        parser.add_section(profile)

    parser.set(profile, "ark_api_key", api_key)
    parser.set(profile, "ark_ak", ak)
    parser.set(profile, "ark_sk", sk)
    if mediakit_api_key:
        parser.set(profile, "mediakit_api_key", mediakit_api_key)

    with CREDENTIALS_PATH.open("w") as f:
        parser.write(f)

    # Restrict permissions — credentials file should not be world-readable
    CREDENTIALS_PATH.chmod(0o600)


def clear_credentials(*, profile: str = "default") -> bool:
    """Remove a profile from ~/.seedance/credentials. Returns True if file existed."""
    if not CREDENTIALS_PATH.exists():
        return False

    parser = configparser.ConfigParser()
    parser.read(CREDENTIALS_PATH)

    if parser.has_section(profile):
        parser.remove_section(profile)
        with CREDENTIALS_PATH.open("w") as f:
            parser.write(f)

    return True


def credentials_configured(*, profile: str = "default") -> dict[str, bool]:
    """Return which credentials are available (for `seedance auth check`)."""
    _load_dotenv()
    return {
        "api_key": bool(
            os.getenv("ARK_API_KEY", "").strip()
            or _read_ini(CREDENTIALS_PATH, profile, "ark_api_key")
        ),
        "ak": bool(
            os.getenv("ARK_AK", "").strip()
            or _read_ini(CREDENTIALS_PATH, profile, "ark_ak")
        ),
        "sk": bool(
            os.getenv("ARK_SK", "").strip()
            or _read_ini(CREDENTIALS_PATH, profile, "ark_sk")
        ),
        "mediakit": bool(
            os.getenv("MEDIAKIT_API_KEY", "").strip()
            or _read_ini(CREDENTIALS_PATH, profile, "mediakit_api_key")
        ),
    }

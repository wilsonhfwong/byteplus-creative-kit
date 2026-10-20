"""Credential loading with a priority chain.

Resolution order (first non-empty value wins):
  1. Explicit constructor arguments
  2. Environment variables  (ARK_API_KEY, ARK_AK, ARK_SK)
  3. ~/.seedream/credentials  INI file  [default] section
  4. .env file in CWD  (loaded only when python-dotenv is installed)

Only ARK_API_KEY is required for image generation. ARK_AK / ARK_SK are needed
only for the TOS tools (uploading local reference images to get a public URL).
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path

from .exceptions import AuthError

CREDENTIALS_PATH = Path.home() / ".seedream" / "credentials"


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
    """Return the ModelArk API key, or raise AuthError.

    Accepts either ARK_API_KEY (canonical) or BYTEPLUS_API_KEY (used by some
    existing Seedream tooling) as the environment variable name.
    """
    _load_dotenv()

    value = (
        (explicit or "").strip()
        or os.getenv("ARK_API_KEY", "").strip()
        or os.getenv("BYTEPLUS_API_KEY", "").strip()
        or _read_ini(CREDENTIALS_PATH, profile, "ark_api_key")
    )

    if not value:
        raise AuthError(
            "ARK_API_KEY is not configured.\n"
            "Set it via one of:\n"
            "  export ARK_API_KEY=<key>\n"
            "  seedream auth login\n"
            "  echo '[default]\\nark_api_key=<key>' > ~/.seedream/credentials"
        )
    return value


def load_asset_credentials(
    explicit_ak: str | None = None,
    explicit_sk: str | None = None,
    *,
    profile: str = "default",
) -> tuple[str, str]:
    """Return (ak, sk) for TOS object storage, or raise AuthError."""
    _load_dotenv()

    ak = (
        (explicit_ak or "").strip()
        or os.getenv("ARK_AK", "").strip()
        or os.getenv("TOS_ACCESS_KEY", "").strip()
        or _read_ini(CREDENTIALS_PATH, profile, "ark_ak")
    )
    sk = (
        (explicit_sk or "").strip()
        or os.getenv("ARK_SK", "").strip()
        or os.getenv("TOS_SECRET_KEY", "").strip()
        or _read_ini(CREDENTIALS_PATH, profile, "ark_sk")
    )

    if not ak or not sk:
        missing = []
        if not ak:
            missing.append("ark_ak (ARK_AK)")
        if not sk:
            missing.append("ark_sk (ARK_SK)")
        raise AuthError(
            f"TOS credentials missing: {', '.join(missing)}.\n"
            "These are only needed to upload local reference images. "
            "Run 'seedream auth login' or set ARK_AK / ARK_SK environment variables."
        )
    return ak, sk


def write_credentials(
    api_key: str,
    ak: str = "",
    sk: str = "",
    *,
    profile: str = "default",
) -> None:
    """Persist credentials to ~/.seedream/credentials."""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)

    parser = configparser.ConfigParser()
    if CREDENTIALS_PATH.exists():
        parser.read(CREDENTIALS_PATH)

    if not parser.has_section(profile):
        parser.add_section(profile)

    parser.set(profile, "ark_api_key", api_key)
    if ak:
        parser.set(profile, "ark_ak", ak)
    if sk:
        parser.set(profile, "ark_sk", sk)

    with CREDENTIALS_PATH.open("w") as f:
        parser.write(f)

    # Restrict permissions — credentials file should not be world-readable
    CREDENTIALS_PATH.chmod(0o600)


def clear_credentials(*, profile: str = "default") -> bool:
    """Remove a profile from ~/.seedream/credentials. Returns True if file existed."""
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
    """Return which credentials are available (for `seedream auth check`)."""
    _load_dotenv()
    return {
        "api_key": bool(
            os.getenv("ARK_API_KEY", "").strip()
            or os.getenv("BYTEPLUS_API_KEY", "").strip()
            or _read_ini(CREDENTIALS_PATH, profile, "ark_api_key")
        ),
        "ak": bool(
            os.getenv("ARK_AK", "").strip()
            or os.getenv("TOS_ACCESS_KEY", "").strip()
            or _read_ini(CREDENTIALS_PATH, profile, "ark_ak")
        ),
        "sk": bool(
            os.getenv("ARK_SK", "").strip()
            or os.getenv("TOS_SECRET_KEY", "").strip()
            or _read_ini(CREDENTIALS_PATH, profile, "ark_sk")
        ),
    }

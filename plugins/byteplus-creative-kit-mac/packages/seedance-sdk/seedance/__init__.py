"""Seedance SDK — BytePlus Seedance video generation (2.5 default, 2.0 supported)."""
from .client import SeedanceClient
from .config import (
    DEFAULT_MODEL,
    DURATION_AUTO,
    FAST_MODEL,
    LEGACY_MODEL,
    RATIO_AUTO,
    __version__,
)
from .exceptions import (
    APIError,
    AssetError,
    AuthError,
    SeedanceError,
    StorageError,
    SubmitTimeoutError,
    TaskTypeConstraintError,
    ValidationError,
)
from .types import (
    AssetGroupResult,
    AssetResult,
    GenerateResult,
    TaskResult,
    TOSUploadResult,
    UpscaleResult,
)

__all__ = [
    "SeedanceClient",
    "__version__",
    # Model selection
    "DEFAULT_MODEL",
    "FAST_MODEL",
    "LEGACY_MODEL",
    "DURATION_AUTO",
    "RATIO_AUTO",
    # Exceptions
    "SeedanceError",
    "AuthError",
    "ValidationError",
    "APIError",
    "TaskTypeConstraintError",
    "SubmitTimeoutError",
    "AssetError",
    "StorageError",
    # Result types
    "TaskResult",
    "GenerateResult",
    "AssetGroupResult",
    "AssetResult",
    "TOSUploadResult",
    "UpscaleResult",
]

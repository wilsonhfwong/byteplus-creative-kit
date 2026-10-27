"""Typed exceptions for the Seedance SDK."""
from __future__ import annotations


class SeedanceError(Exception):
    """Base exception for all Seedance SDK errors."""


class AuthError(SeedanceError):
    """Raised when credentials are missing or invalid."""


class ValidationError(SeedanceError):
    """Raised when request parameters fail validation."""


class APIError(SeedanceError):
    """Raised when the BytePlus API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SubmitTimeoutError(APIError):
    """Raised when a task-creation request times out while reading the response.

    The POST usually reached the server, so a task may exist and be billed even
    though no task_id came back. Never retried: the endpoint is not idempotent,
    so a retry would create a second task.
    """


class TaskTypeConstraintError(APIError):
    """Raised for InvalidParameter.TaskTypeConstraint (Seedance 2.5).

    The request parameters are incompatible with the task type the model
    inferred from the prompt — e.g. a specific ratio on a video-edit task,
    which must be 'adaptive'. The API returns this synchronously for some
    cases and asynchronously (on the failed task) for prompt-inferred ones.

    `issues` holds the parsed per-violation detail lines when available.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        issues: list[str] | None = None,
    ) -> None:
        super().__init__(message, status_code)
        self.issues = issues or []


class AssetError(SeedanceError):
    """Raised when an asset library operation fails."""


class StorageError(SeedanceError):
    """Raised when a TOS object-storage operation fails."""


class TimeoutError(SeedanceError):
    """Raised when polling exceeds the configured deadline."""

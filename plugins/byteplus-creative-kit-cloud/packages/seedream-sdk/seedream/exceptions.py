"""Typed exceptions for the Seedream SDK."""
from __future__ import annotations


class SeedreamError(Exception):
    """Base exception for all Seedream SDK errors."""


class AuthError(SeedreamError):
    """Raised when credentials are missing or invalid."""


class ValidationError(SeedreamError):
    """Raised when request parameters fail validation."""


class APIError(SeedreamError):
    """Raised when the BytePlus API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StorageError(SeedreamError):
    """Raised when a TOS object-storage operation fails."""

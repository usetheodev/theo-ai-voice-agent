"""Exceptions for provider system."""


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, message: str, provider: str = "unknown"):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class ProviderConnectionError(ProviderError):
    """Failed to connect to provider API."""
    pass


class ProviderTimeoutError(ProviderError):
    """Request to provider timed out."""
    pass


class ProviderAuthError(ProviderError):
    """Authentication failed (invalid API key)."""
    pass


class ProviderRateLimitError(ProviderError):
    """Rate limit exceeded."""

    def __init__(self, message: str, provider: str = "unknown", retry_after: float = 0):
        self.retry_after = retry_after
        super().__init__(message, provider)


class ProviderNotFoundError(ProviderError):
    """Provider not found in registry."""
    pass


class ProviderConfigError(ProviderError):
    """Invalid provider configuration."""
    pass

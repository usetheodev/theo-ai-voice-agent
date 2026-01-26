"""
Provider Registry for Voice Pipeline.

Central registry for discovering and instantiating voice providers
(ASR, LLM, TTS, VAD).
"""

import threading
from typing import Any, Optional, TypeVar

from voice_pipeline.interfaces import (
    ASRInterface,
    LLMInterface,
    TTSInterface,
    VADInterface,
)
from voice_pipeline.providers.types import (
    ASRCapabilities,
    Capabilities,
    LLMCapabilities,
    ProviderInfo,
    ProviderType,
    TTSCapabilities,
    VADCapabilities,
)

# Type variable for provider interfaces
T = TypeVar("T", ASRInterface, LLMInterface, TTSInterface, VADInterface)


class ProviderRegistry:
    """
    Central registry for voice pipeline providers.

    This is a singleton that manages registration and discovery of
    ASR, LLM, TTS, and VAD providers.

    Usage:
        >>> registry = get_registry()
        >>> registry.register_asr("whisper", WhisperASR, capabilities=...)
        >>> asr = registry.get_asr("whisper", model="base")

        >>> # List available providers
        >>> print(registry.list_providers("asr"))
        ['whisper', 'deepgram', ...]

    The registry supports:
    - Manual registration via register_* methods
    - Decorator-based registration via @register_asr, etc.
    - Auto-discovery via entry_points (pip install voice-community-*)
    """

    _instance: Optional["ProviderRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ProviderRegistry":
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the registry."""
        if self._initialized:
            return

        self._providers: dict[ProviderType, dict[str, ProviderInfo]] = {
            ProviderType.ASR: {},
            ProviderType.LLM: {},
            ProviderType.TTS: {},
            ProviderType.VAD: {},
        }
        self._aliases: dict[ProviderType, dict[str, str]] = {
            ProviderType.ASR: {},
            ProviderType.LLM: {},
            ProviderType.TTS: {},
            ProviderType.VAD: {},
        }
        self._initialized = True
        self._auto_discovered = False

    def reset(self) -> None:
        """Reset the registry to empty state. Useful for testing."""
        self._providers = {
            ProviderType.ASR: {},
            ProviderType.LLM: {},
            ProviderType.TTS: {},
            ProviderType.VAD: {},
        }
        self._aliases = {
            ProviderType.ASR: {},
            ProviderType.LLM: {},
            ProviderType.TTS: {},
            ProviderType.VAD: {},
        }
        self._auto_discovered = False

    # ==================== Registration ====================

    def register(
        self,
        name: str,
        provider_type: ProviderType,
        provider_class: type,
        capabilities: Capabilities,
        description: str = "",
        version: str = "1.0.0",
        author: str = "",
        config_schema: Optional[dict[str, Any]] = None,
        default_config: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        aliases: Optional[list[str]] = None,
    ) -> None:
        """
        Register a provider in the registry.

        Args:
            name: Unique name for the provider.
            provider_type: Type of provider (ASR, LLM, TTS, VAD).
            provider_class: The class to instantiate.
            capabilities: Provider capabilities.
            description: Human-readable description.
            version: Provider version.
            author: Provider author.
            config_schema: JSON schema for configuration.
            default_config: Default configuration values.
            tags: Tags for categorization.
            aliases: Alternative names for this provider.
        """
        info = ProviderInfo(
            name=name,
            provider_type=provider_type,
            provider_class=provider_class,
            capabilities=capabilities,
            description=description,
            version=version,
            author=author,
            config_schema=config_schema,
            default_config=default_config or {},
            tags=tags or [],
        )

        self._providers[provider_type][name] = info

        # Register aliases
        if aliases:
            for alias in aliases:
                self._aliases[provider_type][alias] = name

    def register_asr(
        self,
        name: str,
        provider_class: type[ASRInterface],
        capabilities: Optional[ASRCapabilities] = None,
        **kwargs,
    ) -> None:
        """Register an ASR provider."""
        caps = capabilities or ASRCapabilities()
        self.register(
            name=name,
            provider_type=ProviderType.ASR,
            provider_class=provider_class,
            capabilities=caps,
            **kwargs,
        )

    def register_llm(
        self,
        name: str,
        provider_class: type[LLMInterface],
        capabilities: Optional[LLMCapabilities] = None,
        **kwargs,
    ) -> None:
        """Register an LLM provider."""
        caps = capabilities or LLMCapabilities()
        self.register(
            name=name,
            provider_type=ProviderType.LLM,
            provider_class=provider_class,
            capabilities=caps,
            **kwargs,
        )

    def register_tts(
        self,
        name: str,
        provider_class: type[TTSInterface],
        capabilities: Optional[TTSCapabilities] = None,
        **kwargs,
    ) -> None:
        """Register a TTS provider."""
        caps = capabilities or TTSCapabilities()
        self.register(
            name=name,
            provider_type=ProviderType.TTS,
            provider_class=provider_class,
            capabilities=caps,
            **kwargs,
        )

    def register_vad(
        self,
        name: str,
        provider_class: type[VADInterface],
        capabilities: Optional[VADCapabilities] = None,
        **kwargs,
    ) -> None:
        """Register a VAD provider."""
        caps = capabilities or VADCapabilities()
        self.register(
            name=name,
            provider_type=ProviderType.VAD,
            provider_class=provider_class,
            capabilities=caps,
            **kwargs,
        )

    # ==================== Discovery ====================

    def _resolve_name(self, provider_type: ProviderType, name: str) -> str:
        """Resolve alias to actual provider name."""
        return self._aliases[provider_type].get(name, name)

    def get_info(
        self, name: str, provider_type: ProviderType
    ) -> Optional[ProviderInfo]:
        """
        Get provider info by name.

        Args:
            name: Provider name or alias.
            provider_type: Type of provider.

        Returns:
            ProviderInfo if found, None otherwise.
        """
        resolved_name = self._resolve_name(provider_type, name)
        return self._providers[provider_type].get(resolved_name)

    def get(
        self,
        name: str,
        provider_type: ProviderType,
        **config,
    ) -> Any:
        """
        Get a provider instance.

        Args:
            name: Provider name or alias.
            provider_type: Type of provider.
            **config: Configuration to pass to the provider constructor.

        Returns:
            Provider instance.

        Raises:
            KeyError: If provider not found.
        """
        info = self.get_info(name, provider_type)
        if info is None:
            available = list(self._providers[provider_type].keys())
            raise KeyError(
                f"Provider '{name}' not found for type {provider_type.value}. "
                f"Available: {available}"
            )

        # Merge default config with provided config
        merged_config = {**info.default_config, **config}

        # Instantiate the provider
        return info.provider_class(**merged_config)

    def get_asr(self, name: str, **config) -> ASRInterface:
        """Get an ASR provider instance."""
        return self.get(name, ProviderType.ASR, **config)

    def get_llm(self, name: str, **config) -> LLMInterface:
        """Get an LLM provider instance."""
        return self.get(name, ProviderType.LLM, **config)

    def get_tts(self, name: str, **config) -> TTSInterface:
        """Get a TTS provider instance."""
        return self.get(name, ProviderType.TTS, **config)

    def get_vad(self, name: str, **config) -> VADInterface:
        """Get a VAD provider instance."""
        return self.get(name, ProviderType.VAD, **config)

    # ==================== Listing ====================

    def list_providers(
        self, provider_type: Optional[str | ProviderType] = None
    ) -> dict[str, list[str]] | list[str]:
        """
        List registered providers.

        Args:
            provider_type: Optional filter by type ('asr', 'llm', 'tts', 'vad').
                          If None, returns all providers grouped by type.

        Returns:
            List of provider names if type specified,
            or dict of type -> names if no type specified.
        """
        if provider_type is None:
            return {
                pt.value: list(providers.keys())
                for pt, providers in self._providers.items()
            }

        if isinstance(provider_type, str):
            provider_type = ProviderType(provider_type)

        return list(self._providers[provider_type].keys())

    def list_asr(self) -> list[str]:
        """List registered ASR providers."""
        return self.list_providers(ProviderType.ASR)

    def list_llm(self) -> list[str]:
        """List registered LLM providers."""
        return self.list_providers(ProviderType.LLM)

    def list_tts(self) -> list[str]:
        """List registered TTS providers."""
        return self.list_providers(ProviderType.TTS)

    def list_vad(self) -> list[str]:
        """List registered VAD providers."""
        return self.list_providers(ProviderType.VAD)

    def get_capabilities(
        self, name: str, provider_type: ProviderType
    ) -> Optional[Capabilities]:
        """Get capabilities for a provider."""
        info = self.get_info(name, provider_type)
        return info.capabilities if info else None

    def find_by_capability(
        self,
        provider_type: ProviderType,
        **requirements,
    ) -> list[str]:
        """
        Find providers matching capability requirements.

        Args:
            provider_type: Type of provider to search.
            **requirements: Capability requirements (e.g., streaming=True).

        Returns:
            List of matching provider names.
        """
        matches = []

        for name, info in self._providers[provider_type].items():
            caps = info.capabilities
            match = True

            for key, value in requirements.items():
                if hasattr(caps, key):
                    cap_value = getattr(caps, key)

                    # Handle list membership check
                    if isinstance(cap_value, list) and not isinstance(value, list):
                        if value not in cap_value:
                            match = False
                            break
                    elif cap_value != value:
                        match = False
                        break
                else:
                    match = False
                    break

            if match:
                matches.append(name)

        return matches

    def find_by_tag(
        self,
        provider_type: ProviderType,
        tags: list[str],
        match_all: bool = True,
    ) -> list[str]:
        """
        Find providers by tags.

        Args:
            provider_type: Type of provider to search.
            tags: Tags to search for.
            match_all: If True, provider must have all tags.
                      If False, provider must have at least one tag.

        Returns:
            List of matching provider names.
        """
        matches = []

        for name, info in self._providers[provider_type].items():
            if match_all:
                if all(tag in info.tags for tag in tags):
                    matches.append(name)
            else:
                if any(tag in info.tags for tag in tags):
                    matches.append(name)

        return matches

    # ==================== Auto-discovery ====================

    def auto_discover(self, force: bool = False) -> int:
        """
        Auto-discover providers via entry_points.

        Looks for entry_points in the 'voice_pipeline.providers' group.

        Args:
            force: If True, re-run discovery even if already done.

        Returns:
            Number of providers discovered.
        """
        if self._auto_discovered and not force:
            return 0

        from voice_pipeline.providers.discovery import discover_providers

        count = discover_providers(self)
        self._auto_discovered = True
        return count


def get_registry() -> ProviderRegistry:
    """Get the global provider registry.

    Returns the singleton ProviderRegistry instance (managed by __new__).
    """
    return ProviderRegistry()


def reset_registry() -> None:
    """Reset the global registry. Useful for testing."""
    ProviderRegistry().reset()

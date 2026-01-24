"""
Decorators for registering Voice Pipeline providers.

These decorators provide a convenient way to register providers
at class definition time.

Example:
    @register_asr("whisper", capabilities=ASRCapabilities(streaming=True))
    class WhisperASR(ASRInterface):
        pass
"""

from typing import Callable, Optional, TypeVar

from voice_pipeline.interfaces import (
    ASRInterface,
    LLMInterface,
    TTSInterface,
    VADInterface,
)
from voice_pipeline.providers.types import (
    ASRCapabilities,
    LLMCapabilities,
    TTSCapabilities,
    VADCapabilities,
)

T = TypeVar("T")


def register_asr(
    name: str,
    capabilities: Optional[ASRCapabilities] = None,
    description: str = "",
    version: str = "1.0.0",
    author: str = "",
    aliases: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    default_config: Optional[dict] = None,
) -> Callable[[type[ASRInterface]], type[ASRInterface]]:
    """
    Decorator to register an ASR provider.

    Usage:
        @register_asr("whisper", capabilities=ASRCapabilities(streaming=True))
        class WhisperASR(ASRInterface):
            async def transcribe_stream(self, audio_stream, language=None):
                ...

    Args:
        name: Unique name for the provider.
        capabilities: ASR capabilities.
        description: Human-readable description.
        version: Provider version.
        author: Provider author.
        aliases: Alternative names.
        tags: Tags for categorization.
        default_config: Default configuration.

    Returns:
        Decorator function.
    """

    def decorator(cls: type[ASRInterface]) -> type[ASRInterface]:
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        registry.register_asr(
            name=name,
            provider_class=cls,
            capabilities=capabilities,
            description=description or cls.__doc__ or "",
            version=version,
            author=author,
            aliases=aliases,
            tags=tags,
            default_config=default_config,
        )

        # Store registration info on the class for introspection
        cls._voice_pipeline_name = name
        cls._voice_pipeline_type = "asr"

        return cls

    return decorator


def register_llm(
    name: str,
    capabilities: Optional[LLMCapabilities] = None,
    description: str = "",
    version: str = "1.0.0",
    author: str = "",
    aliases: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    default_config: Optional[dict] = None,
) -> Callable[[type[LLMInterface]], type[LLMInterface]]:
    """
    Decorator to register an LLM provider.

    Usage:
        @register_llm("openai", capabilities=LLMCapabilities(function_calling=True))
        class OpenAILLM(LLMInterface):
            async def generate_stream(self, messages, **kwargs):
                ...

    Args:
        name: Unique name for the provider.
        capabilities: LLM capabilities.
        description: Human-readable description.
        version: Provider version.
        author: Provider author.
        aliases: Alternative names.
        tags: Tags for categorization.
        default_config: Default configuration.

    Returns:
        Decorator function.
    """

    def decorator(cls: type[LLMInterface]) -> type[LLMInterface]:
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        registry.register_llm(
            name=name,
            provider_class=cls,
            capabilities=capabilities,
            description=description or cls.__doc__ or "",
            version=version,
            author=author,
            aliases=aliases,
            tags=tags,
            default_config=default_config,
        )

        cls._voice_pipeline_name = name
        cls._voice_pipeline_type = "llm"

        return cls

    return decorator


def register_tts(
    name: str,
    capabilities: Optional[TTSCapabilities] = None,
    description: str = "",
    version: str = "1.0.0",
    author: str = "",
    aliases: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    default_config: Optional[dict] = None,
) -> Callable[[type[TTSInterface]], type[TTSInterface]]:
    """
    Decorator to register a TTS provider.

    Usage:
        @register_tts("piper", capabilities=TTSCapabilities(
            voices=["en_US-amy-medium"],
            ssml=False,
        ))
        class PiperTTS(TTSInterface):
            async def synthesize_stream(self, text_stream, **kwargs):
                ...

    Args:
        name: Unique name for the provider.
        capabilities: TTS capabilities.
        description: Human-readable description.
        version: Provider version.
        author: Provider author.
        aliases: Alternative names.
        tags: Tags for categorization.
        default_config: Default configuration.

    Returns:
        Decorator function.
    """

    def decorator(cls: type[TTSInterface]) -> type[TTSInterface]:
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        registry.register_tts(
            name=name,
            provider_class=cls,
            capabilities=capabilities,
            description=description or cls.__doc__ or "",
            version=version,
            author=author,
            aliases=aliases,
            tags=tags,
            default_config=default_config,
        )

        cls._voice_pipeline_name = name
        cls._voice_pipeline_type = "tts"

        return cls

    return decorator


def register_vad(
    name: str,
    capabilities: Optional[VADCapabilities] = None,
    description: str = "",
    version: str = "1.0.0",
    author: str = "",
    aliases: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    default_config: Optional[dict] = None,
) -> Callable[[type[VADInterface]], type[VADInterface]]:
    """
    Decorator to register a VAD provider.

    Usage:
        @register_vad("silero", capabilities=VADCapabilities(
            frame_size_ms=30,
            confidence_scores=True,
        ))
        class SileroVAD(VADInterface):
            async def process(self, audio_chunk, sample_rate):
                ...

    Args:
        name: Unique name for the provider.
        capabilities: VAD capabilities.
        description: Human-readable description.
        version: Provider version.
        author: Provider author.
        aliases: Alternative names.
        tags: Tags for categorization.
        default_config: Default configuration.

    Returns:
        Decorator function.
    """

    def decorator(cls: type[VADInterface]) -> type[VADInterface]:
        from voice_pipeline.providers.registry import get_registry

        registry = get_registry()
        registry.register_vad(
            name=name,
            provider_class=cls,
            capabilities=capabilities,
            description=description or cls.__doc__ or "",
            version=version,
            author=author,
            aliases=aliases,
            tags=tags,
            default_config=default_config,
        )

        cls._voice_pipeline_name = name
        cls._voice_pipeline_type = "vad"

        return cls

    return decorator


def register_provider(
    provider_type: str,
    name: str,
    **kwargs,
) -> Callable[[type[T]], type[T]]:
    """
    Generic decorator to register any provider type.

    Usage:
        @register_provider("asr", "whisper", capabilities=ASRCapabilities())
        class WhisperASR(ASRInterface):
            ...

    Args:
        provider_type: Type of provider ('asr', 'llm', 'tts', 'vad').
        name: Unique name for the provider.
        **kwargs: Additional arguments for registration.

    Returns:
        Decorator function.
    """
    decorators = {
        "asr": register_asr,
        "llm": register_llm,
        "tts": register_tts,
        "vad": register_vad,
    }

    if provider_type not in decorators:
        raise ValueError(
            f"Unknown provider type: {provider_type}. "
            f"Must be one of: {list(decorators.keys())}"
        )

    return decorators[provider_type](name, **kwargs)

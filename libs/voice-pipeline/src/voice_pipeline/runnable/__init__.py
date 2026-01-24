"""
VoiceRunnable - Interface base para componentes do Voice Pipeline.

Este módulo fornece a fundação para criar pipelines de voz composíveis
usando o padrão LCEL (LangChain Expression Language) adaptado para Voice AI.

Exemplo básico:
    >>> from voice_pipeline.runnable import VoiceRunnable, VoiceSequence
    >>> chain = asr | llm | tts
    >>> result = await chain.ainvoke(audio_bytes)

Exemplo com streaming:
    >>> async for audio_chunk in chain.astream(audio_bytes):
    ...     play(audio_chunk)

Exemplo com paralelo:
    >>> parallel = VoiceParallel(
    ...     whisper=whisper_asr,
    ...     deepgram=deepgram_asr,
    ... )
    >>> results = await parallel.ainvoke(audio)
"""

from voice_pipeline.runnable.base import (
    Input,
    Output,
    VoiceRunnable,
    VoiceRunnableBound,
    VoiceRunnableWithConfig,
)
from voice_pipeline.runnable.config import (
    RunnableConfig,
    ensure_config,
    get_callback_manager,
)
from voice_pipeline.runnable.parallel import (
    VoiceParallel,
    VoiceRaceParallel,
)
from voice_pipeline.runnable.passthrough import (
    VoiceFallback,
    VoiceFilter,
    VoiceLambda,
    VoicePassthrough,
    VoiceRetry,
    VoiceRouter,
)
from voice_pipeline.runnable.sequence import (
    VoiceSequence,
    VoiceStreamingSequence,
)

__all__ = [
    # Base
    "VoiceRunnable",
    "VoiceRunnableBound",
    "VoiceRunnableWithConfig",
    "Input",
    "Output",
    # Config
    "RunnableConfig",
    "ensure_config",
    "get_callback_manager",
    # Sequence
    "VoiceSequence",
    "VoiceStreamingSequence",
    # Parallel
    "VoiceParallel",
    "VoiceRaceParallel",
    # Passthrough & Utils
    "VoicePassthrough",
    "VoiceLambda",
    "VoiceRouter",
    "VoiceFilter",
    "VoiceRetry",
    "VoiceFallback",
]

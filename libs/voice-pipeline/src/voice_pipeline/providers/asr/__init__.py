"""ASR (Automatic Speech Recognition) providers.

Available providers:
- OpenAIASRProvider: OpenAI Whisper (whisper-1)
- WhisperCppASRProvider: Local whisper.cpp (tiny, base, small, medium, large, turbo)
- DeepgramASRProvider: Real-time streaming ASR via WebSocket (nova-2)
- NemotronASRProvider: NVIDIA Nemotron Speech ASR (<24ms latency, GPU required)
- FasterWhisperProvider: FasterWhisper with CTranslate2 (4x faster, CPU optimized)
- ParakeetProvider: NVIDIA Parakeet via ONNX (25 languages, ~6% WER, CPU optimized)
"""

from voice_pipeline.providers.asr.openai import (
    OpenAIASRProvider,
    OpenAIASRConfig,
)
from voice_pipeline.providers.asr.whispercpp import (
    WhisperCppASRProvider,
    WhisperCppASRConfig,
)
from voice_pipeline.providers.asr.deepgram import (
    DeepgramASRProvider,
    DeepgramASRConfig,
    DeepgramASR,  # Alias
)
from voice_pipeline.providers.asr.nemotron import (
    NemotronASRProvider,
    NemotronASRConfig,
    ChunkLatencyMode,
)
from voice_pipeline.providers.asr.faster_whisper import (
    FasterWhisperProvider,
    FasterWhisperConfig,
    FasterWhisperModel,
    ComputeType,
)
from voice_pipeline.providers.asr.parakeet import (
    ParakeetProvider,
    ParakeetConfig,
)

__all__ = [
    # OpenAI Whisper
    "OpenAIASRProvider",
    "OpenAIASRConfig",
    # whisper.cpp (local)
    "WhisperCppASRProvider",
    "WhisperCppASRConfig",
    # Deepgram (streaming)
    "DeepgramASRProvider",
    "DeepgramASRConfig",
    "DeepgramASR",
    # NVIDIA Nemotron (ultra-low latency, GPU)
    "NemotronASRProvider",
    "NemotronASRConfig",
    "ChunkLatencyMode",
    # FasterWhisper (CPU optimized)
    "FasterWhisperProvider",
    "FasterWhisperConfig",
    "FasterWhisperModel",
    "ComputeType",
    # NVIDIA Parakeet (ONNX, CPU optimized, multilingual)
    "ParakeetProvider",
    "ParakeetConfig",
]

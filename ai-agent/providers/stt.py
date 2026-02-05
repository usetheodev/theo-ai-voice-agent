"""
Speech-to-Text (STT/ASR) - Converte áudio em texto

Arquitetura refatorada seguindo o padrão modelo_providers:
- Dataclass configs
- Async lifecycle (connect/disconnect)
- Warmup para cold-start
- Health checks
- Métricas

Providers:
- FasterWhisperSTT: Recomendado - 4x mais rápido que whisper original
- WhisperLocalSTT: Whisper original (fallback)
- OpenAIWhisperSTT: API OpenAI (cloud)
"""

import asyncio
import io
import logging
import os
import tempfile
import time
import wave
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from config import STT_CONFIG, AUDIO_CONFIG
from providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    DeviceFallbackStrategy,
)

logger = logging.getLogger("ai-agent.stt")


# ==================== Configs ====================

@dataclass
class FasterWhisperConfig(ProviderConfig):
    """Configuration for FasterWhisper ASR provider."""

    model: str = field(default_factory=lambda: STT_CONFIG.get("model", "tiny"))
    """Whisper model size. For CPU: tiny, base, or small recommended."""

    device: str = field(default_factory=lambda: STT_CONFIG.get("device", "cpu"))
    """Device: 'cpu' or 'cuda'."""

    compute_type: str = field(default_factory=lambda: STT_CONFIG.get("compute_type", "int8"))
    """Compute type. 'int8' for CPU, 'float16' for GPU."""

    language: Optional[str] = field(default_factory=lambda: STT_CONFIG.get("language", "pt"))
    """Language code (ISO-639-1). None for auto-detection."""

    beam_size: int = field(default_factory=lambda: STT_CONFIG.get("beam_size", 1))
    """Beam search width. 1 = fastest (greedy)."""

    vad_filter: bool = field(default_factory=lambda: STT_CONFIG.get("vad_filter", False))
    """Enable VAD to filter silent sections. False recommended - media-server já faz VAD."""

    vad_parameters: Optional[dict] = None
    """Custom VAD parameters. Silero VAD options:
    - threshold: float (0.0-1.0) - speech detection threshold, lower = more sensitive (default 0.5)
    - min_speech_duration_ms: int - minimum speech duration to keep
    - min_silence_duration_ms: int - minimum silence to segment
    - speech_pad_ms: int - padding around speech segments
    """

    word_timestamps: bool = field(default_factory=lambda: STT_CONFIG.get("word_timestamps", False))
    """Compute word-level timestamps."""

    sample_rate: int = field(default_factory=lambda: AUDIO_CONFIG.get("sample_rate", 8000))
    """Input audio sample rate (8kHz for telephony)."""

    cpu_threads: int = field(default_factory=lambda: STT_CONFIG.get("cpu_threads", 0))
    """Number of CPU threads. 0 = auto."""

    num_workers: int = field(default_factory=lambda: STT_CONFIG.get("num_workers", 1))
    """Number of parallel transcription workers."""


@dataclass
class WhisperLocalConfig(ProviderConfig):
    """Configuration for Whisper local provider."""

    model: str = "base"
    """Whisper model size."""

    language: str = "pt"
    """Language code."""

    sample_rate: int = 8000
    """Input audio sample rate."""


@dataclass
class OpenAIWhisperConfig(ProviderConfig):
    """Configuration for OpenAI Whisper API."""

    api_key: Optional[str] = None
    """OpenAI API key."""

    language: str = "pt"
    """Language code."""

    sample_rate: int = 8000
    """Input audio sample rate."""


# ==================== Base STT Interface ====================

class STTProvider(BaseProvider):
    """Interface base para provedores de STT."""

    @abstractmethod
    async def transcribe(self, audio_data: bytes) -> str:
        """Transcreve áudio para texto."""
        pass

    @abstractmethod
    async def transcribe_file(self, audio_file: str) -> str:
        """Transcreve arquivo de áudio para texto."""
        pass

    def _save_wav(self, file, audio_data: bytes) -> None:
        """Salva áudio como WAV."""
        with wave.open(file, 'wb') as wav:
            wav.setnchannels(AUDIO_CONFIG["channels"])
            wav.setsampwidth(AUDIO_CONFIG["sample_width"])
            wav.setframerate(AUDIO_CONFIG["sample_rate"])
            wav.writeframes(audio_data)


# ==================== FasterWhisper Provider ====================

class FasterWhisperSTT(STTProvider):
    """
    STT usando faster-whisper (CTranslate2).

    Significativamente mais rápido que o Whisper original:
    - Modelo tiny: RTF < 1.0 (real-time)
    - Modelo base: RTF ~1.0-1.5
    - Suporta int8 quantization para menor uso de memória
    """

    provider_name = "faster-whisper"

    def __init__(
        self,
        config: Optional[FasterWhisperConfig] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        **kwargs,
    ):
        # Build config from STT_CONFIG or parameters
        if config is None:
            config = FasterWhisperConfig(
                model=STT_CONFIG.get("model", "tiny"),
                device=STT_CONFIG.get("device", "cpu"),
                compute_type=STT_CONFIG.get("compute_type", "int8"),
                language=STT_CONFIG.get("language", "pt"),
                device_fallback=DeviceFallbackStrategy.GPU_TO_CPU,
            )

        # Apply shortcuts
        if model is not None:
            config.model = model
        if language is not None:
            config.language = language
        if device is not None:
            config.device = device
        if compute_type is not None:
            config.compute_type = compute_type

        super().__init__(config=config, **kwargs)
        self._stt_config: FasterWhisperConfig = config
        self._model = None
        self._executor = None

    @property
    def sample_rate(self) -> int:
        return self._stt_config.sample_rate

    async def connect(self) -> None:
        """Load FasterWhisper model."""
        await super().connect()

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper não instalado. Execute: pip install faster-whisper"
            )

        logger.info(
            f"Carregando faster-whisper: {self._stt_config.model} "
            f"({self._stt_config.compute_type}) em {self._stt_config.device}"
        )

        # Load model in thread pool
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(None, self._load_model)

        # Create executor for transcription
        import concurrent.futures
        executor_workers = STT_CONFIG.get("executor_workers", 2)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=executor_workers)

        logger.info(f" faster-whisper carregado: {self._stt_config.model}")

    def _load_model(self):
        """Load model (blocking)."""
        from faster_whisper import WhisperModel

        model_kwargs = {
            "device": self._stt_config.device,
            "compute_type": self._stt_config.compute_type,
        }

        if self._stt_config.cpu_threads > 0:
            model_kwargs["cpu_threads"] = self._stt_config.cpu_threads

        if self._stt_config.num_workers > 1:
            model_kwargs["num_workers"] = self._stt_config.num_workers

        return WhisperModel(self._stt_config.model, **model_kwargs)

    async def disconnect(self) -> None:
        """Release model resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        if self._model is not None:
            del self._model
            self._model = None
        await super().disconnect()

    async def reconnect_with_device(self, device: str) -> None:
        """Reconnect with a different device (CPU fallback)."""
        logger.warning(f"faster-whisper: switching to {device}")
        if self._stt_config.device == "cuda":
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
        self._stt_config.device = device
        self._stt_config.compute_type = "int8" if device == "cpu" else "float16"
        await self.disconnect()
        await self.connect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if model is loaded and functional."""
        if self._model is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Modelo não carregado. Chame connect() primeiro.",
            )

        try:
            import numpy as np
            test_audio = np.zeros(int(0.5 * 16000), dtype=np.float32)

            loop = asyncio.get_event_loop()
            segments, _ = await loop.run_in_executor(
                self._executor,
                lambda: self._model.transcribe(test_audio, beam_size=1),
            )
            list(segments)

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"faster-whisper pronto. Modelo: {self._stt_config.model}",
                details={
                    "model": self._stt_config.model,
                    "device": self._stt_config.device,
                    "compute_type": self._stt_config.compute_type,
                },
            )
        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Health check falhou: {e}",
            )

    async def warmup(self, **kwargs) -> float:
        """Warm up model to eliminate cold-start latency."""
        if self._model is None:
            raise RuntimeError("Modelo não carregado. Chame connect() primeiro.")

        import numpy as np
        warmup_audio = np.zeros(int(0.5 * 16000), dtype=np.float32)

        start = time.perf_counter()
        loop = asyncio.get_event_loop()

        def _warmup():
            segments, _ = self._model.transcribe(warmup_audio, beam_size=1)
            list(segments)

        await loop.run_in_executor(self._executor, _warmup)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True
        logger.info(f" faster-whisper warmup: {elapsed_ms:.1f}ms")
        return elapsed_ms

    async def transcribe(self, audio_data: bytes) -> str:
        """Transcreve áudio usando faster-whisper."""
        if self._model is None:
            return ""

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
                self._save_wav(f, audio_data)

            return await self.transcribe_file(temp_path)

        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            self._metrics.record_failure(str(e))
            return ""
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    async def transcribe_file(self, audio_file: str) -> str:
        """Transcreve arquivo de áudio usando faster-whisper."""
        if self._model is None:
            return ""

        start_time = time.perf_counter()

        try:
            language = self._stt_config.language

            def _transcribe_sync():
                # VAD desabilitado: o media-server já faz VAD antes de enviar audio.end
                # Double-VAD causa descarte de áudio válido (especialmente durante barge-in)
                segments, info = self._model.transcribe(
                    audio_file,
                    language=language,
                    beam_size=self._stt_config.beam_size,
                    vad_filter=False,
                )
                all_segments = list(segments)
                return all_segments, info

            loop = asyncio.get_event_loop()
            all_segments, info = await loop.run_in_executor(
                self._executor,
                _transcribe_sync,
            )

            text = " ".join(segment.text.strip() for segment in all_segments)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            if text:
                logger.info(
                    f" STT: '{text}' "
                    f"(lang: {info.language}, prob: {info.language_probability:.2f}, "
                    f"latency: {latency_ms:.0f}ms)"
                )

            return text

        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            self._metrics.record_failure(str(e))
            import traceback
            traceback.print_exc()
            return ""


# ==================== Whisper Local Provider ====================

class WhisperLocalSTT(STTProvider):
    """STT usando Whisper local (OpenAI)."""

    provider_name = "whisper"

    def __init__(
        self,
        config: Optional[WhisperLocalConfig] = None,
        **kwargs,
    ):
        if config is None:
            config = WhisperLocalConfig(
                model=STT_CONFIG.get("whisper_model", STT_CONFIG.get("model", "base")),
                language=STT_CONFIG.get("language", "pt"),
            )
        super().__init__(config=config, **kwargs)
        self._whisper_config: WhisperLocalConfig = config
        self._model = None

    async def connect(self) -> None:
        """Load Whisper model."""
        await super().connect()

        try:
            import whisper
        except ImportError:
            raise ImportError(
                "Whisper não instalado. Execute: pip install openai-whisper"
            )

        logger.info(f"Carregando modelo Whisper: {self._whisper_config.model}")

        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(
            None,
            lambda: whisper.load_model(self._whisper_config.model),
        )

        logger.info(" Modelo Whisper carregado")

    async def disconnect(self) -> None:
        """Release model resources."""
        if self._model is not None:
            del self._model
            self._model = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if model is loaded."""
        if self._model is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Modelo não carregado.",
            )
        return HealthCheckResult(
            status=ProviderHealth.HEALTHY,
            message=f"Whisper pronto. Modelo: {self._whisper_config.model}",
        )

    async def transcribe(self, audio_data: bytes) -> str:
        """Transcreve áudio usando Whisper local."""
        if not self._model:
            return ""

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
                self._save_wav(f, audio_data)

            return await self.transcribe_file(temp_path)

        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            return ""
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    async def transcribe_file(self, audio_file: str) -> str:
        """Transcreve arquivo de áudio usando Whisper local."""
        if not self._model:
            return ""

        start_time = time.perf_counter()

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._model.transcribe(
                    audio_file,
                    language=self._whisper_config.language,
                    fp16=False,  # CPU
                ),
            )

            text = result.get("text", "").strip()

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            if text:
                logger.info(f" STT: '{text}' (latency: {latency_ms:.0f}ms)")
            return text

        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            self._metrics.record_failure(str(e))
            import traceback
            traceback.print_exc()
            return ""


# ==================== OpenAI Whisper API Provider ====================

class OpenAIWhisperSTT(STTProvider):
    """STT usando API OpenAI Whisper."""

    provider_name = "openai-whisper"

    def __init__(
        self,
        config: Optional[OpenAIWhisperConfig] = None,
        **kwargs,
    ):
        if config is None:
            config = OpenAIWhisperConfig(
                api_key=STT_CONFIG.get("openai_api_key", os.getenv("OPENAI_API_KEY")),
                language=STT_CONFIG.get("language", "pt"),
            )
        super().__init__(config=config, **kwargs)
        self._openai_config: OpenAIWhisperConfig = config
        self.client = None

    async def connect(self) -> None:
        """Initialize OpenAI client."""
        await super().connect()

        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "OpenAI não instalado. Execute: pip install openai"
            )

        api_key = self._openai_config.api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada")

        self.client = OpenAI(api_key=api_key)
        logger.info(" Cliente OpenAI inicializado para STT")

    async def disconnect(self) -> None:
        """Close client."""
        self.client = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if client is ready."""
        if self.client is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Cliente não inicializado.",
            )
        return HealthCheckResult(
            status=ProviderHealth.HEALTHY,
            message="OpenAI Whisper API pronta.",
        )

    async def transcribe(self, audio_data: bytes) -> str:
        """Transcreve áudio usando API OpenAI."""
        if not self.client:
            return ""

        start_time = time.perf_counter()

        try:
            audio_file = io.BytesIO()
            with wave.open(audio_file, 'wb') as wav:
                wav.setnchannels(AUDIO_CONFIG["channels"])
                wav.setsampwidth(AUDIO_CONFIG["sample_width"])
                wav.setframerate(AUDIO_CONFIG["sample_rate"])
                wav.writeframes(audio_data)
            audio_file.seek(0)
            audio_file.name = "audio.wav"

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=self._openai_config.language,
                ),
            )

            text = response.text.strip()

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            if text:
                logger.info(f" STT: '{text}' (latency: {latency_ms:.0f}ms)")
            return text

        except Exception as e:
            logger.error(f"Erro na transcrição OpenAI: {e}")
            self._metrics.record_failure(str(e))
            return ""

    async def transcribe_file(self, audio_file: str) -> str:
        """Transcreve arquivo de áudio usando API OpenAI."""
        if not self.client:
            return ""

        start_time = time.perf_counter()

        try:
            loop = asyncio.get_event_loop()

            def _transcribe():
                with open(audio_file, 'rb') as f:
                    return self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                        language=self._openai_config.language,
                    )

            response = await loop.run_in_executor(None, _transcribe)
            text = response.text.strip()

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            if text:
                logger.info(f" STT: '{text}' (latency: {latency_ms:.0f}ms)")
            return text

        except Exception as e:
            logger.error(f"Erro na transcrição OpenAI: {e}")
            self._metrics.record_failure(str(e))
            return ""


# ==================== Factory ====================

# Mapeamento de providers para classes
_STT_PROVIDERS = {
    "faster-whisper": FasterWhisperSTT,
    "whisper": WhisperLocalSTT,
    "openai": OpenAIWhisperSTT,
}

_STT_FALLBACK_ORDER = ["faster-whisper", "whisper"]


def _create_stt_instance(provider: str = None) -> STTProvider:
    """Cria instância do provedor STT (sem conectar)."""
    provider = provider or STT_CONFIG.get("provider", "faster-whisper")

    # Tenta provider solicitado
    if provider in _STT_PROVIDERS:
        try:
            return _STT_PROVIDERS[provider]()
        except Exception as e:
            logger.warning(f"Falha ao criar {provider}: {e}")

    # Fallback para providers locais
    for fallback in _STT_FALLBACK_ORDER:
        if fallback != provider:
            try:
                logger.warning(f"Tentando fallback: {fallback}")
                return _STT_PROVIDERS[fallback]()
            except Exception:
                continue

    raise RuntimeError("Nenhum provedor STT disponível")


async def create_stt_provider() -> STTProvider:
    """Factory assíncrona para criar, conectar e aquecer provedor STT."""
    stt = _create_stt_instance()
    await stt.connect()

    # Warmup apenas para faster-whisper (modelo local)
    if isinstance(stt, FasterWhisperSTT):
        await stt.warmup()

    return stt


def create_stt_provider_sync() -> STTProvider:
    """
    Factory síncrona para criar provedor STT (sem conectar).

    Nota: Modelo não está carregado. Use create_stt_provider() para versão async completa.
    """
    return _create_stt_instance()

"""
Text-to-Speech (TTS) - Converte texto em áudio

Arquitetura refatorada seguindo o padrão modelo_providers:
- Dataclass configs
- Async lifecycle (connect/disconnect)
- Warmup para cold-start
- Health checks
- Métricas
- Streaming support

Providers:
- KokoroTTS: Local neural TTS de alta qualidade (24kHz)
- GoogleTTS: gTTS - gratuito mas requer internet
- OpenAITTS: Alta qualidade, streaming, requer API
- MockTTS: Para testes
"""

import asyncio
import io
import logging
import math
import os
import re
import struct
import subprocess
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Generator, Optional

from config import TTS_CONFIG, AUDIO_CONFIG
from providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    DeviceFallbackStrategy,
)

logger = logging.getLogger("ai-agent.tts")


# ==================== Configs ====================

@dataclass
class KokoroTTSConfig(ProviderConfig):
    """Configuration for Kokoro TTS provider."""

    lang_code: str = "p"
    """Language code (a=American, b=British, j=Japanese, k=Korean, z=Chinese, p=Portuguese)."""

    voice: str = field(default_factory=lambda: TTS_CONFIG.get("voice", "pf_dora"))
    """Default voice (e.g., pf_dora, af_bella, am_adam)."""

    speed: float = field(default_factory=lambda: TTS_CONFIG.get("speed", 1.0))
    """Speech speed (0.5 to 2.0)."""

    sample_rate: int = field(default_factory=lambda: TTS_CONFIG.get("sample_rate", 24000))
    """Output sample rate in Hz (Kokoro native)."""

    output_sample_rate: int = field(default_factory=lambda: TTS_CONFIG.get("output_sample_rate", 8000))
    """Output sample rate for telephony."""

    device: Optional[str] = None
    """Device to use (cpu, cuda). None for auto-detection."""

    repo_id: Optional[str] = None
    """HuggingFace repo ID for model. None uses default."""


@dataclass
class GoogleTTSConfig(ProviderConfig):
    """Configuration for Google TTS (gTTS)."""

    language: str = "pt"
    """Language code."""

    sample_rate: int = 8000
    """Output sample rate for telephony."""


@dataclass
class OpenAITTSConfig(ProviderConfig):
    """Configuration for OpenAI TTS."""

    api_key: Optional[str] = None
    """OpenAI API key."""

    model: str = "tts-1"
    """TTS model (tts-1 or tts-1-hd)."""

    voice: str = "alloy"
    """Voice (alloy, echo, fable, onyx, nova, shimmer)."""

    sample_rate: int = 8000
    """Output sample rate for telephony."""


# ==================== Base TTS Interface ====================

class TTSProvider(BaseProvider):
    """Interface base para provedores de TTS."""

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Converte texto em áudio (PCM 8kHz mono 16-bit)."""
        pass

    async def synthesize_stream(self, text: str) -> Generator[bytes, None, None]:
        """
        Converte texto em áudio com streaming.
        Yield chunks de áudio conforme são gerados.
        """
        audio = await self.synthesize(text)
        if audio:
            chunk_size = int(AUDIO_CONFIG["sample_rate"] * 0.1 * 2)  # 100ms
            for i in range(0, len(audio), chunk_size):
                yield audio[i:i + chunk_size]

    @property
    def supports_streaming(self) -> bool:
        """Indica se o provedor suporta streaming real."""
        return False


# ==================== Kokoro TTS Provider ====================

# Vozes populares para cada idioma
KOKORO_VOICES = {
    "a": ["af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael"],
    "b": ["bf_emma", "bf_isabella", "bm_george", "bm_lewis"],
    "p": ["pf_dora", "pm_alex", "pm_santa"],
}

# Textos de warmup por idioma
WARMUP_TEXTS = {
    "a": "Hello.",
    "b": "Hello.",
    "j": "こんにちは。",
    "k": "안녕하세요.",
    "z": "你好。",
    "p": "Olá.",
}


class KokoroTTS(TTSProvider):
    """
    TTS usando Kokoro - modelo neural local de alta qualidade.

    Kokoro é baseado em StyleTTS2 e gera áudio em 24kHz.
    Para telefonia, fazemos downsampling para 8kHz.

    Vozes disponíveis:
    - pf_dora: Voz feminina brasileira (português)
    - af_bella, af_sarah, am_adam, etc. (inglês)
    """

    provider_name = "kokoro"

    def __init__(
        self,
        config: Optional[KokoroTTSConfig] = None,
        voice: Optional[str] = None,
        lang_code: Optional[str] = None,
        speed: Optional[float] = None,
        device: Optional[str] = None,
        **kwargs,
    ):
        if config is None:
            # Detecta lang_code pela voz
            voice_value = TTS_CONFIG.get("voice", "pf_dora")
            lang_code_value = "p" if voice_value.startswith("p") else "a"

            config = KokoroTTSConfig(
                voice=voice_value,
                lang_code=lang_code_value,
                sample_rate=TTS_CONFIG.get("sample_rate", 24000),
                device_fallback=DeviceFallbackStrategy.GPU_TO_CPU,
            )

        # Apply shortcuts
        if voice is not None:
            config.voice = voice
            # Auto-detect lang_code from voice
            if voice.startswith("p"):
                config.lang_code = "p"
            elif voice.startswith("a"):
                config.lang_code = "a"
            elif voice.startswith("b"):
                config.lang_code = "b"
        if lang_code is not None:
            config.lang_code = lang_code
        if speed is not None:
            config.speed = speed
        if device is not None:
            config.device = device

        super().__init__(config=config, **kwargs)
        self._tts_config: KokoroTTSConfig = config
        self._pipeline = None
        self._executor = None

    @property
    def sample_rate(self) -> int:
        return self._tts_config.output_sample_rate

    @property
    def supports_streaming(self) -> bool:
        return True

    async def connect(self) -> None:
        """Initialize Kokoro pipeline."""
        await super().connect()

        try:
            from kokoro import KPipeline
        except ImportError:
            raise ImportError(
                "Kokoro não instalado. Execute: pip install kokoro soundfile"
            )

        logger.info(
            f"Inicializando Kokoro: voz={self._tts_config.voice}, "
            f"lang={self._tts_config.lang_code}"
        )

        loop = asyncio.get_event_loop()

        def _create_pipeline():
            return KPipeline(
                lang_code=self._tts_config.lang_code,
                repo_id=self._tts_config.repo_id,
                device=self._tts_config.device,
            )

        self._pipeline = await loop.run_in_executor(None, _create_pipeline)

        # Create executor for sync operations
        import concurrent.futures
        executor_workers = TTS_CONFIG.get("executor_workers", 2)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=executor_workers)

        logger.info(" Kokoro TTS inicializado")

    async def disconnect(self) -> None:
        """Release Kokoro resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._pipeline = None
        await super().disconnect()

    async def reconnect_with_device(self, device: str) -> None:
        """Reconnect with different device (CPU fallback)."""
        logger.warning(f"Kokoro TTS: switching to {device}")
        if self._tts_config.device and "cuda" in self._tts_config.device:
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
        self._tts_config.device = device
        await self.disconnect()
        await self.connect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if Kokoro is ready."""
        if self._pipeline is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Pipeline não inicializado. Chame connect() primeiro.",
            )

        try:
            loop = asyncio.get_event_loop()

            def _test_synth():
                results = list(self._pipeline(
                    "teste",
                    voice=self._tts_config.voice,
                    speed=1.0,
                ))
                return len(results) > 0

            success = await loop.run_in_executor(self._executor, _test_synth)

            if success:
                return HealthCheckResult(
                    status=ProviderHealth.HEALTHY,
                    message=f"Kokoro pronto. Voz: {self._tts_config.voice}",
                    details={
                        "voice": self._tts_config.voice,
                        "lang_code": self._tts_config.lang_code,
                    },
                )
            else:
                return HealthCheckResult(
                    status=ProviderHealth.DEGRADED,
                    message="Kokoro não retornou resultados.",
                )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Kokoro erro: {e}",
            )

    async def warmup(self, text: Optional[str] = None, **kwargs) -> float:
        """Warm up Kokoro to eliminate cold-start latency."""
        if self._pipeline is None:
            raise RuntimeError("Pipeline não conectado. Chame connect() primeiro.")

        warmup_text = text or WARMUP_TEXTS.get(self._tts_config.lang_code, "Olá.")

        start = time.perf_counter()
        _ = await self.synthesize(warmup_text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True
        logger.info(f" Kokoro warmup: {elapsed_ms:.1f}ms")
        return elapsed_ms

    def _preprocess_text(self, text: str) -> str:
        """Preprocessa texto para melhorar qualidade do TTS."""
        # Handle Portuguese time notation (16h29, 10h, etc.)
        def expand_time(match):
            hours = int(match.group(1))
            minutes = match.group(2)
            if minutes:
                minutes = int(minutes)
                return f"{hours} horas e {minutes} minutos"
            return f"{hours} horas"

        text = re.sub(r'(\d{1,2})h(\d{2})?', expand_time, text)

        # Handle percentage
        text = re.sub(r'(\d+)%', r'\1 por cento', text)

        # Handle temperature
        text = re.sub(r'(\d+)°C?', r'\1 graus', text)

        # Handle common abbreviations
        text = text.replace("etc.", "etcetera")
        text = text.replace("Sr.", "Senhor")
        text = text.replace("Sra.", "Senhora")
        text = text.replace("Dr.", "Doutor")
        text = text.replace("Dra.", "Doutora")

        return text

    def _resample(self, audio, from_rate: int, to_rate: int):
        """Resample áudio usando decimação simples."""
        import numpy as np

        if from_rate == to_rate:
            return audio

        factor = from_rate // to_rate
        if factor <= 0:
            return audio

        return audio[::factor]

    async def synthesize(self, text: str) -> bytes:
        """Converte texto em áudio usando Kokoro."""
        if not self._pipeline:
            return b""

        start_time = time.perf_counter()

        try:
            import numpy as np

            processed_text = self._preprocess_text(text)

            loop = asyncio.get_event_loop()

            def _synthesize():
                audio_chunks = []
                for _, _, audio_chunk in self._pipeline(
                    processed_text,
                    voice=self._tts_config.voice,
                    speed=self._tts_config.speed,
                ):
                    if audio_chunk is not None:
                        audio_chunks.append(audio_chunk)

                if not audio_chunks:
                    return b""

                # Concatenate chunks
                audio = np.concatenate(audio_chunks)

                # Resample from 24kHz to 8kHz
                audio_8k = self._resample(
                    audio,
                    self._tts_config.sample_rate,
                    self._tts_config.output_sample_rate,
                )

                # Convert to PCM 16-bit
                audio_int16 = (audio_8k * 32767).astype(np.int16)
                return audio_int16.tobytes()

            pcm_data = await loop.run_in_executor(self._executor, _synthesize)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            if pcm_data:
                logger.info(
                    f" TTS (Kokoro): {len(pcm_data)} bytes "
                    f"(latency: {latency_ms:.0f}ms)"
                )

            return pcm_data

        except Exception as e:
            logger.error(f"Erro no Kokoro TTS: {e}")
            self._metrics.record_failure(str(e))
            import traceback
            traceback.print_exc()
            return b""

    async def synthesize_stream(self, text: str) -> Generator[bytes, None, None]:
        """Converte texto em áudio com streaming."""
        if not self._pipeline:
            return

        try:
            import numpy as np

            processed_text = self._preprocess_text(text)

            loop = asyncio.get_event_loop()

            def _get_chunks():
                chunks = []
                for _, _, audio_chunk in self._pipeline(
                    processed_text,
                    voice=self._tts_config.voice,
                    speed=self._tts_config.speed,
                ):
                    if audio_chunk is not None and len(audio_chunk) > 0:
                        # Convert PyTorch Tensor to NumPy array
                        if hasattr(audio_chunk, 'numpy'):
                            audio_chunk = audio_chunk.numpy()
                        elif hasattr(audio_chunk, 'cpu'):
                            audio_chunk = audio_chunk.cpu().numpy()

                        audio_8k = self._resample(
                            audio_chunk,
                            self._tts_config.sample_rate,
                            self._tts_config.output_sample_rate,
                        )
                        audio_int16 = (audio_8k * 32767).astype(np.int16)
                        chunks.append(audio_int16.tobytes())
                return chunks

            chunks = await loop.run_in_executor(self._executor, _get_chunks)

            for chunk in chunks:
                yield chunk

        except Exception as e:
            logger.error(f"Erro no Kokoro TTS streaming: {e}")
            self._metrics.record_failure(str(e))

    def list_voices(self, lang_code: Optional[str] = None) -> list[str]:
        """List available voices for a language."""
        code = lang_code or self._tts_config.lang_code
        return KOKORO_VOICES.get(code, [])


# ==================== Google TTS Provider ====================

class GoogleTTS(TTSProvider):
    """TTS usando Google Text-to-Speech (gTTS)."""

    provider_name = "gtts"

    def __init__(
        self,
        config: Optional[GoogleTTSConfig] = None,
        **kwargs,
    ):
        if config is None:
            config = GoogleTTSConfig(
                language=TTS_CONFIG.get("language", "pt")[:2],
            )
        super().__init__(config=config, **kwargs)
        self._gtts_config: GoogleTTSConfig = config
        self.gTTS = None

    async def connect(self) -> None:
        """Initialize gTTS."""
        await super().connect()

        try:
            from gtts import gTTS
            self.gTTS = gTTS
            logger.info(" gTTS inicializado")
        except ImportError:
            raise ImportError(
                "gTTS não instalado. Execute: pip install gtts"
            )

    async def disconnect(self) -> None:
        """Release gTTS."""
        self.gTTS = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if gTTS is ready."""
        if self.gTTS is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="gTTS não inicializado.",
            )
        return HealthCheckResult(
            status=ProviderHealth.HEALTHY,
            message="gTTS pronto.",
        )

    async def synthesize(self, text: str) -> bytes:
        """Converte texto em áudio usando gTTS."""
        if not self.gTTS:
            return b""

        start_time = time.perf_counter()

        try:
            loop = asyncio.get_event_loop()

            def _synthesize():
                tts = self.gTTS(text=text, lang=self._gtts_config.language)
                mp3_buffer = io.BytesIO()
                tts.write_to_fp(mp3_buffer)
                mp3_buffer.seek(0)
                return self._convert_to_pcm(mp3_buffer.read())

            pcm_data = await loop.run_in_executor(None, _synthesize)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            logger.info(
                f" TTS (gTTS): {len(pcm_data)} bytes "
                f"(latency: {latency_ms:.0f}ms)"
            )
            return pcm_data

        except Exception as e:
            logger.error(f"Erro no gTTS: {e}")
            self._metrics.record_failure(str(e))
            return b""

    def _convert_to_pcm(self, mp3_data: bytes) -> bytes:
        """Converte MP3 para PCM 8kHz mono 16-bit usando ffmpeg."""
        try:
            process = subprocess.Popen(
                [
                    "ffmpeg", "-i", "pipe:0",
                    "-f", "s16le",
                    "-acodec", "pcm_s16le",
                    "-ar", str(AUDIO_CONFIG["sample_rate"]),
                    "-ac", "1",
                    "pipe:1"
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            pcm_data, stderr = process.communicate(input=mp3_data)

            if process.returncode != 0:
                logger.error(f"ffmpeg error: {stderr.decode()}")
                return b""

            return pcm_data

        except FileNotFoundError:
            logger.error("ffmpeg não encontrado")
            return b""
        except Exception as e:
            logger.error(f"Erro ao converter áudio: {e}")
            return b""


# ==================== OpenAI TTS Provider ====================

class OpenAITTS(TTSProvider):
    """TTS usando OpenAI API - suporta streaming real."""

    provider_name = "openai-tts"

    def __init__(
        self,
        config: Optional[OpenAITTSConfig] = None,
        **kwargs,
    ):
        if config is None:
            config = OpenAITTSConfig(
                api_key=TTS_CONFIG.get("openai_api_key", os.getenv("OPENAI_API_KEY")),
                model=TTS_CONFIG.get("openai_tts_model", "tts-1"),
                voice=TTS_CONFIG.get("openai_tts_voice", "alloy"),
            )
        super().__init__(config=config, **kwargs)
        self._openai_config: OpenAITTSConfig = config
        self.client = None

    @property
    def supports_streaming(self) -> bool:
        return True

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
            raise ValueError("OPENAI_API_KEY não configurada para TTS")

        self.client = OpenAI(api_key=api_key)
        logger.info(" OpenAI TTS inicializado")

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
            message=f"OpenAI TTS pronto. Voz: {self._openai_config.voice}",
        )

    async def synthesize(self, text: str) -> bytes:
        """Converte texto em áudio usando OpenAI TTS."""
        if not self.client:
            return b""

        start_time = time.perf_counter()

        try:
            loop = asyncio.get_event_loop()

            def _synthesize():
                response = self.client.audio.speech.create(
                    model=self._openai_config.model,
                    voice=self._openai_config.voice,
                    input=text,
                    response_format="pcm",  # PCM 24kHz mono 16-bit
                )
                return response.content

            pcm_24k = await loop.run_in_executor(None, _synthesize)
            pcm_8k = self._downsample_24k_to_8k(pcm_24k)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            logger.info(
                f" TTS (OpenAI): {len(pcm_8k)} bytes "
                f"(latency: {latency_ms:.0f}ms)"
            )
            return pcm_8k

        except Exception as e:
            logger.error(f"Erro no OpenAI TTS: {e}")
            self._metrics.record_failure(str(e))
            return b""

    async def synthesize_stream(self, text: str) -> Generator[bytes, None, None]:
        """Converte texto em áudio com streaming."""
        if not self.client:
            return

        try:
            loop = asyncio.get_event_loop()

            def _get_chunks():
                chunks = []
                with self.client.audio.speech.with_streaming_response.create(
                    model=self._openai_config.model,
                    voice=self._openai_config.voice,
                    input=text,
                    response_format="pcm",
                ) as response:
                    buffer = bytearray()
                    chunk_bytes = 4800  # 100ms at 24kHz

                    for chunk in response.iter_bytes(chunk_size=chunk_bytes):
                        buffer.extend(chunk)

                        while len(buffer) >= chunk_bytes:
                            pcm_24k = bytes(buffer[:chunk_bytes])
                            buffer = buffer[chunk_bytes:]
                            pcm_8k = self._downsample_24k_to_8k(pcm_24k)
                            chunks.append(pcm_8k)

                    if len(buffer) > 0:
                        pcm_8k = self._downsample_24k_to_8k(bytes(buffer))
                        chunks.append(pcm_8k)

                return chunks

            chunks = await loop.run_in_executor(None, _get_chunks)

            for chunk in chunks:
                yield chunk

        except Exception as e:
            logger.error(f"Erro no OpenAI TTS streaming: {e}")
            self._metrics.record_failure(str(e))

    def _downsample_24k_to_8k(self, pcm_24k: bytes) -> bytes:
        """Converte PCM de 24kHz para 8kHz (decimação por 3)."""
        try:
            if len(pcm_24k) < 2:
                return b""

            num_samples = len(pcm_24k) // 2
            samples = struct.unpack(f'<{num_samples}h', pcm_24k)
            downsampled = samples[::3]
            return struct.pack(f'<{len(downsampled)}h', *downsampled)
        except Exception:
            return pcm_24k


# ==================== Mock TTS Provider ====================

class MockTTS(TTSProvider):
    """TTS mock para testes (gera tom)."""

    provider_name = "mock"

    async def connect(self) -> None:
        await super().connect()
        logger.info(" Mock TTS inicializado")

    async def _do_health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            status=ProviderHealth.HEALTHY,
            message="Mock TTS pronto.",
        )

    async def synthesize(self, text: str) -> bytes:
        """Gera tom de teste."""
        sample_rate = AUDIO_CONFIG["sample_rate"]
        duration = max(1.0, len(text) * 0.05)
        frequency = 440

        samples = []
        for i in range(int(sample_rate * duration)):
            t = i / sample_rate
            envelope = min(1.0, t * 10) * min(1.0, (duration - t) * 10)
            sample = int(16000 * envelope * math.sin(2 * math.pi * frequency * i / sample_rate))
            samples.append(struct.pack('<h', sample))

        pcm_data = b''.join(samples)
        logger.info(f" TTS (mock): {len(pcm_data)} bytes")
        return pcm_data


# ==================== Factory ====================

# Mapeamento de providers para classes
_TTS_PROVIDERS = {
    "kokoro": KokoroTTS,
    "openai": OpenAITTS,
    "gtts": GoogleTTS,
    "mock": MockTTS,
}

_TTS_FALLBACK_ORDER = ["kokoro", "gtts", "mock"]


def _create_tts_instance(provider: str = None) -> TTSProvider:
    """Cria instância do provedor TTS (sem conectar)."""
    provider = provider or TTS_CONFIG.get("provider", "kokoro")

    # Tenta provider solicitado
    if provider in _TTS_PROVIDERS:
        try:
            return _TTS_PROVIDERS[provider]()
        except Exception as e:
            logger.warning(f"Falha ao criar {provider}: {e}")

    # Fallback para próximo provider disponível
    for fallback in _TTS_FALLBACK_ORDER:
        if fallback != provider:
            try:
                logger.warning(f"Tentando fallback: {fallback}")
                return _TTS_PROVIDERS[fallback]()
            except Exception:
                continue

    # Último recurso: mock
    return MockTTS()


async def create_tts_provider() -> TTSProvider:
    """Factory assíncrona para criar, conectar e aquecer provedor TTS."""
    tts = _create_tts_instance()
    await tts.connect()

    # Warmup apenas para Kokoro (modelo local)
    if isinstance(tts, KokoroTTS):
        await tts.warmup()

    return tts


def create_tts_provider_sync() -> TTSProvider:
    """
    Factory síncrona para criar provedor TTS (sem conectar).

    Nota: Pipeline não está inicializado. Use create_tts_provider() para versão async completa.
    """
    return _create_tts_instance()

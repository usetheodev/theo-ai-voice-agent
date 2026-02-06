"""
Speech-to-Text using Qwen3-ASR (Alibaba)

Qwen3-ASR is a state-of-the-art multilingual ASR model with:
- WER 1.63% on LibriSpeech (SOTA)
- Native streaming support
- PT-BR support
- Apache 2.0 license

Requires: transformers>=4.52.0, accelerate>=0.28.0
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

from config import STT_CONFIG, AUDIO_CONFIG
from providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    DeviceFallbackStrategy,
)
from providers.stt import STTProvider

logger = logging.getLogger("ai-agent.stt.qwen3")


@dataclass
class Qwen3ASRConfig(ProviderConfig):
    """Configuration for Qwen3-ASR provider."""

    model: str = field(
        default_factory=lambda: STT_CONFIG.get("model", "Qwen/Qwen3-ASR-1.7B")
    )
    """HuggingFace model ID."""

    device: str = field(default_factory=lambda: STT_CONFIG.get("device", "cpu"))
    """Device: 'cpu' or 'cuda'."""

    compute_type: str = field(
        default_factory=lambda: STT_CONFIG.get("compute_type", "float32")
    )
    """Compute type: float32 (CPU), float16/bfloat16 (GPU)."""

    language: Optional[str] = field(
        default_factory=lambda: STT_CONFIG.get("language", "pt")
    )
    """Language code."""

    chunk_duration_ms: int = field(
        default_factory=lambda: int(STT_CONFIG.get("qwen3_chunk_ms", 500))
    )
    """Chunk duration for streaming mode (ms)."""

    target_sample_rate: int = 16000
    """Qwen3-ASR expects 16kHz input."""

    max_new_tokens: int = field(
        default_factory=lambda: int(STT_CONFIG.get("qwen3_max_tokens", 512))
    )
    """Maximum new tokens for generation."""

    use_flash_attention: bool = field(
        default_factory=lambda: STT_CONFIG.get("qwen3_flash_attn", "false").lower()
        in ("true", "1", "yes")
        if isinstance(STT_CONFIG.get("qwen3_flash_attn", "false"), str)
        else bool(STT_CONFIG.get("qwen3_flash_attn", False))
    )
    """Use Flash Attention 2 for faster inference."""

    sample_rate: int = field(
        default_factory=lambda: AUDIO_CONFIG.get("sample_rate", 8000)
    )
    """Input audio sample rate (telephony)."""


class Qwen3ASRSTT(STTProvider):
    """
    STT using Qwen3-ASR (Alibaba).

    Best-in-class WER (1.63% on LibriSpeech), native multilingual support,
    and streaming capability via incremental prefix processing.
    """

    provider_name = "qwen3-asr"

    def __init__(
        self,
        config: Optional[Qwen3ASRConfig] = None,
        **kwargs,
    ):
        if config is None:
            model = STT_CONFIG.get("model", "Qwen/Qwen3-ASR-1.7B")
            # Default model for qwen3-asr provider
            if model in ("tiny", "base", "small", "medium", "large-v3"):
                model = "Qwen/Qwen3-ASR-1.7B"

            config = Qwen3ASRConfig(
                model=model,
                device=STT_CONFIG.get("device", "cpu"),
                compute_type=STT_CONFIG.get("compute_type", "float32"),
                language=STT_CONFIG.get("language", "pt"),
                device_fallback=DeviceFallbackStrategy.GPU_TO_CPU,
            )
        super().__init__(config=config, **kwargs)
        self._asr_config: Qwen3ASRConfig = config
        self._model = None
        self._processor = None
        self._executor = None

    @property
    def sample_rate(self) -> int:
        return self._asr_config.sample_rate

    @property
    def supports_streaming_stt(self) -> bool:
        return True

    async def connect(self) -> None:
        """Load Qwen3-ASR model and processor."""
        await super().connect()

        logger.info(
            f"Carregando Qwen3-ASR: {self._asr_config.model} "
            f"({self._asr_config.compute_type}) em {self._asr_config.device}"
        )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_model)

        import concurrent.futures
        executor_workers = STT_CONFIG.get("executor_workers", 2)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=executor_workers
        )

        logger.info(f" Qwen3-ASR carregado: {self._asr_config.model}")

    def _load_model(self):
        """Load model and processor (blocking)."""
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
        import torch

        dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        torch_dtype = dtype_map.get(self._asr_config.compute_type, torch.float32)

        model_kwargs = {
            "torch_dtype": torch_dtype,
            "trust_remote_code": True,
        }

        if self._asr_config.use_flash_attention:
            model_kwargs["attn_implementation"] = "flash_attention_2"

        self._processor = AutoProcessor.from_pretrained(
            self._asr_config.model,
            trust_remote_code=True,
        )

        self._model = AutoModelForSpeechSeq2Seq.from_pretrained(
            self._asr_config.model,
            **model_kwargs,
        )

        if self._asr_config.device == "cuda":
            self._model = self._model.cuda()

        self._model.eval()

    async def disconnect(self) -> None:
        """Release model and VRAM."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        if self._model is not None:
            del self._model
            self._model = None
        if self._processor is not None:
            del self._processor
            self._processor = None
        # Free GPU memory
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        await super().disconnect()

    async def reconnect_with_device(self, device: str) -> None:
        """Reconnect with a different device (CPU fallback)."""
        logger.warning(f"qwen3-asr: switching to {device}")
        self._asr_config.device = device
        if device == "cpu":
            self._asr_config.compute_type = "float32"
        await self.disconnect()
        await self.connect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check model is loaded and functional."""
        if self._model is None or self._processor is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Modelo não carregado. Chame connect() primeiro.",
            )

        try:
            import numpy as np
            test_audio = np.zeros(int(0.5 * 16000), dtype=np.float32)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                self._executor, lambda: self._inference_sync(test_audio)
            )
            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"Qwen3-ASR pronto. Modelo: {self._asr_config.model}",
                details={
                    "model": self._asr_config.model,
                    "device": self._asr_config.device,
                    "compute_type": self._asr_config.compute_type,
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
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor, lambda: self._inference_sync(warmup_audio)
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True
        logger.info(f" Qwen3-ASR warmup: {elapsed_ms:.1f}ms")
        return elapsed_ms

    def _prepare_audio(self, audio_data: bytes, input_sample_rate: int = 0):
        """PCM 16-bit signed -> float32 16kHz numpy array."""
        import numpy as np

        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        input_sr = input_sample_rate or self._asr_config.sample_rate
        target_sr = self._asr_config.target_sample_rate
        if input_sr != target_sr:
            n_target = int(len(audio_np) * target_sr / input_sr)
            x_orig = np.arange(len(audio_np))
            x_target = np.linspace(0, len(audio_np) - 1, n_target)
            audio_np = np.interp(x_target, x_orig, audio_np)
            logger.debug(
                f"Resampled {input_sr}Hz → {target_sr}Hz "
                f"({len(audio_data)//2} → {n_target} samples)"
            )

        return audio_np

    def _build_chat_input(self, audio_np):
        """Build Qwen3-ASR chat-template input."""
        conversation = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": audio_np},
                ],
            }
        ]
        return conversation

    def _inference_sync(self, audio_np) -> str:
        """Run model.generate() synchronously (called in thread pool)."""
        import torch

        conversation = self._build_chat_input(audio_np)

        # Use processor's chat template
        text = self._processor.apply_chat_template(
            conversation,
            add_generation_prompt=True,
            tokenize=False,
        )
        audios = [audio_np]

        inputs = self._processor(
            text=text,
            audios=audios,
            sampling_rate=self._asr_config.target_sample_rate,
            return_tensors="pt",
            padding=True,
        )

        if self._asr_config.device == "cuda":
            inputs = {k: v.cuda() if hasattr(v, 'cuda') else v for k, v in inputs.items()}

        with torch.no_grad():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=self._asr_config.max_new_tokens,
            )

        # Decode only new tokens
        input_len = inputs["input_ids"].shape[1]
        generated_ids = generated_ids[:, input_len:]

        result = self._processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )

        return result[0].strip() if result else ""

    async def transcribe(self, audio_data: bytes, input_sample_rate: int = 0) -> str:
        """Transcreve áudio usando Qwen3-ASR (batch mode)."""
        if self._model is None:
            return ""

        from providers.base import ProviderUnavailableError
        try:
            self._check_circuit_breaker()
        except ProviderUnavailableError:
            logger.warning(
                f"{self.provider_name}: circuit breaker OPEN - skipping transcription"
            )
            return ""

        start_time = time.perf_counter()

        try:
            audio_np = self._prepare_audio(audio_data, input_sample_rate)

            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(
                self._executor, lambda: self._inference_sync(audio_np)
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)
            self._record_circuit_success()

            if text:
                logger.info(
                    f" STT (qwen3): '{text}' (latency: {latency_ms:.0f}ms)"
                )
            else:
                audio_duration_ms = len(audio_data) / 2 / self.sample_rate * 1000
                logger.info(
                    f" STT (qwen3): <vazio> "
                    f"(audio: {audio_duration_ms:.0f}ms, latency: {latency_ms:.0f}ms)"
                )

            return text

        except Exception as e:
            logger.error(f"Erro na transcrição Qwen3-ASR: {e}")
            self._metrics.record_failure(str(e))
            self._record_circuit_failure()
            return ""

    async def transcribe_stream(
        self, audio_data: bytes, input_sample_rate: int = 0
    ) -> AsyncGenerator[str, None]:
        """Transcreve áudio com prefixos crescentes para resultados parciais.

        Processa o áudio em chunks crescentes, gerando transcrições
        parciais incrementais para menor latência percebida.
        """
        if self._model is None:
            return

        audio_np = self._prepare_audio(audio_data, input_sample_rate)

        chunk_samples = int(
            self._asr_config.chunk_duration_ms / 1000.0
            * self._asr_config.target_sample_rate
        )

        # Minimum audio for first chunk (at least 200ms)
        min_samples = int(0.2 * self._asr_config.target_sample_rate)
        total_samples = len(audio_np)

        if total_samples <= min_samples:
            # Audio too short for streaming, use batch
            result = await self.transcribe(audio_data, input_sample_rate)
            if result:
                yield result
            return

        loop = asyncio.get_running_loop()
        prev_text = ""
        pos = chunk_samples

        while pos < total_samples:
            prefix = audio_np[:pos]

            try:
                text = await loop.run_in_executor(
                    self._executor, lambda p=prefix: self._inference_sync(p)
                )

                if text and text != prev_text:
                    yield text
                    prev_text = text
            except Exception as e:
                logger.error(f"Erro no streaming Qwen3-ASR: {e}")

            pos += chunk_samples

        # Final pass with full audio
        try:
            text = await loop.run_in_executor(
                self._executor, lambda: self._inference_sync(audio_np)
            )
            if text and text != prev_text:
                yield text
        except Exception as e:
            logger.error(f"Erro no streaming final Qwen3-ASR: {e}")

    async def transcribe_file(self, audio_file: str) -> str:
        """Transcreve arquivo de áudio via Qwen3-ASR."""
        if self._model is None:
            return ""

        try:
            import soundfile as sf
            import numpy as np

            audio_np, sr = sf.read(audio_file, dtype="float32")

            # Resample if needed
            if sr != self._asr_config.target_sample_rate:
                n_target = int(
                    len(audio_np)
                    * self._asr_config.target_sample_rate
                    / sr
                )
                x_orig = np.arange(len(audio_np))
                x_target = np.linspace(0, len(audio_np) - 1, n_target)
                audio_np = np.interp(x_target, x_orig, audio_np)

            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(
                self._executor, lambda: self._inference_sync(audio_np)
            )
            return text

        except Exception as e:
            logger.error(f"Erro na transcrição de arquivo Qwen3-ASR: {e}")
            return ""

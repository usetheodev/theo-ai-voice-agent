"""
STT Provider - Speech-to-Text para transcricao

Versao simplificada do provider do ai-agent, focado apenas em transcricao.
"""

import asyncio
import logging
import os
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional, Tuple

from config import STT_CONFIG, AUDIO_CONFIG

logger = logging.getLogger("ai-transcribe.stt")


@dataclass
class TranscriptionResult:
    """Resultado de uma transcricao."""
    text: str
    language: str
    language_probability: float
    latency_ms: float
    audio_duration_ms: float

    @property
    def is_empty(self) -> bool:
        """Verifica se transcricao esta vazia."""
        return not self.text or not self.text.strip()


class STTProvider:
    """
    Provider de STT usando Faster-Whisper.

    Otimizado para transcricao em tempo real com baixa latencia.

    Example:
        stt = STTProvider()
        await stt.connect()

        result = await stt.transcribe(audio_data)
        print(f"Texto: {result.text}")

        await stt.disconnect()
    """

    def __init__(self):
        self._model = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._connected = False

        # Config
        self._model_name = STT_CONFIG["model"]
        self._device = STT_CONFIG["device"]
        self._compute_type = STT_CONFIG["compute_type"]
        self._language = STT_CONFIG["language"]
        self._beam_size = STT_CONFIG["beam_size"]

        # Audio config
        self._sample_rate = AUDIO_CONFIG["sample_rate"]
        self._channels = AUDIO_CONFIG["channels"]
        self._sample_width = AUDIO_CONFIG["sample_width"]

        logger.info(
            f"STTProvider criado: model={self._model_name}, "
            f"device={self._device}, compute_type={self._compute_type}"
        )

    @property
    def is_connected(self) -> bool:
        """Verifica se esta conectado."""
        return self._connected

    async def connect(self) -> bool:
        """
        Carrega o modelo Whisper.

        Returns:
            True se carregou com sucesso
        """
        if self._connected:
            return True

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper nao instalado. Execute: pip install faster-whisper"
            )

        logger.info(
            f"Carregando faster-whisper: {self._model_name} "
            f"({self._compute_type}) em {self._device}"
        )

        loop = asyncio.get_event_loop()

        # Carrega modelo em thread separada
        self._model = await loop.run_in_executor(None, self._load_model)

        # Cria executor para transcricoes
        executor_workers = STT_CONFIG.get("executor_workers", 2)
        self._executor = ThreadPoolExecutor(max_workers=executor_workers)

        self._connected = True
        logger.info(f"faster-whisper carregado: {self._model_name}")

        # Warmup
        await self.warmup()

        return True

    def _load_model(self):
        """Carrega modelo (blocking)."""
        from faster_whisper import WhisperModel

        model_kwargs = {
            "device": self._device,
            "compute_type": self._compute_type,
        }

        cpu_threads = STT_CONFIG.get("cpu_threads", 0)
        if cpu_threads > 0:
            model_kwargs["cpu_threads"] = cpu_threads

        num_workers = STT_CONFIG.get("num_workers", 1)
        if num_workers > 1:
            model_kwargs["num_workers"] = num_workers

        return WhisperModel(self._model_name, **model_kwargs)

    async def disconnect(self) -> None:
        """Libera recursos do modelo."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

        if self._model is not None:
            del self._model
            self._model = None

        self._connected = False
        logger.info("STTProvider desconectado")

    async def warmup(self) -> float:
        """
        Aquece o modelo para eliminar latencia de cold-start.

        Returns:
            Tempo de warmup em ms
        """
        if self._model is None:
            raise RuntimeError("Modelo nao carregado. Chame connect() primeiro.")

        import numpy as np
        warmup_audio = np.zeros(int(0.5 * 16000), dtype=np.float32)

        start = time.perf_counter()
        loop = asyncio.get_event_loop()

        def _warmup():
            segments, _ = self._model.transcribe(warmup_audio, beam_size=1)
            list(segments)

        await loop.run_in_executor(self._executor, _warmup)
        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(f"STT warmup concluido: {elapsed_ms:.1f}ms")
        return elapsed_ms

    async def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        """
        Transcreve audio para texto.

        Args:
            audio_data: Dados de audio PCM (16-bit, mono)

        Returns:
            TranscriptionResult com texto e metadados
        """
        if self._model is None:
            return TranscriptionResult(
                text="",
                language=self._language,
                language_probability=0.0,
                latency_ms=0.0,
                audio_duration_ms=0.0,
            )

        temp_path = None
        start_time = time.perf_counter()

        try:
            # Calcula duracao do audio
            audio_duration_ms = self._calculate_audio_duration(audio_data)

            # Salva como WAV temporario
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
                self._save_wav(f, audio_data)

            # Transcreve
            text, language, language_prob = await self._transcribe_file(temp_path)

            latency_ms = (time.perf_counter() - start_time) * 1000

            result = TranscriptionResult(
                text=text,
                language=language,
                language_probability=language_prob,
                latency_ms=latency_ms,
                audio_duration_ms=audio_duration_ms,
            )

            if text:
                logger.info(
                    f"STT: '{text}' "
                    f"(lang={language}, prob={language_prob:.2f}, "
                    f"latency={latency_ms:.0f}ms)"
                )

            return result

        except Exception as e:
            logger.error(f"Erro na transcricao: {e}")
            return TranscriptionResult(
                text="",
                language=self._language,
                language_probability=0.0,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                audio_duration_ms=0.0,
            )
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    async def _transcribe_file(self, audio_file: str) -> Tuple[str, str, float]:
        """
        Transcreve arquivo de audio.

        Returns:
            Tuple (texto, idioma, probabilidade)
        """
        language = self._language

        def _transcribe_sync():
            segments, info = self._model.transcribe(
                audio_file,
                language=language,
                beam_size=self._beam_size,
                vad_filter=False,  # VAD ja feito no media-server
            )
            all_segments = list(segments)
            return all_segments, info

        loop = asyncio.get_event_loop()
        all_segments, info = await loop.run_in_executor(
            self._executor,
            _transcribe_sync,
        )

        text = " ".join(segment.text.strip() for segment in all_segments)

        return text, info.language, info.language_probability

    def _save_wav(self, file, audio_data: bytes) -> None:
        """Salva audio como WAV."""
        with wave.open(file, 'wb') as wav:
            wav.setnchannels(self._channels)
            wav.setsampwidth(self._sample_width)
            wav.setframerate(self._sample_rate)
            wav.writeframes(audio_data)

    def _calculate_audio_duration(self, audio_data: bytes) -> float:
        """
        Calcula duracao do audio em ms.

        Args:
            audio_data: Dados de audio PCM

        Returns:
            Duracao em ms
        """
        bytes_per_sample = self._sample_width * self._channels
        num_samples = len(audio_data) / bytes_per_sample
        duration_seconds = num_samples / self._sample_rate
        return duration_seconds * 1000


async def create_stt_provider() -> STTProvider:
    """
    Factory para criar e conectar provider STT.

    Returns:
        STTProvider pronto para uso
    """
    stt = STTProvider()
    await stt.connect()
    return stt

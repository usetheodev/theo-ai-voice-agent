"""
Voice Activity Detection (VAD) - Detecção de atividade de voz
Buffer de áudio com detecção de fim de fala
"""

import logging
import struct
from collections import deque
from typing import Optional

from config import AUDIO_CONFIG

logger = logging.getLogger("ai-agent.vad")

try:
    import webrtcvad
    WEBRTC_VAD_AVAILABLE = True
except ImportError:
    WEBRTC_VAD_AVAILABLE = False
    logger.warning("webrtcvad não disponível - usando fallback de energia")


class AudioBuffer:
    """Buffer de áudio com detecção de voz usando WebRTC VAD.

    Modos de operação:
    - vad_enabled=True: VAD local (add_frame/add_audio processam VAD frame a frame)
    - vad_enabled=False: VAD externo (add_audio_raw acumula sem processar, media-server faz VAD)
    """

    # Tamanhos de frame suportados pelo WebRTC VAD (em ms)
    VALID_FRAME_DURATIONS = [10, 20, 30]

    def __init__(self, silence_threshold_ms: int = None, vad_aggressiveness: int = None,
                 vad_enabled: bool = True, sample_rate: int = 0, frame_duration_ms: int = 0):
        """
        Args:
            silence_threshold_ms: Tempo de silêncio para considerar fim de fala
            vad_aggressiveness: Agressividade do VAD (0-3, maior = mais agressivo)
            vad_enabled: Se False, não inicializa VAD (usa add_audio_raw com VAD externo)
            sample_rate: Sample rate do áudio (da sessão ASP). 0 = usa AUDIO_CONFIG.
            frame_duration_ms: Duração do frame (da sessão ASP). 0 = usa AUDIO_CONFIG.
        """
        self.buffer = bytearray()

        # Configurações de áudio: prioridade ASP session > AUDIO_CONFIG global
        self.sample_rate = sample_rate or AUDIO_CONFIG["sample_rate"]
        self.frame_duration_ms = frame_duration_ms or AUDIO_CONFIG["frame_duration_ms"]
        self.frame_size = int(self.sample_rate * self.frame_duration_ms / 1000) * 2  # 16-bit

        # Limite máximo do buffer
        max_buffer_seconds = AUDIO_CONFIG.get("max_buffer_seconds", 10)
        bytes_per_sec = self.sample_rate * 2  # 16-bit mono
        self.MAX_BUFFER_SIZE = max_buffer_seconds * bytes_per_sec

        self.silence_frames = 0
        self.speech_detected = False

        # Duração mínima de fala para ser válida (permite "sim", "não", "ok")
        self.min_speech_ms = AUDIO_CONFIG.get("min_speech_ms", 250)

        # VAD desabilitado: media-server faz VAD e envia audio.end
        self.vad_enabled = vad_enabled
        self.vad = None
        self.use_webrtc_vad = False
        self.speech_ring_buffer = deque(maxlen=1)

        if not vad_enabled:
            logger.info("AudioBuffer: VAD desabilitado (VAD externo via media-server)")
            return

        # --- VAD local (só inicializa se vad_enabled=True) ---

        # Usa valor passado ou config (sincronizado com media-server)
        config_threshold = AUDIO_CONFIG.get("silence_threshold_ms", 500)
        self.silence_threshold = silence_threshold_ms or config_threshold

        vad_level = vad_aggressiveness if vad_aggressiveness is not None else AUDIO_CONFIG["vad_aggressiveness"]

        if WEBRTC_VAD_AVAILABLE:
            try:
                if self.frame_duration_ms in self.VALID_FRAME_DURATIONS:
                    self.vad = webrtcvad.Vad(vad_level)
                    self.use_webrtc_vad = True
                    logger.info(f" WebRTC VAD inicializado (agressividade={vad_level})")
                else:
                    logger.warning(
                        f"WebRTC VAD requer frame de {self.VALID_FRAME_DURATIONS}ms, "
                        f"configurado {self.frame_duration_ms}ms - usando fallback de energia"
                    )
            except Exception as e:
                logger.warning(f"Erro ao inicializar WebRTC VAD: {e} - usando fallback de energia")

        # Fallback: VAD baseado em energia (configurável)
        self.energy_threshold = AUDIO_CONFIG.get("energy_threshold", 500)

        # Ring buffer para suavização (configurável)
        ring_buffer_size = AUDIO_CONFIG.get("vad_ring_buffer_size", 5)
        self.speech_ring_buffer = deque(maxlen=ring_buffer_size)

        # Threshold de ratio de fala para considerar que há fala
        self.speech_ratio_threshold = AUDIO_CONFIG.get("vad_speech_ratio_threshold", 0.4)

    def add_frame(self, frame: bytes) -> Optional[bytes]:
        """
        Adiciona frame de áudio ao buffer.
        Retorna áudio completo quando detecta fim de fala.
        """
        if len(self.buffer) >= self.MAX_BUFFER_SIZE:
            logger.warning("Buffer de áudio atingiu limite máximo, resetando")
            self._reset()
            return None

        is_speech = self._is_speech(frame)
        self.speech_ring_buffer.append(is_speech)

        # Evita divisão por zero e usa threshold configurável
        if not self.speech_ring_buffer:
            is_speech_smoothed = is_speech
        else:
            speech_ratio = sum(self.speech_ring_buffer) / len(self.speech_ring_buffer)
            is_speech_smoothed = speech_ratio >= self.speech_ratio_threshold

        if is_speech_smoothed:
            self.speech_detected = True
            self.silence_frames = 0
            self.buffer.extend(frame)
        else:
            if self.speech_detected:
                self.buffer.extend(frame)
                self.silence_frames += 1

                silence_ms = self.silence_frames * self.frame_duration_ms
                if silence_ms >= self.silence_threshold:
                    # Cálculo: bytes / 2 (16-bit) / sample_rate * 1000 = ms
                    num_samples = len(self.buffer) // 2
                    speech_ms = (num_samples / self.sample_rate) * 1000

                    if speech_ms >= self.min_speech_ms:
                        audio = bytes(self.buffer)
                        logger.debug(f" Fala detectada: {speech_ms:.0f}ms ({len(self.buffer)} bytes)")
                        self._reset()
                        return audio
                    else:
                        logger.debug(f"️ Fala muito curta ignorada: {speech_ms:.0f}ms < {self.min_speech_ms}ms")
                        self._reset()

        return None

    def add_audio(self, audio_data: bytes) -> Optional[bytes]:
        """
        Adiciona bloco de áudio ao buffer, processando frame a frame.
        Retorna áudio completo quando detecta fim de fala.
        """
        result = None
        offset = 0

        while offset < len(audio_data):
            frame = audio_data[offset:offset + self.frame_size]
            if len(frame) < self.frame_size:
                # Frame incompleto - adiciona ao buffer sem processar VAD
                if self.speech_detected:
                    self.buffer.extend(frame)
                break

            result = self.add_frame(frame)
            if result:
                return result

            offset += self.frame_size

        return result

    def add_audio_raw(self, audio_data: bytes) -> None:
        """
        Adiciona áudio ao buffer SEM processar VAD.
        Use quando o VAD é feito externamente (ex: pelo media-server).

        Se o buffer exceder o limite máximo, descarta áudio mais antigo
        mantendo apenas os últimos N segundos (backpressure).
        """
        # Se o audio_data sozinho excede o buffer, trunca o próprio audio_data
        if len(audio_data) > self.MAX_BUFFER_SIZE:
            audio_data = audio_data[-self.MAX_BUFFER_SIZE:]
            self.buffer = bytearray()

        if len(self.buffer) + len(audio_data) > self.MAX_BUFFER_SIZE:
            # Backpressure: descarta áudio mais antigo, mantém últimos N bytes
            overflow = (len(self.buffer) + len(audio_data)) - self.MAX_BUFFER_SIZE
            self._truncate_count = getattr(self, '_truncate_count', 0) + 1
            if self._truncate_count <= 3 or self._truncate_count % 50 == 0:
                logger.warning(
                    f"Buffer de áudio excedeu limite ({self.MAX_BUFFER_SIZE//1000}KB), "
                    f"descartando {overflow} bytes antigos"
                )
            # Remove do início (áudio mais antigo)
            self.buffer = self.buffer[overflow:]

        self.buffer.extend(audio_data)
        self.speech_detected = True  # Marca que tem fala (VAD externo)

    def flush(self) -> Optional[bytes]:
        """Retorna áudio acumulado e reseta buffer"""
        if len(self.buffer) > 0:
            num_samples = len(self.buffer) // 2
            speech_ms = (num_samples / self.sample_rate) * 1000
            logger.debug(f" Flush: {speech_ms:.0f}ms ({len(self.buffer)} bytes)")
            if speech_ms >= self.min_speech_ms:
                audio = bytes(self.buffer)
                self._reset()
                return audio
        self._reset()
        return None

    def _is_speech(self, frame: bytes) -> bool:
        """Detecta se o frame contém fala"""
        if self.use_webrtc_vad and self.vad:
            try:
                return self.vad.is_speech(frame, self.sample_rate)
            except Exception as e:
                # Log apenas uma vez para não poluir
                if not hasattr(self, '_webrtc_error_logged'):
                    logger.warning(f"WebRTC VAD falhou, usando fallback de energia: {e}")
                    self._webrtc_error_logged = True

        return self._calculate_energy(frame) > self.energy_threshold

    def _calculate_energy(self, frame: bytes) -> float:
        """Calcula energia RMS do frame (fallback)"""
        if len(frame) < 2:
            return 0

        samples = struct.unpack(f'<{len(frame)//2}h', frame)
        if not samples:
            return 0

        sum_squares = sum(s * s for s in samples)
        return (sum_squares / len(samples)) ** 0.5

    def _reset(self):
        """Reseta buffer"""
        self.buffer = bytearray()
        self.silence_frames = 0
        self.speech_detected = False
        self.speech_ring_buffer.clear()
        self._truncate_count = 0

    @property
    def has_audio(self) -> bool:
        """Verifica se há áudio no buffer"""
        return len(self.buffer) > 0

    @property
    def duration_ms(self) -> float:
        """Retorna duração do áudio no buffer em ms"""
        return len(self.buffer) / self.sample_rate / 2 * 1000

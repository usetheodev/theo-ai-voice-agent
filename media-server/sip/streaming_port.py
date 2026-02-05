"""
Streaming Audio Port - Captura de áudio em tempo real usando PJSUA2 AudioMediaPort

Este módulo elimina a necessidade de gravar em arquivo, processando frames
de áudio (20ms) em tempo real e enviando imediatamente para o destino de áudio.

Latência: ~20ms por frame (vs 3000ms com gravação em arquivo)
"""

import logging
import asyncio
import struct
import threading
from typing import Optional, Callable, TYPE_CHECKING
from collections import deque

try:
    import pjsua2 as pj
except ImportError:
    raise ImportError("pjsua2 não encontrado")

from config import AUDIO_CONFIG, RTP_QUALITY_CONFIG, MEDIA_FORK_CONFIG
from metrics import track_vad_event, track_vad_utterance_duration
from sip.rtp_quality import RtpQualityTracker

if TYPE_CHECKING:
    from ports.audio_destination import IAudioDestination
    from core.media_fork_manager import MediaForkManager

logger = logging.getLogger("media-server.streaming")


def bytes_to_bytevector(data: bytes) -> pj.ByteVector:
    """Converte bytes para pj.ByteVector (necessário para frame.buf)"""
    bv = pj.ByteVector(len(data))
    # Usa assign que é mais eficiente que loop byte a byte
    for i in range(len(data)):
        bv[i] = data[i]
    return bv


# Cache de silêncio para evitar alocações repetidas
_silence_cache: dict = {}

try:
    import webrtcvad
    WEBRTC_VAD_AVAILABLE = True
except ImportError:
    WEBRTC_VAD_AVAILABLE = False
    logger.warning("webrtcvad não disponível - usando fallback de energia")


class StreamingVAD:
    """VAD otimizado para streaming com resposta rápida"""

    VALID_FRAME_DURATIONS = [10, 20, 30]
    VALID_SAMPLE_RATES = [8000, 16000, 32000, 48000]

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 20,
        silence_threshold_ms: int = 500,
        vad_aggressiveness: int = 2,
        min_speech_ms: int = 250,
        energy_threshold: int = 500,
        ring_buffer_size: int = 5,
        speech_ratio_threshold: float = 0.4,
    ):
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.silence_threshold_ms = silence_threshold_ms
        self.min_speech_ms = min_speech_ms
        self.speech_ratio_threshold = speech_ratio_threshold

        self.silence_frames = 0
        self.speech_frames = 0
        self.speech_detected = False
        self.is_speaking = False

        # WebRTC VAD
        self.vad = None
        self.use_webrtc_vad = False

        if WEBRTC_VAD_AVAILABLE:
            try:
                if (frame_duration_ms in self.VALID_FRAME_DURATIONS and
                    sample_rate in self.VALID_SAMPLE_RATES):
                    self.vad = webrtcvad.Vad(vad_aggressiveness)
                    self.use_webrtc_vad = True
                    logger.debug(f"WebRTC VAD inicializado: {sample_rate}Hz, {frame_duration_ms}ms")
            except Exception as e:
                logger.warning(f"Erro ao inicializar WebRTC VAD: {e}")

        # Fallback: energia (configurável via env)
        self.energy_threshold = energy_threshold

        # Ring buffer para suavização (tamanho configurável)
        self.speech_ring_buffer = deque(maxlen=ring_buffer_size)

    def process_frame(self, frame: bytes) -> tuple[bool, bool]:
        """
        Processa frame de áudio.

        Returns:
            (speech_started, speech_ended): Tupla indicando transições
        """
        is_speech = self._is_speech(frame)
        self.speech_ring_buffer.append(is_speech)

        # Suavização (threshold configurável)
        speech_ratio = sum(self.speech_ring_buffer) / len(self.speech_ring_buffer) if self.speech_ring_buffer else 0
        is_speech_smoothed = speech_ratio >= self.speech_ratio_threshold

        speech_started = False
        speech_ended = False

        if is_speech_smoothed:
            if not self.is_speaking:
                self.is_speaking = True
                speech_started = True
                track_vad_event('speech_start')
                logger.debug(" Fala detectada")

            self.speech_frames += 1
            self.silence_frames = 0

        else:
            if self.is_speaking:
                self.silence_frames += 1
                silence_ms = self.silence_frames * self.frame_duration_ms
                speech_ms = self.speech_frames * self.frame_duration_ms

                if silence_ms >= self.silence_threshold_ms:
                    if speech_ms >= self.min_speech_ms:
                        speech_ended = True
                        track_vad_event('speech_end')
                        track_vad_utterance_duration(speech_ms)
                        logger.debug(f" Fim de fala: {speech_ms}ms de fala, {silence_ms}ms de silêncio")
                    else:
                        track_vad_event('too_short')
                        logger.debug(f"️ Fala muito curta ignorada: {speech_ms}ms")

                    self.reset()

        return speech_started, speech_ended

    def _is_speech(self, frame: bytes) -> bool:
        """Detecta se frame contém fala"""
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
        """Calcula energia RMS do frame"""
        if len(frame) < 2:
            return 0

        try:
            samples = struct.unpack(f'<{len(frame)//2}h', frame)
            if not samples:
                return 0

            sum_squares = sum(s * s for s in samples)
            return (sum_squares / len(samples)) ** 0.5
        except Exception:
            return 0

    def reset(self):
        """Reseta estado do VAD"""
        self.silence_frames = 0
        self.speech_frames = 0
        self.is_speaking = False
        self.speech_ring_buffer.clear()


class StreamingAudioPort(pj.AudioMediaPort):
    """
    AudioMediaPort customizado para streaming em tempo real.

    Recebe frames de áudio do PJSUA2 (20ms cada) e:
    1. Faz downsampling de 16kHz para 8kHz (se necessário)
    2. Aplica VAD em tempo real
    3. Envia imediatamente para o destino de áudio (AI Agent, Softphone, etc.)

    Isso elimina a latência de 3 segundos da gravação em arquivo.
    """

    def __init__(
        self,
        audio_destination: "IAudioDestination",
        session_id: str,
        loop: asyncio.AbstractEventLoop,
        on_speech_end: Optional[Callable[[], None]] = None,
        on_speech_start: Optional[Callable[[], None]] = None,
        fork_manager: Optional["MediaForkManager"] = None,
    ):
        pj.AudioMediaPort.__init__(self)

        self.audio_destination = audio_destination
        self.session_id = session_id
        self.loop = loop
        self.on_speech_end = on_speech_end
        self.on_speech_start = on_speech_start

        # Media Fork Manager (isolamento do path de IA)
        self.fork_manager = fork_manager
        self.use_fork = fork_manager is not None and MEDIA_FORK_CONFIG.get("enabled", True)

        # PJSUA2 usa 16kHz internamente, AI Agent espera 8kHz
        self.input_sample_rate = 16000
        self.output_sample_rate = AUDIO_CONFIG["sample_rate"]  # 8000
        self.frame_duration_ms = AUDIO_CONFIG["frame_duration_ms"]  # 20ms

        # VAD com configurações do AUDIO_CONFIG
        self.vad = StreamingVAD(
            sample_rate=self.output_sample_rate,  # VAD em 8kHz após downsampling
            frame_duration_ms=self.frame_duration_ms,
            silence_threshold_ms=AUDIO_CONFIG.get("silence_threshold_ms", 500),
            vad_aggressiveness=AUDIO_CONFIG.get("vad_aggressiveness", 2),
            min_speech_ms=AUDIO_CONFIG.get("min_speech_ms", 250),
            energy_threshold=AUDIO_CONFIG.get("energy_threshold", 500),
            ring_buffer_size=AUDIO_CONFIG.get("vad_ring_buffer_size", 5),
            speech_ratio_threshold=AUDIO_CONFIG.get("vad_speech_ratio_threshold", 0.4),
        )

        # Controle
        self.is_active = True
        self.monitor_mode = False  # Em monitor_mode: detecta fala mas não envia áudio
        self.frames_processed = 0
        self.bytes_sent = 0

        # Buffer para acumulação antes de enviar (configurável)
        self.send_buffer = bytearray()
        self.send_buffer_max = AUDIO_CONFIG.get("send_buffer_max", 1600)

        # Lock para thread-safety
        self._lock = threading.Lock()

        # RTP Quality Tracker (usando configurações centralizadas)
        self.rtp_tracker = RtpQualityTracker(
            expected_interval_ms=RTP_QUALITY_CONFIG.get("expected_interval_ms", self.frame_duration_ms),
            gap_threshold_factor=RTP_QUALITY_CONFIG.get("gap_threshold_factor", 1.5),
            direction="inbound"
        )

        fork_status = "fork_enabled" if self.use_fork else "direct_send"
        logger.info(f"[{session_id[:8]}] StreamingAudioPort criado ({fork_status})")

    def createPort(self, name: str, clock_rate: int, channel_count: int,
                   samples_per_frame: int, bits_per_sample: int):
        """Configura o port de áudio (chamado pelo PJSUA2)"""
        # Cria formato de áudio
        fmt = pj.MediaFormatAudio()
        fmt.type = pj.PJMEDIA_TYPE_AUDIO
        fmt.id = pj.PJMEDIA_FORMAT_L16  # PCM 16-bit linear
        fmt.clockRate = clock_rate
        fmt.channelCount = channel_count
        fmt.bitsPerSample = bits_per_sample
        fmt.frameTimeUsec = int((samples_per_frame / clock_rate) * 1_000_000)

        # Chama implementação base com o formato
        pj.AudioMediaPort.createPort(self, name, fmt)

        self.input_sample_rate = clock_rate
        logger.info(f"[{self.session_id[:8]}] Port criado: {clock_rate}Hz, {channel_count}ch, {samples_per_frame} samples")

    def onFrameRequested(self, frame: pj.MediaFrame):
        """Chamado quando PJSUA2 precisa de áudio para enviar (playback)"""
        # Não usado para captura - apenas para playback
        pass

    def _extract_audio_data(self, frame: pj.MediaFrame) -> Optional[bytes]:
        """Extrai e prepara dados de áudio do frame."""
        audio_data = bytes(frame.buf)
        if len(audio_data) == 0:
            return None

        # Track RTP quality (antes do downsampling)
        self.rtp_tracker.track_frame(len(audio_data))

        # Downsampling: 16kHz -> 8kHz
        if self.input_sample_rate != self.output_sample_rate:
            audio_data = self._downsample(audio_data)

        return audio_data

    def _invoke_callback_safe(self, callback: Optional[Callable], name: str):
        """Invoca callback de forma segura."""
        if callback:
            try:
                callback()
            except Exception as e:
                logger.error(f"Erro em {name}: {e}")

    def _dispatch_audio(self, audio_data: bytes):
        """Envia áudio para o destino apropriado."""
        if self.use_fork and self.fork_manager:
            self.fork_manager.fork_audio(self.session_id, audio_data)
            self.bytes_sent += len(audio_data)
        else:
            self._send_audio_async(audio_data)

    def _handle_speech_end(self):
        """Processa fim de fala."""
        self._send_audio_end_async()
        self._invoke_callback_safe(self.on_speech_end, "on_speech_end")

    def _process_normal_mode(self, audio_data: bytes, speech_ended: bool):
        """Processa audio no modo normal (acumula e envia)."""
        self.send_buffer.extend(audio_data)

        # Envia quando buffer estiver cheio ou fim de fala
        should_send = len(self.send_buffer) >= self.send_buffer_max or speech_ended

        if should_send and len(self.send_buffer) > 0:
            audio_to_send = bytes(self.send_buffer)
            self.send_buffer = bytearray()
            self._dispatch_audio(audio_to_send)

        if speech_ended:
            self._handle_speech_end()

    def onFrameReceived(self, frame: pj.MediaFrame):
        """
        Chamado quando um frame de áudio é recebido do RTP.
        Este é o ponto de entrada do streaming real.

        Modos de operação:
        - is_active=False: Ignora completamente
        - monitor_mode=True: Detecta fala (para barge-in) mas não envia áudio
        - Normal: Detecta fala E envia áudio

        IMPORTANTE: Com fork_manager habilitado, o envio de áudio NUNCA bloqueia.
        O áudio é copiado para um buffer e consumido assincronamente.
        """
        if not self.is_active and not self.monitor_mode:
            return

        try:
            with self._lock:
                audio_data = self._extract_audio_data(frame)
                if audio_data is None:
                    return

                # VAD em tempo real (sempre executa para barge-in)
                speech_started, speech_ended = self.vad.process_frame(audio_data)

                # Callback de início de fala (importante para barge-in!)
                if speech_started:
                    self._invoke_callback_safe(self.on_speech_start, "on_speech_start")

                # Em monitor_mode, só detecta fala - não envia áudio
                if not self.monitor_mode:
                    self._process_normal_mode(audio_data, speech_ended)

                self.frames_processed += 1

        except Exception as e:
            logger.error(f"[{self.session_id[:8]}] Erro em onFrameReceived: {e}")

    def _downsample(self, audio_data: bytes) -> bytes:
        """
        Converte áudio de 16kHz para 8kHz.
        Decimação simples: pega cada 2º sample.
        """
        try:
            # Converte bytes para samples (16-bit signed)
            num_samples = len(audio_data) // 2
            samples = struct.unpack(f'<{num_samples}h', audio_data)

            # Decimação por fator 2
            downsampled = samples[::2]

            # Converte de volta para bytes
            return struct.pack(f'<{len(downsampled)}h', *downsampled)
        except Exception as e:
            logger.error(f"Erro no downsampling: {e}")
            return audio_data

    def _send_audio_async(self, audio_data: bytes):
        """Envia áudio para o destino de forma assíncrona"""
        try:
            asyncio.run_coroutine_threadsafe(
                self.audio_destination.send_audio(self.session_id, audio_data),
                self.loop
            )
            self.bytes_sent += len(audio_data)
        except Exception as e:
            logger.error(f"[{self.session_id[:8]}] Erro ao enviar áudio: {e}")

    def _send_audio_end_async(self):
        """Envia sinal de fim de áudio para o destino"""
        try:
            asyncio.run_coroutine_threadsafe(
                self.audio_destination.send_audio_end(self.session_id),
                self.loop
            )
            logger.info(f"[{self.session_id[:8]}]  audio.end enviado (frames: {self.frames_processed}, bytes: {self.bytes_sent})")
        except Exception as e:
            logger.error(f"[{self.session_id[:8]}] Erro ao enviar audio.end: {e}")

    def flush_buffer(self):
        """Força envio do buffer restante"""
        with self._lock:
            if len(self.send_buffer) > 0:
                self._send_audio_async(bytes(self.send_buffer))
                self.send_buffer = bytearray()

    def stop(self):
        """Para o streaming"""
        self.is_active = False
        self.flush_buffer()

        # Atualiza métricas finais de RTP
        self.rtp_tracker.update_gauges()

        logger.info(f"[{self.session_id[:8]}] StreamingAudioPort parado (frames: {self.frames_processed})")

    def reset_vad(self):
        """Reseta o VAD (útil após reproduzir resposta)"""
        self.vad.reset()


class StreamingPlaybackPort(pj.AudioMediaPort):
    """
    AudioMediaPort para playback de áudio streaming.

    Recebe chunks de áudio do AI Agent e reproduz em tempo real,
    sem precisar esperar o áudio completo.
    """

    def __init__(self, session_id: str, sample_rate: int = 16000):
        pj.AudioMediaPort.__init__(self)

        self.session_id = session_id
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * 0.02) * 2  # 20ms em bytes (16-bit)

        # Buffer circular de áudio para playback
        self.audio_buffer = bytearray()
        self._lock = threading.Lock()

        # Controle
        self.is_active = True
        self.frames_played = 0

        logger.info(f"[{session_id[:8]}] StreamingPlaybackPort criado")

    def createPort(self, name: str, clock_rate: int, channel_count: int,
                   samples_per_frame: int, bits_per_sample: int):
        """Configura o port de áudio (chamado pelo PJSUA2)"""
        # Cria formato de áudio
        fmt = pj.MediaFormatAudio()
        fmt.type = pj.PJMEDIA_TYPE_AUDIO
        fmt.id = pj.PJMEDIA_FORMAT_L16  # PCM 16-bit linear
        fmt.clockRate = clock_rate
        fmt.channelCount = channel_count
        fmt.bitsPerSample = bits_per_sample
        fmt.frameTimeUsec = int((samples_per_frame / clock_rate) * 1_000_000)

        # Chama implementação base com o formato
        pj.AudioMediaPort.createPort(self, name, fmt)
        logger.info(f"[{self.session_id[:8]}] PlaybackPort criado: {clock_rate}Hz, {channel_count}ch")

    def add_audio(self, audio_data: bytes):
        """Adiciona áudio ao buffer de playback"""
        with self._lock:
            # Se input é 8kHz, fazer upsampling para 16kHz
            if len(audio_data) > 0:
                # Upsampling simples: duplica cada sample
                upsampled = self._upsample(audio_data)
                self.audio_buffer.extend(upsampled)

    def _upsample(self, audio_data: bytes) -> bytes:
        """Converte áudio de 8kHz para 16kHz (duplica samples)"""
        try:
            num_samples = len(audio_data) // 2
            samples = struct.unpack(f'<{num_samples}h', audio_data)

            # Duplica cada sample
            upsampled = []
            for s in samples:
                upsampled.extend([s, s])

            return struct.pack(f'<{len(upsampled)}h', *upsampled)
        except Exception:
            return audio_data

    def onFrameRequested(self, frame: pj.MediaFrame):
        """Chamado quando PJSUA2 precisa de áudio para enviar (playback)"""
        if not self.is_active:
            frame.type = pj.PJMEDIA_FRAME_TYPE_NONE
            return

        with self._lock:
            if len(self.audio_buffer) >= self.frame_size:
                # Copia frame do buffer
                frame_data = bytes(self.audio_buffer[:self.frame_size])
                self.audio_buffer = self.audio_buffer[self.frame_size:]

                frame.buf = bytes_to_bytevector(frame_data)
                frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
                self.frames_played += 1
            else:
                # Buffer vazio - envia silêncio (usa cache para performance)
                if self.frame_size not in _silence_cache:
                    _silence_cache[self.frame_size] = bytes_to_bytevector(b'\x00' * self.frame_size)
                frame.buf = _silence_cache[self.frame_size]
                frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO

    def onFrameReceived(self, frame: pj.MediaFrame):
        """Não usado para playback"""
        pass

    def clear(self):
        """Limpa buffer de áudio"""
        with self._lock:
            self.audio_buffer = bytearray()

    def stop(self):
        """Para o playback"""
        self.is_active = False
        self.clear()
        logger.info(f"[{self.session_id[:8]}] StreamingPlaybackPort parado (frames: {self.frames_played})")

    @property
    def buffered_duration_ms(self) -> float:
        """Retorna duração do áudio no buffer em ms"""
        with self._lock:
            bytes_buffered = len(self.audio_buffer)
            samples_buffered = bytes_buffered // 2
            return (samples_buffered / self.sample_rate) * 1000

    @property
    def has_audio(self) -> bool:
        """Verifica se há áudio suficiente para pelo menos um frame"""
        with self._lock:
            # Considera vazio se tem menos que um frame (não será reproduzido)
            return len(self.audio_buffer) >= self.frame_size

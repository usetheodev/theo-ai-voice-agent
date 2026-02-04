"""
Gerenciamento de Chamadas SIP - Versão Streaming Real

Esta versão usa streaming bidirecional em tempo real:
- StreamingAudioPort: captura de áudio do usuário
- StreamingPlaybackPort: playback de áudio da resposta

Fluxo de áudio (bidirecional):
    Captura:  RTP -> PJSUA2 -> StreamingAudioPort  -> Audio Destination
    Playback: RTP <- PJSUA2 <- StreamingPlaybackPort <- Audio Destination
                                (20ms frames)

Latência típica: ~100-200ms (vs 3-5s com gravação em arquivo)
"""

import logging
import threading
import time
import uuid
import asyncio
from typing import Optional, TYPE_CHECKING

try:
    import pjsua2 as pj
except ImportError:
    print("ERRO: pjsua2 não encontrado! Use Docker ou compile PJSIP.")
    import sys
    sys.exit(1)

from config import AUDIO_CONFIG
from metrics import track_call_ended, track_rtp_transmitted, track_barge_in, track_e2e_latency, track_barge_in_progress
from sip.streaming_port import StreamingAudioPort, StreamingPlaybackPort
from ports.audio_destination import SessionInfo, AudioConfig

if TYPE_CHECKING:
    from ports.audio_destination import IAudioDestination

logger = logging.getLogger("media-server.call")


class MyCall(pj.Call):
    """Gerencia uma chamada SIP com processamento streaming"""

    def __init__(self, acc, audio_destination: "IAudioDestination", loop, call_id=pj.PJSUA_INVALID_ID):
        pj.Call.__init__(self, acc, call_id)
        self.acc = acc
        self.audio_destination = audio_destination
        self.loop = loop

        # ID único para correlação de logs
        self.unique_call_id = str(uuid.uuid4())[:8]
        self.session_id = str(uuid.uuid4())

        # Mídia
        self.call_media: Optional[pj.AudioMedia] = None
        self.streaming_port: Optional[StreamingAudioPort] = None
        self.playback_port: Optional[StreamingPlaybackPort] = None
        self.player: Optional[pj.AudioMediaPlayer] = None

        # Controle de thread
        self.conversation_thread: Optional[threading.Thread] = None
        self.stop_conversation = threading.Event()

        # Controle de playback streaming
        self.playback_finished = threading.Event()
        self.playback_finished.set()  # Inicia como "finalizado"

        # Flag para aguardar greeting terminar
        self.greeting_finished = threading.Event()
        self.is_first_response = True

        # Timestamp de início para cálculo de duração
        self.call_start_time: Optional[float] = None

        # Estado do streaming
        self.is_streaming = False
        self.is_playing_response = False

        # Barge-in: permite interromper playback quando usuário fala
        self.barge_in_enabled = True
        self.barge_in_triggered = threading.Event()

        # Bytes transmitidos para métricas
        self.bytes_transmitted = 0

        # E2E latency tracking
        self.speech_end_timestamp: float = 0.0
        self.e2e_recorded: bool = False

        # Barge-in progress tracking
        self.response_total_bytes: int = 0
        self.response_played_bytes: int = 0

    def _log(self, message: str, level: str = "info"):
        log_func = getattr(logger, level, logger.info)
        log_func(f"[{self.unique_call_id}] {message}")

    def onCallState(self, prm):
        """Estado da chamada mudou"""
        ci = self.getInfo()
        self._log(f"📞 Estado: {ci.stateText}")

        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            self._log(f"✅ Chamada conectada: {ci.remoteUri}")
            self.call_start_time = time.time()
            self._start_conversation()

        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            self._log(f"📴 Chamada encerrada (código: {ci.lastStatusCode})")

            # Registra duração da chamada
            if self.call_start_time:
                duration = time.time() - self.call_start_time
                track_call_ended(duration)
                self._log(f"⏱️ Duração: {duration:.1f}s")

            self._stop_conversation()
            self._cleanup()
            if hasattr(self.acc, 'current_call') and self.acc.current_call == self:
                self.acc.current_call = None

    def _cleanup(self):
        """Limpa recursos"""
        # Para streaming ports
        if self.streaming_port:
            try:
                self.streaming_port.stop()
            except Exception:
                pass
            self.streaming_port = None

        if self.playback_port:
            try:
                # Desconecta do call_media antes de parar
                if self.call_media:
                    try:
                        self.playback_port.stopTransmit(self.call_media)
                    except Exception:
                        pass
                self.playback_port.stop()
            except Exception:
                pass
            self.playback_port = None

    def _start_conversation(self):
        """Inicia thread de conversação"""
        self.stop_conversation.clear()
        self.conversation_thread = threading.Thread(target=self._conversation_loop, daemon=True)
        self.conversation_thread.start()

    def _stop_conversation(self):
        """Para thread de conversação"""
        self.stop_conversation.set()
        self.is_streaming = False

        # Encerra sessão no destino de áudio
        if self.audio_destination and self.audio_destination.is_connected:
            asyncio.run_coroutine_threadsafe(
                self.audio_destination.end_session(self.session_id, "hangup"),
                self.loop
            )

        if self.conversation_thread:
            self.conversation_thread.join(timeout=2)

    def _conversation_loop(self):
        """Loop principal de conversação com streaming real"""
        self._log("🗣️ Iniciando loop de conversação streaming...")

        # Registra thread no pjlib
        try:
            pj.Endpoint.instance().libRegisterThread("conversation")
        except Exception:
            pass

        # Aguarda mídia estar pronta (reduzido de 500ms para 100ms)
        time.sleep(0.1)

        # Configura playback streaming ANTES dos callbacks
        self._setup_playback_streaming()

        # Configura callbacks ANTES de iniciar sessão
        self._setup_response_callbacks()

        # Inicia sessão no destino de áudio
        if not self._start_audio_session():
            self._log("Falha ao iniciar sessão de áudio", "error")
            return

        # Aguarda greeting terminar (o áudio já está tocando via streaming)
        self._log("⏳ Aguardando greeting terminar...")
        if not self.greeting_finished.wait(timeout=30):
            self._log("Timeout aguardando greeting", "warning")

        # Aguarda playback do greeting terminar
        self._wait_playback_finished()

        # Inicia streaming de captura
        self._start_streaming()

        # Loop principal - mantém thread viva (reduzido de 100ms para 50ms)
        while not self.stop_conversation.is_set():
            time.sleep(0.05)

        # Para streaming
        self._stop_streaming()
        self._log("🗣️ Loop de conversação encerrado")

    def _start_audio_session(self) -> bool:
        """Inicia sessão no destino de áudio"""
        if not self.audio_destination or not self.audio_destination.is_connected:
            self._log("Destino de áudio não conectado", "error")
            return False

        try:
            ci = self.getInfo()
            session_info = SessionInfo(
                session_id=self.session_id,
                call_id=ci.callIdString,
                audio_config=AudioConfig(
                    sample_rate=AUDIO_CONFIG["sample_rate"],
                    channels=AUDIO_CONFIG["channels"],
                    sample_width=AUDIO_CONFIG["sample_width"]
                )
            )
            future = asyncio.run_coroutine_threadsafe(
                self.audio_destination.start_session(session_info),
                self.loop
            )
            result = future.result(timeout=60)
            return result
        except Exception as e:
            self._log(f"Erro ao iniciar sessão de áudio: {e}", "error")
            return False

    def _setup_playback_streaming(self):
        """Configura StreamingPlaybackPort para playback em tempo real"""
        if not self.call_media:
            self._log("call_media não disponível para playback streaming", "warning")
            return

        try:
            # Cria StreamingPlaybackPort (16kHz para PJSUA2)
            self.playback_port = StreamingPlaybackPort(
                session_id=self.session_id,
                sample_rate=16000
            )

            # Configura o port
            clock_rate = 16000
            channel_count = 1
            samples_per_frame = int(clock_rate * AUDIO_CONFIG["frame_duration_ms"] / 1000)
            bits_per_sample = 16

            self.playback_port.createPort(
                f"playback_{self.unique_call_id}",
                clock_rate,
                channel_count,
                samples_per_frame,
                bits_per_sample
            )

            # Conecta playback_port -> call_media (para enviar áudio ao telefone)
            self.playback_port.startTransmit(self.call_media)

            self._log("🔊 Playback streaming configurado")

        except Exception as e:
            self._log(f"Erro ao configurar playback streaming: {e}", "error")
            import traceback
            traceback.print_exc()

    def _wait_playback_finished(self):
        """Aguarda o playback terminar (buffer esvaziar)"""
        if not self.playback_port:
            return

        # Aguarda buffer esvaziar com timeout
        max_wait = 30  # segundos
        check_interval = 0.05  # 50ms
        waited = 0

        while waited < max_wait:
            if self.stop_conversation.is_set():
                break

            if not self.playback_port.has_audio:
                # Buffer vazio - aguarda um pouco mais para garantir que terminou
                time.sleep(0.04)  # Reduzido de 100ms para 40ms
                if not self.playback_port.has_audio:
                    break

            time.sleep(check_interval)
            waited += check_interval

        self.playback_finished.set()
        self.is_playing_response = False

    def _setup_response_callbacks(self):
        """Configura callbacks para receber respostas do AI Agent (streaming real)"""

        def on_response_start(session_id: str, text: str):
            if session_id != self.session_id:
                return
            self._log(f"🤖 Resposta: {text[:50]}...")

            # Marca início do playback
            self.is_playing_response = True
            self.playback_finished.clear()

            # Pausa captura enquanto reproduz resposta
            self._pause_streaming()

        def on_response_audio(session_id: str, audio_data: bytes):
            if session_id != self.session_id:
                return

            # E2E latency - só no primeiro chunk
            if self.speech_end_timestamp > 0 and not self.e2e_recorded:
                e2e = time.time() - self.speech_end_timestamp
                track_e2e_latency(e2e)
                self.e2e_recorded = True
                self._log(f"⏱️ E2E Latency: {e2e*1000:.0f}ms")

            # Tracking para barge-in progress
            self.response_total_bytes += len(audio_data)

            # Envia diretamente para playback streaming (sem acumular!)
            if self.playback_port:
                self.playback_port.add_audio(audio_data)
                self.bytes_transmitted += len(audio_data)

        def on_response_end(session_id: str):
            if session_id != self.session_id:
                return

            self._log(f"🔊 Resposta completa ({self.bytes_transmitted} bytes)")

            # Registra métricas
            track_rtp_transmitted(self.bytes_transmitted)
            self.bytes_transmitted = 0

            # Sinaliza que greeting terminou
            if self.is_first_response:
                self.is_first_response = False
                self.greeting_finished.set()
                self._log("✅ Greeting concluído")

            # Inicia thread para aguardar playback e resumir captura
            threading.Thread(
                target=self._on_playback_complete,
                daemon=True
            ).start()

        self.audio_destination.on_response_start = on_response_start
        self.audio_destination.on_response_audio = on_response_audio
        self.audio_destination.on_response_end = on_response_end

    def _on_playback_complete(self):
        """Chamado quando resposta termina - aguarda buffer esvaziar"""
        self._wait_playback_finished()
        self._resume_streaming()

    def _start_streaming(self):
        """Inicia captura de áudio streaming"""
        if not self.call_media:
            self._log("call_media não disponível para streaming", "warning")
            return

        try:
            # Cria StreamingAudioPort
            self.streaming_port = StreamingAudioPort(
                audio_destination=self.audio_destination,
                session_id=self.session_id,
                loop=self.loop,
                on_speech_end=self._on_speech_end,
                on_speech_start=self._on_speech_start,
            )

            # Configura o port (16kHz, mono, 20ms frames)
            # PJSUA2 usa 16kHz internamente
            clock_rate = 16000
            channel_count = 1
            samples_per_frame = int(clock_rate * AUDIO_CONFIG["frame_duration_ms"] / 1000)
            bits_per_sample = 16

            self.streaming_port.createPort(
                f"stream_{self.unique_call_id}",
                clock_rate,
                channel_count,
                samples_per_frame,
                bits_per_sample
            )

            # Conecta call_media -> streaming_port
            self.call_media.startTransmit(self.streaming_port)

            self.is_streaming = True
            self._log("🎤 Streaming de áudio iniciado")

        except Exception as e:
            self._log(f"Erro ao iniciar streaming: {e}", "error")
            import traceback
            traceback.print_exc()

    def _stop_streaming(self):
        """Para captura de áudio streaming"""
        if self.streaming_port and self.call_media:
            try:
                self.call_media.stopTransmit(self.streaming_port)
            except Exception:
                pass

            try:
                self.streaming_port.stop()
            except Exception:
                pass

        self.is_streaming = False
        self._log("🎤 Streaming de áudio parado")

    def _pause_streaming(self):
        """Pausa envio de áudio mas mantém detecção de fala para barge-in"""
        if self.streaming_port:
            # Modo monitor: detecta fala mas não envia áudio
            self.streaming_port.monitor_mode = True
            self._log("⏸️ Streaming em modo monitor (barge-in ativo)")

    def _resume_streaming(self):
        """Resume o streaming após playback"""
        if self.streaming_port:
            self.streaming_port.monitor_mode = False
            self.streaming_port.is_active = True
            self.streaming_port.reset_vad()
            self.barge_in_triggered.clear()
            self._log("▶️ Streaming resumido")

    def _on_speech_start(self):
        """Callback quando fala é detectada - implementa barge-in"""
        if not self.barge_in_enabled:
            return

        # Se estamos reproduzindo resposta, usuário está interrompendo (barge-in)
        if self.is_playing_response and not self.barge_in_triggered.is_set():
            self._handle_barge_in()

    def _handle_barge_in(self):
        """Trata interrupção do usuário (barge-in)"""
        self.barge_in_triggered.set()

        # Calcula e registra progresso da resposta quando barge-in ocorreu
        if self.response_total_bytes > 0 and self.playback_port:
            # Bytes restantes no buffer = ainda não reproduzidos
            bytes_remaining = len(self.playback_port.audio_buffer)
            bytes_played = self.response_total_bytes - bytes_remaining
            progress = bytes_played / self.response_total_bytes if self.response_total_bytes > 0 else 0.0
            progress = max(0.0, min(1.0, progress))  # Clamp 0-1
            track_barge_in_progress(progress)
            self._log(f"🛑 BARGE-IN: Usuário interrompeu em {progress*100:.0f}% da resposta")
        else:
            self._log("🛑 BARGE-IN: Usuário interrompeu - cancelando playback")

        # Registra métrica
        track_barge_in()

        # Limpa buffer de playback (para de falar imediatamente)
        if self.playback_port:
            self.playback_port.clear()

        # Sinaliza que playback terminou (foi interrompido)
        self.playback_finished.set()
        self.is_playing_response = False

        # Resume streaming normal para capturar o que usuário está dizendo
        if self.streaming_port:
            self.streaming_port.monitor_mode = False
            self.streaming_port.is_active = True
            # NÃO reseta VAD - queremos continuar capturando a fala atual

        self._log("▶️ Captura resumida após barge-in")

    def _on_speech_end(self):
        """Callback quando fim de fala é detectado"""
        # Guarda timestamp para cálculo de E2E latency
        self.speech_end_timestamp = time.time()
        self.e2e_recorded = False

        # Reseta contadores de barge-in progress
        self.response_total_bytes = 0
        self.response_played_bytes = 0

        self._log("🔇 Fim de fala detectado - aguardando resposta")
        # O streaming_port já envia audio.end automaticamente

    def onCallMediaState(self, prm):
        """Estado da mídia mudou"""
        ci = self.getInfo()

        for i, mi in enumerate(ci.media):
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                try:
                    self.call_media = self.getAudioMedia(i)
                    self._log("🎤 Mídia de áudio ativa")
                except Exception as e:
                    self._log(f"Erro ao obter mídia: {e}", "error")
                break

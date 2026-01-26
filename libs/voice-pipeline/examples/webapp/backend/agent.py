"""Voice Agent Session - WebSocket handler usando voice-pipeline.

Usa streaming sentence-level para baixa latência (TTFA ~0.6-0.8s).

Otimizações implementadas:
- TTS Warmup: Elimina cold-start do TTS (auto_warmup=True por padrão)
- Sentence Streaming: LLM e TTS executam em paralelo
- Producer-Consumer: asyncio.Queue conecta LLM→TTS
- msgpack (opcional): Serialização binária ~10x mais rápida que JSON
- Singleton de providers: Modelos compartilhados entre sessões
- Buffers limitados: Previne consumo ilimitado de memória

Features (Phase 7-9):
- Turn-Taking Adaptativo: Silêncio contextual para detecção de fim de turno
- Streaming Granularity: Clause-level para balanço latência/naturalidade
- Interruption Strategy: Backchannel-aware (distingue "uhum" de interrupção real)
- Full-Duplex State: Suporta fala simultânea com decisão inteligente
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional, Union

from fastapi import WebSocket

from voice_pipeline import VoiceAgent
from voice_pipeline.chains import StreamingVoiceChain
from voice_pipeline.interfaces.turn_taking import TurnTakingContext, TurnTakingDecision
from voice_pipeline.interfaces.interruption import (
    InterruptionContext,
    InterruptionDecision,
)

logger = logging.getLogger(__name__)

# Limite de sessões simultâneas
MAX_CONCURRENT_SESSIONS = 3

# Controle de sessões ativas
_active_sessions: set["VoiceAgentSession"] = set()
_sessions_lock = asyncio.Lock()

# Singleton: chain e VAD compartilhados entre sessões
_shared_chain: Optional[StreamingVoiceChain] = None
_shared_vad = None
_shared_chain_lock = asyncio.Lock()

# Configuração de modelos via variáveis de ambiente
LLM_MODEL = os.environ.get("VP_LLM_MODEL", "qwen3:0.6b")
TTS_PROVIDER = os.environ.get("VP_TTS_PROVIDER", "kokoro")
TTS_VOICE = os.environ.get("VP_TTS_VOICE", "pf_dora")

# Limites de buffers
AUDIO_BUFFER_MAX_SIZE = 100  # ~100 chunks de 1024 bytes = ~100KB
VAD_BUFFER_MAX_BYTES = 32768  # 32KB máximo no buffer do VAD
POST_SPEECH_COOLDOWN_MS = 500  # Cooldown após agente falar (evitar echo)
BUFFER_OVERFLOW_LOG_INTERVAL = 50  # Logar warning a cada N overflows


# =============================================================================
# Serialização otimizada (msgpack opcional)
# =============================================================================

def _has_msgpack() -> bool:
    """Check if msgpack is available."""
    try:
        import msgpack
        return True
    except ImportError:
        return False


class WebSocketSerializer:
    """Serializer para WebSocket com suporte a msgpack.

    Usa msgpack se disponível e habilitado, senão usa JSON.
    msgpack é ~10x mais rápido e ~50% menor que JSON.

    Para habilitar msgpack no cliente JavaScript:
    ```javascript
    import msgpack from '@msgpack/msgpack';

    ws.onmessage = (event) => {
        if (event.data instanceof Blob) {
            // Check if it's a msgpack message (starts with specific bytes)
            // or raw audio (PCM16)
            event.data.arrayBuffer().then(buf => {
                try {
                    const data = msgpack.decode(new Uint8Array(buf));
                    handleControlMessage(data);
                } catch {
                    handleAudioData(buf);
                }
            });
        }
    };
    ```
    """

    def __init__(self, use_msgpack: bool = False):
        """Initialize serializer.

        Args:
            use_msgpack: If True, use msgpack for control messages.
                        Requires msgpack installed and client support.
        """
        self.use_msgpack = use_msgpack and _has_msgpack()
        if use_msgpack and not _has_msgpack():
            logger.warning("msgpack solicitado mas não instalado. Usando JSON.")

    async def send_json(self, websocket: WebSocket, data: dict[str, Any]) -> None:
        """Send control message (JSON or msgpack)."""
        if self.use_msgpack:
            import msgpack
            await websocket.send_bytes(msgpack.packb(data, use_bin_type=True))
        else:
            await websocket.send_json(data)


class VoiceAgentSession:
    """Sessão WebSocket para conversação de voz em tempo real.

    Usa VoiceAgent.builder() com streaming=True para baixa latência.

    Arquitetura:
        Audio → ASR → LLM (streaming) → StreamingStrategy → TTS → Audio
                            ↓
                    [chunk pronto (clause/sentence/word)]
                            ↓
                      TTS começa

    Features:
        - Turn-Taking Adaptativo: Silêncio contextual
        - Streaming Granularity: Clause-level (~200-400ms TTFA)
        - Backchannel Detection: "uhum", "sim" não interrompem
        - Full-Duplex: Fala simultânea com decisão inteligente
        - TTS Warmup: Elimina cold-start (~200-500ms economia)
        - msgpack (opcional): Serialização ~10x mais rápida
    """

    def __init__(self, websocket: WebSocket, use_msgpack: bool = False):
        """Initialize voice agent session.

        Args:
            websocket: FastAPI WebSocket connection.
            use_msgpack: If True, use msgpack for control messages.
                        Default: False (JSON for browser compatibility).
        """
        self.websocket = websocket
        self.sample_rate = 16000

        # Serializer (JSON ou msgpack)
        self._serializer = WebSocketSerializer(use_msgpack=use_msgpack)

        # Pipeline compartilhado (singleton)
        self._chain: Optional[StreamingVoiceChain] = None
        self._vad = None
        self._is_listening = False
        # Buffer limitado para evitar consumo ilimitado de memória
        self._audio_buffer: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=AUDIO_BUFFER_MAX_SIZE
        )
        self._speech_started = False
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        # Flag para ignorar áudio durante processamento da resposta
        self._is_processing = False
        # VAD buffer mutável (bytearray evita cópias de bytes imutáveis)
        self._vad_buffer = bytearray()
        # Turn-taking: número de turnos completos na conversação
        self._turn_count = 0
        self._last_agent_response_length = 0
        # Interruption tracking
        self._last_interruption_time = 0.0
        self._barge_in_speech_start = 0.0
        self._backchannel_count = 0
        self._interruption_count = 0
        # Post-speech cooldown (evitar echo do TTS no microfone)
        self._processing_end_time = 0.0
        # Rate-limit de log de buffer overflow
        self._buffer_overflow_count = 0

    async def initialize(self):
        """Inicializa voice agent com streaming de baixa latência.

        Usa singleton para compartilhar modelos entre sessões,
        evitando múltiplas cópias dos modelos na memória.
        """
        global _shared_chain, _shared_vad

        # Verificar limite de sessões
        async with _sessions_lock:
            if len(_active_sessions) >= MAX_CONCURRENT_SESSIONS:
                raise RuntimeError(
                    f"Limite de {MAX_CONCURRENT_SESSIONS} sessões simultâneas atingido"
                )
            _active_sessions.add(self)

        async with _shared_chain_lock:
            if _shared_chain is None:
                # Otimizado para CPU (máxima velocidade, memória mínima):
                # Config via env vars: VP_LLM_MODEL, VP_TTS_PROVIDER, VP_TTS_VOICE
                # Ex: VP_TTS_PROVIDER=piper VP_TTS_VOICE=pt_BR-faber-medium
                #     VP_LLM_MODEL=qwen3:0.6b
                logger.info(
                    f"Inicializando providers compartilhados (primeira sessão)...\n"
                    f"  LLM: {LLM_MODEL}, TTS: {TTS_PROVIDER} ({TTS_VOICE})"
                )

                builder = (
                    VoiceAgent.builder()
                    .asr("faster-whisper", model="base", language="pt",
                         compute_type="int8", vad_filter=True, beam_size=1,
                         vad_parameters={
                             "threshold": 0.5,
                             "min_silence_duration_ms": 250,
                             "speech_pad_ms": 200,
                         })
                    .llm("ollama", model=LLM_MODEL, keep_alive="-1")
                    .tts(TTS_PROVIDER, voice=TTS_VOICE)
                    .vad("silero")
                    .turn_taking("adaptive", base_threshold_ms=600)
                    .streaming_granularity("adaptive", first_chunk_words=3, clause_min_chars=10, language="pt")
                    .interruption("backchannel", language="pt")
                    .system_prompt(
                        "Você é um assistente de voz prestativo. "
                        "Responda de forma MUITO breve (1-2 frases curtas) "
                        "em português brasileiro. "
                        "Seja direto e conciso."
                    )
                    .streaming(True)
                )

                _shared_chain = await builder.build_async()
                _shared_vad = builder._vad

                if hasattr(_shared_chain, 'warmup_time_ms') and _shared_chain.warmup_time_ms:
                    logger.info(f"TTS warmup completado em {_shared_chain.warmup_time_ms:.1f}ms")

                logger.info("Providers compartilhados prontos")
                logger.info(
                    f"Strategies: "
                    f"turn_taking={type(_shared_chain.turn_taking_controller).__name__ if _shared_chain.turn_taking_controller else 'None'}, "
                    f"streaming={_shared_chain.streaming_strategy.name if _shared_chain.streaming_strategy else 'SentenceDefault'}, "
                    f"interruption={_shared_chain.interruption_strategy.name if _shared_chain.interruption_strategy else 'None'}"
                )
            else:
                logger.info("Reutilizando providers compartilhados")

        self._chain = _shared_chain
        self._vad = _shared_vad

        # Enviar informações sobre strategies ativas ao frontend
        await self._send_strategy_info()

        logger.info("Voice agent pronto (StreamingVoiceChain com otimizações)")

    async def _send_strategy_info(self):
        """Envia informações sobre as strategies ativas ao frontend."""
        chain = self._chain
        if not chain:
            return

        info = {
            "type": "strategy_info",
            "turn_taking": type(chain.turn_taking_controller).__name__ if chain.turn_taking_controller else "FixedSilence",
            "streaming": chain.streaming_strategy.name if chain.streaming_strategy else "SentenceStreamingStrategy(sentence)",
            "interruption": chain.interruption_strategy.name if chain.interruption_strategy else "ImmediateInterruption",
        }
        await self._serializer.send_json(self.websocket, info)

    async def configure(self, sample_rate: int = 16000, language: str = "pt"):
        """Atualiza configuração."""
        self.sample_rate = sample_rate

    async def start_listening(self):
        """Inicia escuta."""
        self._is_listening = True
        self._speech_started = False
        await self._send_status("listening")

    async def stop_listening(self):
        """Para escuta."""
        self._is_listening = False
        await self._send_status("idle")

    async def process_audio(self, audio_chunk: bytes):
        """Processa chunk de áudio do cliente.

        Usa TurnTakingController plugável para decidir quando o
        turno do usuário terminou. O controller recebe contexto
        completo (VAD, silêncio, duração da fala) e retorna uma
        decisão (CONTINUE, END_OF_TURN, BARGE_IN).

        Quando o agente está falando (is_processing=True), o VAD
        continua rodando para detectar barge-in. A InterruptionStrategy
        decide se é um backchannel ("uhum") ou interrupção real.

        Silero VAD espera chunks de 512 samples (para 16kHz).
        Frontend envia chunks maiores, então dividimos aqui.
        """
        if not self._is_listening or not self._vad:
            return

        # Cooldown pós-processamento: ignorar áudio para evitar echo
        if self._processing_end_time > 0:
            elapsed_ms = (time.time() - self._processing_end_time) * 1000
            if elapsed_ms < POST_SPEECH_COOLDOWN_MS:
                return  # Ainda no cooldown, descartar áudio (provável echo)
            else:
                self._processing_end_time = 0.0  # Cooldown expirou

        # Silero VAD espera 512 samples para 16kHz (1024 bytes em PCM16)
        VAD_CHUNK_SIZE = 512 * 2  # 512 samples * 2 bytes/sample

        # Acumular no buffer de VAD (bytearray mutável - sem cópias)
        self._vad_buffer.extend(audio_chunk)

        # Proteger contra acúmulo excessivo (descarta dados antigos)
        if len(self._vad_buffer) > VAD_BUFFER_MAX_BYTES:
            excess = len(self._vad_buffer) - VAD_BUFFER_MAX_BYTES
            del self._vad_buffer[:excess]
            logger.warning(f"VAD buffer overflow: descartados {excess} bytes")

        # Processar chunks de tamanho correto para o VAD
        while len(self._vad_buffer) >= VAD_CHUNK_SIZE:
            vad_chunk = bytes(self._vad_buffer[:VAD_CHUNK_SIZE])
            del self._vad_buffer[:VAD_CHUNK_SIZE]

            vad_event = await self._vad.process(vad_chunk, self.sample_rate)

            # === Modo Full-Duplex: VAD roda mesmo durante processamento ===
            if self._is_processing:
                await self._handle_barge_in(vad_event)
                continue

            # === Modo normal: coletar áudio e detectar fim de turno ===
            if vad_event.is_speech:
                if not self._speech_started:
                    self._speech_started = True
                    self._speech_start_time = time.time()
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_start"})

                self._last_speech_time = time.time()
                # put_nowait com fallback: descarta chunk mais antigo se buffer cheio
                if self._audio_buffer.full():
                    try:
                        self._audio_buffer.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._buffer_overflow_count += 1
                    if self._buffer_overflow_count % BUFFER_OVERFLOW_LOG_INTERVAL == 1:
                        logger.warning(
                            f"Audio buffer cheio: descartados {self._buffer_overflow_count} chunks até agora"
                        )
                await self._audio_buffer.put(vad_chunk)

            # Consultar TurnTakingController para decisão
            turn_controller = (
                self._chain.turn_taking_controller if self._chain else None
            )
            if turn_controller and self._speech_started:
                now = time.time()
                silence_ms = (now - self._last_speech_time) * 1000 if not vad_event.is_speech else 0.0
                speech_ms = (self._last_speech_time - self._speech_start_time) * 1000

                context = TurnTakingContext(
                    is_speech=vad_event.is_speech,
                    speech_confidence=vad_event.confidence,
                    silence_duration_ms=silence_ms,
                    speech_duration_ms=speech_ms,
                    agent_is_speaking=self._is_processing,
                    conversation_turn_count=self._turn_count,
                    last_agent_response_length=self._last_agent_response_length,
                    sample_rate=self.sample_rate,
                )

                decision = await turn_controller.decide(context)

                if decision == TurnTakingDecision.END_OF_TURN:
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_end"})
                    turn_controller.reset()
                    await self._process_speech()
                    self._speech_started = False
                elif decision == TurnTakingDecision.BARGE_IN:
                    await self.interrupt()

            elif not turn_controller and self._speech_started and not vad_event.is_speech:
                # Fallback: silêncio fixo 800ms se não há controller
                silence_ms = (time.time() - self._last_speech_time) * 1000
                if silence_ms >= 800:
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_end"})
                    await self._process_speech()
                    self._speech_started = False

    async def _handle_barge_in(self, vad_event):
        """Trata barge-in usando InterruptionStrategy.

        Quando o agente está falando e o VAD detecta fala do usuário,
        consulta a InterruptionStrategy para decidir:
        - IGNORE: Ruído ou fala muito curta, ignorar
        - BACKCHANNEL: "uhum", "ok" — agente continua falando
        - INTERRUPT_IMMEDIATE: Parar TTS imediatamente
        - INTERRUPT_GRACEFUL: Terminar chunk atual e parar
        """
        interruption_strategy = (
            self._chain.interruption_strategy if self._chain else None
        )

        if not interruption_strategy:
            # Fallback: comportamento antigo (interrompe imediatamente)
            if vad_event.is_speech:
                if not self._barge_in_speech_start:
                    self._barge_in_speech_start = time.time()
                speech_ms = (time.time() - self._barge_in_speech_start) * 1000
                if speech_ms >= 200:
                    await self.interrupt()
                    self._barge_in_speech_start = 0.0
            else:
                self._barge_in_speech_start = 0.0
            return

        # Rastrear início de fala durante barge-in
        if vad_event.is_speech:
            if not self._barge_in_speech_start:
                self._barge_in_speech_start = time.time()
                # Notificar frontend que entrou em modo full-duplex
                await self._serializer.send_json(self.websocket, {
                    "type": "full_duplex",
                    "event": "start",
                })
        else:
            if self._barge_in_speech_start:
                # Fala parou durante barge-in
                self._barge_in_speech_start = 0.0
                await self._serializer.send_json(self.websocket, {
                    "type": "full_duplex",
                    "event": "end",
                })
            return

        # Calcular contexto para InterruptionStrategy
        now = time.time()
        speech_duration_ms = (now - self._barge_in_speech_start) * 1000
        time_since_last = (
            (now - self._last_interruption_time) * 1000
            if self._last_interruption_time > 0 else 0.0
        )

        context = InterruptionContext(
            user_is_speaking=vad_event.is_speech,
            user_speech_duration_ms=speech_duration_ms,
            user_speech_confidence=vad_event.confidence,
            agent_is_speaking=True,
            time_since_last_interruption_ms=time_since_last,
            conversation_turn_count=self._turn_count,
            agent_response_text="",  # Não temos acesso fácil aqui
        )

        decision = await interruption_strategy.decide(context)

        if decision == InterruptionDecision.IGNORE:
            return

        elif decision == InterruptionDecision.BACKCHANNEL:
            self._backchannel_count += 1
            # Notificar frontend do backchannel (agente continua falando)
            await self._serializer.send_json(self.websocket, {
                "type": "backchannel",
                "count": self._backchannel_count,
            })
            logger.debug(f"Backchannel #{self._backchannel_count} detectado")
            # Resetar timer de fala para evitar re-trigger
            self._barge_in_speech_start = 0.0

        elif decision in (
            InterruptionDecision.INTERRUPT_IMMEDIATE,
            InterruptionDecision.INTERRUPT_GRACEFUL,
        ):
            self._interruption_count += 1
            self._last_interruption_time = time.time()
            interruption_strategy.on_interruption_executed(decision)

            # Notificar tipo de interrupção
            await self._serializer.send_json(self.websocket, {
                "type": "interruption",
                "mode": decision.value,
                "count": self._interruption_count,
            })
            logger.info(
                f"Interrupção #{self._interruption_count} ({decision.value}): "
                f"speech={speech_duration_ms:.0f}ms"
            )

            await self.interrupt()
            self._barge_in_speech_start = 0.0

    async def _process_speech(self):
        """Processa fala coletada com streaming de baixa latência."""
        self._is_processing = True
        await self._send_status("processing")

        try:
            # Coletar áudio
            chunks = []
            while not self._audio_buffer.empty():
                chunks.append(await self._audio_buffer.get())

            if not chunks:
                await self._send_status("listening")
                return

            audio_data = b"".join(chunks)

            # Stream áudio de resposta (baixa latência)
            await self._send_status("speaking")
            first_audio = True

            async for audio_chunk in self._chain.astream(audio_data):
                # Notificar primeiro áudio
                if first_audio:
                    first_audio = False
                    # Enviar métricas parciais
                    if self._chain.metrics and self._chain.metrics.ttfa:
                        await self._serializer.send_json(self.websocket, {
                            "type": "metrics",
                            "ttfa": round(self._chain.metrics.ttfa, 3),
                        })

                await self.websocket.send_bytes(audio_chunk.data)

            # Enviar métricas finais
            if self._chain.metrics:
                metrics = self._chain.metrics
                strategy_name = (
                    self._chain.streaming_strategy.name
                    if self._chain.streaming_strategy
                    else "SentenceStreamer"
                )
                await self._serializer.send_json(self.websocket, {
                    "type": "metrics",
                    "ttft": round(metrics.ttft, 3) if metrics.ttft else None,
                    "ttfa": round(metrics.ttfa, 3) if metrics.ttfa else None,
                    "total": round(metrics.total_time, 3) if metrics.total_time else None,
                    "sentences": metrics.sentences_count,
                    "tokens": metrics.tokens_count,
                    "rtf": round(metrics.rtf, 2) if metrics.rtf else None,
                    "streaming_strategy": strategy_name,
                })

            # Resposta de texto + atualizar contexto para turn-taking
            if self._chain.messages:
                last = self._chain.messages[-1]
                if last.get("role") == "assistant":
                    response_text = last.get("content", "")
                    await self._serializer.send_json(self.websocket, {
                        "type": "response",
                        "text": response_text,
                    })
                    # Atualizar contexto para o TurnTakingController
                    self._turn_count += 1
                    self._last_agent_response_length = len(response_text)

        except Exception as e:
            logger.error(f"Erro no processamento de fala: {e}", exc_info=True)
            try:
                await self._serializer.send_json(self.websocket, {"type": "error", "message": str(e)})
            except Exception:
                logger.debug("WebSocket já desconectado, não foi possível enviar erro")

        finally:
            self._is_processing = False
            self._vad_buffer.clear()
            self._barge_in_speech_start = 0.0
            self._speech_started = False
            # Ativar cooldown para evitar echo do TTS
            self._processing_end_time = time.time()
            # Drenar audio buffer (evitar processar áudio stale/echo)
            while not self._audio_buffer.empty():
                try:
                    self._audio_buffer.get_nowait()
                except asyncio.QueueEmpty:
                    break
            if self._buffer_overflow_count > 0:
                logger.info(f"Buffer overflow total neste turno: {self._buffer_overflow_count} chunks descartados")
                self._buffer_overflow_count = 0
            try:
                await self._send_status("listening")
            except Exception:
                pass

    async def _send_status(self, state: str):
        """Envia status."""
        await self._serializer.send_json(self.websocket, {"type": "status", "state": state})

    async def interrupt(self):
        """Interrompe resposta (barge-in)."""
        if self._chain:
            self._chain.interrupt()
        self._speech_started = False
        await self._send_status("listening")
        await self._serializer.send_json(self.websocket, {"type": "interrupted"})

    async def reset(self):
        """Reseta conversação."""
        if self._chain:
            self._chain.reset()
        self._vad_buffer.clear()
        self._turn_count = 0
        self._last_agent_response_length = 0
        self._backchannel_count = 0
        self._interruption_count = 0
        self._last_interruption_time = 0.0

    async def cleanup(self):
        """Limpa recursos da sessão.

        Libera buffers e remove a sessão do controle global.
        Os providers compartilhados (chain, vad) NÃO são desconectados
        pois são reutilizados por outras sessões.
        """
        self._is_listening = False
        self._vad_buffer.clear()

        # Drenar audio buffer
        while not self._audio_buffer.empty():
            try:
                self._audio_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Remover do controle de sessões ativas
        async with _sessions_lock:
            _active_sessions.discard(self)
            remaining = len(_active_sessions)

        # Limpar referências locais (sem desconectar o singleton)
        self._chain = None
        self._vad = None

        logger.info(f"Sessão limpa. Sessões ativas restantes: {remaining}")

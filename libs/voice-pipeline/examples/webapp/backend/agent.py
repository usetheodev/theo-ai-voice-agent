"""Voice Agent Session - WebSocket handler usando voice-pipeline.

Usa streaming sentence-level para baixa latência (TTFA ~0.6-0.8s).

Otimizações implementadas:
- TTS Warmup: Elimina cold-start do TTS (auto_warmup=True por padrão)
- Sentence Streaming: LLM e TTS executam em paralelo
- Producer-Consumer: asyncio.Queue conecta LLM→TTS
- msgpack (opcional): Serialização binária ~10x mais rápida que JSON
- Singleton de providers: Modelos compartilhados entre sessões
- Buffers limitados: Previne consumo ilimitado de memória
"""

import asyncio
import logging
import time
from typing import Any, Optional, Union

from fastapi import WebSocket

from voice_pipeline import VoiceAgent
from voice_pipeline.chains import StreamingVoiceChain

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

# Limites de buffers
AUDIO_BUFFER_MAX_SIZE = 100  # ~100 chunks de 1024 bytes = ~100KB
VAD_BUFFER_MAX_BYTES = 32768  # 32KB máximo no buffer do VAD


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
        Audio → ASR → LLM (streaming) → SentenceStreamer → TTS → Audio
                            ↓
                    [sentença pronta]
                            ↓
                      TTS começa

    Otimizações:
        - TTS Warmup: Elimina cold-start (~200-500ms economia)
        - Sentence Streaming: TTFA reduzido de ~2-3s para ~0.6-0.8s
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
        self._last_speech_time = 0.0
        self._silence_threshold_ms = 800
        # VAD buffer mutável (bytearray evita cópias de bytes imutáveis)
        self._vad_buffer = bytearray()

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
                logger.info("Inicializando providers compartilhados (primeira sessão)...")

                builder = (
                    VoiceAgent.builder()
                    .asr("faster-whisper", model="tiny", language="pt",
                         compute_type="int8", vad_filter=True, beam_size=1,
                         vad_parameters={
                             "threshold": 0.5,
                             "min_silence_duration_ms": 250,
                             "speech_pad_ms": 200,
                         })
                    .llm("ollama", model="qwen2.5:0.5b")
                    .tts("kokoro", voice="pf_dora")
                    .vad("silero")
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
            else:
                logger.info("Reutilizando providers compartilhados")

        self._chain = _shared_chain
        self._vad = _shared_vad

        logger.info("Voice agent pronto (StreamingVoiceChain com otimizações)")

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

        Silero VAD espera chunks de 512 samples (para 16kHz).
        Frontend envia chunks maiores, então dividimos aqui.
        """
        if not self._is_listening or not self._vad:
            return

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

            if vad_event.is_speech:
                if not self._speech_started:
                    self._speech_started = True
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_start"})

                self._last_speech_time = time.time()
                # put_nowait com fallback: descarta chunk mais antigo se buffer cheio
                if self._audio_buffer.full():
                    try:
                        self._audio_buffer.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    logger.warning("Audio buffer cheio: descartado chunk antigo")
                await self._audio_buffer.put(vad_chunk)

            elif self._speech_started:
                silence_ms = (time.time() - self._last_speech_time) * 1000
                if silence_ms >= self._silence_threshold_ms:
                    await self._serializer.send_json(self.websocket, {"type": "vad", "event": "speech_end"})
                    await self._process_speech()
                    self._speech_started = False

    async def _process_speech(self):
        """Processa fala coletada com streaming de baixa latência."""
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
                await self._serializer.send_json(self.websocket, {
                    "type": "metrics",
                    "ttft": round(metrics.ttft, 3) if metrics.ttft else None,
                    "ttfa": round(metrics.ttfa, 3) if metrics.ttfa else None,
                    "total": round(metrics.total_time, 3) if metrics.total_time else None,
                    "sentences": metrics.sentences_count,
                    "tokens": metrics.tokens_count,
                    "rtf": round(metrics.rtf, 2) if metrics.rtf else None,
                })

            # Resposta de texto
            if self._chain.messages:
                last = self._chain.messages[-1]
                if last.get("role") == "assistant":
                    await self._serializer.send_json(self.websocket, {
                        "type": "response",
                        "text": last.get("content", "")
                    })

        except Exception as e:
            logger.error(f"Erro: {e}", exc_info=True)
            await self._serializer.send_json(self.websocket, {"type": "error", "message": str(e)})

        finally:
            await self._send_status("listening")

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

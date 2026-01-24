"""Voice Agent Session - WebSocket handler usando voice-pipeline.

Usa streaming sentence-level para baixa latência (TTFA ~0.6-0.8s).
"""

import asyncio
import logging
import time
from typing import Optional, Union

from fastapi import WebSocket

from voice_pipeline import VoiceAgent
from voice_pipeline.chains import StreamingVoiceChain

logger = logging.getLogger(__name__)


class VoiceAgentSession:
    """Sessão WebSocket para conversação de voz em tempo real.

    Usa VoiceAgent.builder() com streaming=True para baixa latência.

    Arquitetura:
        Audio → ASR → LLM (streaming) → SentenceStreamer → TTS → Audio
                            ↓
                    [sentença pronta]
                            ↓
                      TTS começa
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.sample_rate = 16000

        # Pipeline será criado no initialize()
        self._chain: Optional[StreamingVoiceChain] = None
        self._vad = None
        self._is_listening = False
        self._audio_buffer: asyncio.Queue[bytes] = asyncio.Queue()
        self._speech_started = False
        self._last_speech_time = 0.0
        self._silence_threshold_ms = 800

    async def initialize(self):
        """Inicializa voice agent com streaming de baixa latência."""
        logger.info("Inicializando voice agent (streaming mode)...")

        # Criar pipeline com STREAMING para baixa latência
        builder = (
            VoiceAgent.builder()
            .asr("whisper", model="base", language="pt")
            .llm("ollama", model="qwen2.5:0.5b")
            .tts("kokoro", voice="pf_dora")
            .vad("silero")
            .system_prompt(
                "Você é um assistente de voz prestativo. "
                "Responda de forma concisa em português brasileiro."
            )
            .streaming(True)  # Baixa latência!
        )

        # Build e conecta todos os providers
        self._chain = await builder.build_async()

        # Guardar referência ao VAD para detecção de fala
        self._vad = builder._vad

        logger.info("Voice agent pronto (StreamingVoiceChain)")

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
        """Processa chunk de áudio do cliente."""
        if not self._is_listening or not self._vad:
            return

        vad_event = await self._vad.process(audio_chunk, self.sample_rate)

        if vad_event.is_speech:
            if not self._speech_started:
                self._speech_started = True
                await self.websocket.send_json({"type": "vad", "event": "speech_start"})

            self._last_speech_time = time.time()
            await self._audio_buffer.put(audio_chunk)

        elif self._speech_started:
            silence_ms = (time.time() - self._last_speech_time) * 1000
            if silence_ms >= self._silence_threshold_ms:
                await self.websocket.send_json({"type": "vad", "event": "speech_end"})
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
                        await self.websocket.send_json({
                            "type": "metrics",
                            "ttfa": round(self._chain.metrics.ttfa, 3),
                        })

                await self.websocket.send_bytes(audio_chunk.data)

            # Enviar métricas finais
            if self._chain.metrics:
                metrics = self._chain.metrics
                await self.websocket.send_json({
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
                    await self.websocket.send_json({
                        "type": "response",
                        "text": last.get("content", "")
                    })

        except Exception as e:
            logger.error(f"Erro: {e}", exc_info=True)
            await self.websocket.send_json({"type": "error", "message": str(e)})

        finally:
            await self._send_status("listening")

    async def _send_status(self, state: str):
        """Envia status."""
        await self.websocket.send_json({"type": "status", "state": state})

    async def interrupt(self):
        """Interrompe resposta (barge-in)."""
        if self._chain:
            self._chain.interrupt()
        self._speech_started = False
        await self._send_status("listening")
        await self.websocket.send_json({"type": "interrupted"})

    async def reset(self):
        """Reseta conversação."""
        if self._chain:
            self._chain.reset()

    async def cleanup(self):
        """Limpa recursos."""
        while not self._audio_buffer.empty():
            try:
                self._audio_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

"""Voice Agent Session - WebSocket handler usando voice-pipeline."""

import asyncio
import logging
import time
from typing import Optional

from fastapi import WebSocket

from voice_pipeline import (
    WhisperASR, OllamaLLM, KokoroTTS, SileroVAD,
    ConversationChain, ConversationBufferMemory,
)

logger = logging.getLogger(__name__)


class VoiceAgentSession:
    """Sessão WebSocket para conversação de voz em tempo real."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.sample_rate = 16000
        self.language = "pt"
        self.system_prompt = (
            "Você é um assistente de voz prestativo. "
            "Responda de forma concisa em português brasileiro."
        )

        self._chain: Optional[ConversationChain] = None
        self._vad: Optional[SileroVAD] = None
        self._is_listening = False
        self._audio_buffer: asyncio.Queue[bytes] = asyncio.Queue()
        self._speech_started = False
        self._last_speech_time = 0.0
        self._silence_threshold_ms = 800

    async def initialize(self):
        """Inicializa providers e chain."""
        logger.info("Inicializando voice agent...")

        # Providers
        asr = WhisperASR(model="base", language=self.language)
        llm = OllamaLLM(model="qwen2.5:0.5b")
        tts = KokoroTTS(voice="pf_dora")
        self._vad = SileroVAD()

        await asr.connect()
        await llm.connect()
        await tts.connect()
        await self._vad.connect()

        # Chain
        self._chain = ConversationChain(
            asr=asr,
            llm=llm,
            tts=tts,
            vad=self._vad,
            system_prompt=self.system_prompt,
            language=self.language,
            tts_voice="pf_dora",
            memory=ConversationBufferMemory(max_messages=20),
            enable_barge_in=True,
        )

        logger.info("Voice agent pronto")

    async def configure(self, sample_rate: int = 16000, language: str = "pt"):
        """Atualiza configuração."""
        self.sample_rate = sample_rate
        self.language = language

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
        """Processa fala coletada."""
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

            # Transcrever
            transcription = await self._chain.asr.ainvoke(audio_data)
            if not transcription.text.strip():
                await self._send_status("listening")
                return

            await self.websocket.send_json({
                "type": "transcript",
                "text": transcription.text,
                "is_final": True
            })

            # Gerar resposta
            await self._send_status("speaking")

            async for audio_chunk in self._chain.astream(audio_data):
                await self.websocket.send_bytes(audio_chunk.data)

            # Resposta final
            if self._chain.messages:
                last = self._chain.messages[-1]
                if last.get("role") == "assistant":
                    await self.websocket.send_json({
                        "type": "response",
                        "text": last.get("content", "")
                    })

        except Exception as e:
            logger.error(f"Erro: {e}")
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

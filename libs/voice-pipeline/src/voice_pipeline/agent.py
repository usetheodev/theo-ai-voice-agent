"""VoiceAgent - API simples estilo LangChain para agentes de voz.

Exemplo de uso:

    # Uma linha
    agent = VoiceAgent.local()
    response = await agent.chat("Olá!")

    # Builder fluente
    agent = (
        VoiceAgent.builder()
        .asr("whisper", model="base")
        .llm("ollama", model="qwen2.5:0.5b")
        .tts("kokoro", voice="pf_dora")
        .system_prompt("Você é um assistente...")
        .build()
    )

    # Usar
    response = await agent.chat("Olá!")       # Texto -> Texto
    audio = await agent.speak("Olá!")         # Texto -> Áudio
    audio = await agent.process(audio_bytes)  # Áudio -> Áudio
    await agent.conversation()                 # Loop interativo
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Optional, Union

from voice_pipeline.interfaces import (
    ASRInterface,
    LLMInterface,
    TTSInterface,
    VADInterface,
    AudioChunk,
)
from voice_pipeline.memory import ConversationBufferMemory, VoiceMemory

logger = logging.getLogger(__name__)


@dataclass
class VoiceAgentConfig:
    """Configuração do VoiceAgent."""

    system_prompt: str = "Você é um assistente de voz prestativo. Responda de forma concisa."
    language: str = "pt"
    max_messages: int = 20
    temperature: float = 0.7

    # ASR
    asr_provider: str = "whisper"
    asr_model: str = "base"

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:0.5b"

    # TTS
    tts_provider: str = "kokoro"
    tts_voice: str = "pf_dora"

    # VAD
    vad_provider: str = "silero"
    vad_enabled: bool = True


class VoiceAgent:
    """Agente de voz com API simples estilo LangChain.

    Exemplo:
        >>> agent = VoiceAgent.local()
        >>> response = await agent.chat("Olá, como você está?")
        >>> print(response)
        "Olá! Estou bem, obrigado por perguntar!"

        >>> audio = await agent.speak("Bom dia!")
        >>> play_audio(audio)

        >>> response_audio = await agent.process(user_audio)
        >>> play_audio(response_audio)
    """

    def __init__(
        self,
        asr: Optional[ASRInterface] = None,
        llm: Optional[LLMInterface] = None,
        tts: Optional[TTSInterface] = None,
        vad: Optional[VADInterface] = None,
        memory: Optional[VoiceMemory] = None,
        system_prompt: Optional[str] = None,
        language: str = "pt",
        config: Optional[VoiceAgentConfig] = None,
    ):
        """Inicializa o VoiceAgent.

        Args:
            asr: Provider ASR (speech-to-text).
            llm: Provider LLM (language model).
            tts: Provider TTS (text-to-speech).
            vad: Provider VAD (voice activity detection).
            memory: Memória de conversação.
            system_prompt: Prompt do sistema.
            language: Idioma (default: "pt").
            config: Configuração completa.
        """
        self._config = config or VoiceAgentConfig()

        self._asr = asr
        self._llm = llm
        self._tts = tts
        self._vad = vad
        self._memory = memory or ConversationBufferMemory(
            max_messages=self._config.max_messages
        )
        self._system_prompt = system_prompt or self._config.system_prompt
        self._language = language

        self._connected = False
        self._messages: list[dict[str, str]] = []

    # =========================================================================
    # Factory Methods (Presets)
    # =========================================================================

    @classmethod
    def local(
        cls,
        system_prompt: Optional[str] = None,
        language: str = "pt",
        asr_model: str = "base",
        llm_model: str = "qwen2.5:0.5b",
        tts_voice: str = "pf_dora",
    ) -> "VoiceAgent":
        """Cria agente com providers locais (Whisper + Ollama + Kokoro).

        Args:
            system_prompt: Prompt do sistema.
            language: Idioma.
            asr_model: Modelo Whisper (tiny, base, small, medium, large).
            llm_model: Modelo Ollama.
            tts_voice: Voz Kokoro.

        Returns:
            VoiceAgent configurado com providers locais.

        Example:
            >>> agent = VoiceAgent.local()
            >>> await agent.connect()
            >>> response = await agent.chat("Olá!")
        """
        from voice_pipeline.providers.asr import WhisperCppASRProvider
        from voice_pipeline.providers.llm import OllamaLLMProvider
        from voice_pipeline.providers.tts import KokoroTTSProvider
        from voice_pipeline.providers.vad import SileroVADProvider

        return cls(
            asr=WhisperCppASRProvider(model=asr_model, language=language),
            llm=OllamaLLMProvider(model=llm_model),
            tts=KokoroTTSProvider(voice=tts_voice),
            vad=SileroVADProvider(),
            system_prompt=system_prompt,
            language=language,
        )

    @classmethod
    def openai(
        cls,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        language: str = "pt",
        asr_model: str = "whisper-1",
        llm_model: str = "gpt-4o-mini",
        tts_voice: str = "alloy",
    ) -> "VoiceAgent":
        """Cria agente com providers OpenAI.

        Args:
            api_key: OpenAI API key (ou usa OPENAI_API_KEY env).
            system_prompt: Prompt do sistema.
            language: Idioma.
            asr_model: Modelo ASR.
            llm_model: Modelo LLM.
            tts_voice: Voz TTS.

        Returns:
            VoiceAgent configurado com providers OpenAI.
        """
        from voice_pipeline.providers.asr import OpenAIASRProvider
        from voice_pipeline.providers.llm import OpenAILLMProvider
        from voice_pipeline.providers.tts import OpenAITTSProvider

        return cls(
            asr=OpenAIASRProvider(api_key=api_key, model=asr_model),
            llm=OpenAILLMProvider(api_key=api_key, model=llm_model),
            tts=OpenAITTSProvider(api_key=api_key, voice=tts_voice),
            system_prompt=system_prompt,
            language=language,
        )

    @classmethod
    def builder(cls) -> "VoiceAgentBuilder":
        """Retorna um builder para configuração fluente.

        Example:
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .asr("whisper", model="base")
            ...     .llm("ollama", model="qwen2.5:0.5b")
            ...     .tts("kokoro", voice="pf_dora")
            ...     .system_prompt("Você é um assistente...")
            ...     .build()
            ... )
        """
        return VoiceAgentBuilder()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> "VoiceAgent":
        """Conecta todos os providers (baixa modelos se necessário).

        Returns:
            Self para encadeamento.

        Example:
            >>> agent = VoiceAgent.local()
            >>> await agent.connect()
        """
        if self._connected:
            return self

        logger.info("Conectando providers...")

        if self._asr:
            await self._asr.connect()
            logger.info(f"  ASR: {self._asr}")

        if self._llm:
            await self._llm.connect()
            logger.info(f"  LLM: {self._llm}")

        if self._tts:
            await self._tts.connect()
            logger.info(f"  TTS: {self._tts}")

        if self._vad:
            try:
                await self._vad.connect()
                logger.info(f"  VAD: {self._vad}")
            except Exception as e:
                logger.warning(f"  VAD não disponível: {e}")
                self._vad = None

        self._connected = True
        logger.info("Agente pronto!")

        return self

    async def disconnect(self) -> None:
        """Desconecta todos os providers."""
        if self._asr and hasattr(self._asr, 'disconnect'):
            await self._asr.disconnect()
        if self._llm and hasattr(self._llm, 'disconnect'):
            await self._llm.disconnect()
        if self._tts and hasattr(self._tts, 'disconnect'):
            await self._tts.disconnect()
        if self._vad and hasattr(self._vad, 'disconnect'):
            await self._vad.disconnect()
        self._connected = False

    async def __aenter__(self) -> "VoiceAgent":
        """Context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        await self.disconnect()

    # =========================================================================
    # Core Methods
    # =========================================================================

    async def chat(self, text: str) -> str:
        """Envia texto e recebe resposta em texto.

        Args:
            text: Mensagem do usuário.

        Returns:
            Resposta do assistente.

        Example:
            >>> response = await agent.chat("Qual é a capital do Brasil?")
            >>> print(response)
            "A capital do Brasil é Brasília."
        """
        if not self._connected:
            await self.connect()

        if not self._llm:
            raise RuntimeError("LLM não configurado")

        # Adiciona mensagem do usuário
        self._messages.append({"role": "user", "content": text})

        # Gera resposta
        response = ""
        async for chunk in self._llm.generate_stream(
            messages=self._messages,
            system_prompt=self._system_prompt,
            temperature=self._config.temperature,
        ):
            response += chunk.text

        # Adiciona resposta ao histórico
        self._messages.append({"role": "assistant", "content": response})

        # Limita histórico
        if len(self._messages) > self._config.max_messages * 2:
            self._messages = self._messages[-self._config.max_messages * 2:]

        return response

    async def chat_stream(self, text: str) -> AsyncIterator[str]:
        """Envia texto e recebe resposta em streaming.

        Args:
            text: Mensagem do usuário.

        Yields:
            Chunks de texto da resposta.

        Example:
            >>> async for chunk in agent.chat_stream("Conte uma história"):
            ...     print(chunk, end="", flush=True)
        """
        if not self._connected:
            await self.connect()

        if not self._llm:
            raise RuntimeError("LLM não configurado")

        self._messages.append({"role": "user", "content": text})

        response = ""
        async for chunk in self._llm.generate_stream(
            messages=self._messages,
            system_prompt=self._system_prompt,
            temperature=self._config.temperature,
        ):
            response += chunk.text
            yield chunk.text

        self._messages.append({"role": "assistant", "content": response})

    async def speak(self, text: str) -> bytes:
        """Converte texto em áudio.

        Args:
            text: Texto para sintetizar.

        Returns:
            Áudio em bytes (PCM16, 24kHz, mono).

        Example:
            >>> audio = await agent.speak("Bom dia!")
            >>> with open("output.wav", "wb") as f:
            ...     write_wav(f, audio, 24000)
        """
        if not self._connected:
            await self.connect()

        if not self._tts:
            raise RuntimeError("TTS não configurado")

        chunks = []
        async for chunk in self._tts.synthesize_stream(
            self._text_iterator(text),
            voice=self._config.tts_voice,
        ):
            chunks.append(chunk.data)

        return b"".join(chunks)

    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        """Converte texto em áudio com streaming.

        Args:
            text: Texto para sintetizar.

        Yields:
            Chunks de áudio.
        """
        if not self._connected:
            await self.connect()

        if not self._tts:
            raise RuntimeError("TTS não configurado")

        async for chunk in self._tts.synthesize_stream(
            self._text_iterator(text),
            voice=self._config.tts_voice,
        ):
            yield chunk.data

    async def listen(self, audio: bytes) -> str:
        """Converte áudio em texto.

        Args:
            audio: Áudio em bytes (PCM16, 16kHz, mono).

        Returns:
            Texto transcrito.

        Example:
            >>> text = await agent.listen(audio_bytes)
            >>> print(text)
            "Olá, como você está?"
        """
        if not self._connected:
            await self.connect()

        if not self._asr:
            raise RuntimeError("ASR não configurado")

        result = await self._asr.ainvoke(audio)
        return result.text

    async def process(self, audio: bytes) -> bytes:
        """Processa áudio completo: ASR -> LLM -> TTS.

        Args:
            audio: Áudio de entrada (PCM16, 16kHz, mono).

        Returns:
            Áudio de resposta (PCM16, 24kHz, mono).

        Example:
            >>> response_audio = await agent.process(user_audio)
            >>> play_audio(response_audio)
        """
        if not self._connected:
            await self.connect()

        # ASR: Áudio -> Texto
        user_text = await self.listen(audio)
        if not user_text.strip():
            return b""

        logger.info(f"Usuário: {user_text}")

        # LLM: Texto -> Resposta
        response_text = await self.chat(user_text)
        logger.info(f"Assistente: {response_text}")

        # TTS: Resposta -> Áudio
        response_audio = await self.speak(response_text)

        return response_audio

    async def process_stream(self, audio: bytes) -> AsyncIterator[bytes]:
        """Processa áudio com streaming de resposta.

        Args:
            audio: Áudio de entrada.

        Yields:
            Chunks de áudio de resposta.
        """
        if not self._connected:
            await self.connect()

        # ASR
        user_text = await self.listen(audio)
        if not user_text.strip():
            return

        logger.info(f"Usuário: {user_text}")

        # LLM + TTS com streaming
        self._messages.append({"role": "user", "content": user_text})

        response = ""
        sentence_buffer = ""

        async for chunk in self._llm.generate_stream(
            messages=self._messages,
            system_prompt=self._system_prompt,
        ):
            response += chunk.text
            sentence_buffer += chunk.text

            # Quando completar uma sentença, sintetiza
            if any(sentence_buffer.rstrip().endswith(p) for p in ".!?"):
                if len(sentence_buffer.strip()) > 10:
                    async for audio_chunk in self._tts.synthesize_stream(
                        self._text_iterator(sentence_buffer),
                    ):
                        yield audio_chunk.data
                    sentence_buffer = ""

        # Sintetiza resto
        if sentence_buffer.strip():
            async for audio_chunk in self._tts.synthesize_stream(
                self._text_iterator(sentence_buffer),
            ):
                yield audio_chunk.data

        self._messages.append({"role": "assistant", "content": response})
        logger.info(f"Assistente: {response}")

    # =========================================================================
    # Conversation Loop
    # =========================================================================

    async def conversation(
        self,
        on_user_text: Optional[Callable[[str], None]] = None,
        on_assistant_text: Optional[Callable[[str], None]] = None,
        on_audio: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        """Inicia loop de conversação interativo (para terminal).

        Args:
            on_user_text: Callback quando usuário fala.
            on_assistant_text: Callback quando assistente responde.
            on_audio: Callback para tocar áudio.

        Example:
            >>> await agent.conversation()
            Você: Olá!
            Assistente: Olá! Como posso ajudar?
            Você: Tchau
            Assistente: Até logo!
        """
        if not self._connected:
            await self.connect()

        print("\n" + "=" * 50)
        print("Conversação iniciada! Digite 'sair' para encerrar.")
        print("=" * 50 + "\n")

        while True:
            try:
                user_input = input("Você: ").strip()

                if user_input.lower() in ("sair", "exit", "quit", "q"):
                    print("\nAté logo!")
                    break

                if not user_input:
                    continue

                if on_user_text:
                    on_user_text(user_input)

                # Gera resposta
                print("Assistente: ", end="", flush=True)
                response = ""
                async for chunk in self.chat_stream(user_input):
                    print(chunk, end="", flush=True)
                    response += chunk
                print("\n")

                if on_assistant_text:
                    on_assistant_text(response)

                # Sintetiza áudio se callback fornecido
                if on_audio:
                    audio = await self.speak(response)
                    on_audio(audio)

            except KeyboardInterrupt:
                print("\n\nInterrompido!")
                break
            except EOFError:
                break

    # =========================================================================
    # Utilities
    # =========================================================================

    async def _text_iterator(self, text: str) -> AsyncIterator[str]:
        """Converte texto em async iterator."""
        yield text

    def reset(self) -> None:
        """Limpa histórico de conversação."""
        self._messages.clear()
        if self._memory:
            self._memory.clear()

    @property
    def messages(self) -> list[dict[str, str]]:
        """Retorna histórico de mensagens."""
        return self._messages.copy()

    @property
    def is_connected(self) -> bool:
        """Verifica se está conectado."""
        return self._connected

    def __repr__(self) -> str:
        return (
            f"VoiceAgent("
            f"asr={type(self._asr).__name__ if self._asr else None}, "
            f"llm={type(self._llm).__name__ if self._llm else None}, "
            f"tts={type(self._tts).__name__ if self._tts else None}, "
            f"connected={self._connected})"
        )


class VoiceAgentBuilder:
    """Builder fluente para VoiceAgent.

    Example:
        >>> agent = (
        ...     VoiceAgent.builder()
        ...     .asr("whisper", model="base")
        ...     .llm("ollama", model="qwen2.5:0.5b")
        ...     .tts("kokoro", voice="pf_dora")
        ...     .system_prompt("Você é um assistente...")
        ...     .memory(max_messages=20)
        ...     .build()
        ... )
    """

    def __init__(self):
        self._asr = None
        self._llm = None
        self._tts = None
        self._vad = None
        self._system_prompt = None
        self._language = "pt"
        self._memory = None
        self._config = VoiceAgentConfig()

    def asr(
        self,
        provider: str = "whisper",
        model: str = "base",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider ASR.

        Args:
            provider: "whisper" ou "openai".
            model: Modelo a usar.
            **kwargs: Argumentos extras.
        """
        if provider in ("whisper", "whispercpp"):
            from voice_pipeline.providers.asr import WhisperCppASRProvider
            self._asr = WhisperCppASRProvider(model=model, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.asr import OpenAIASRProvider
            self._asr = OpenAIASRProvider(model=model, **kwargs)
        else:
            raise ValueError(f"ASR provider desconhecido: {provider}")
        return self

    def llm(
        self,
        provider: str = "ollama",
        model: str = "qwen2.5:0.5b",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider LLM.

        Args:
            provider: "ollama" ou "openai".
            model: Modelo a usar.
            **kwargs: Argumentos extras.
        """
        if provider == "ollama":
            from voice_pipeline.providers.llm import OllamaLLMProvider
            self._llm = OllamaLLMProvider(model=model, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.llm import OpenAILLMProvider
            self._llm = OpenAILLMProvider(model=model, **kwargs)
        else:
            raise ValueError(f"LLM provider desconhecido: {provider}")
        return self

    def tts(
        self,
        provider: str = "kokoro",
        voice: str = "pf_dora",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider TTS.

        Args:
            provider: "kokoro" ou "openai".
            voice: Voz a usar.
            **kwargs: Argumentos extras.
        """
        if provider == "kokoro":
            from voice_pipeline.providers.tts import KokoroTTSProvider
            self._tts = KokoroTTSProvider(voice=voice, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.tts import OpenAITTSProvider
            self._tts = OpenAITTSProvider(voice=voice, **kwargs)
        else:
            raise ValueError(f"TTS provider desconhecido: {provider}")
        return self

    def vad(
        self,
        provider: str = "silero",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configura provider VAD.

        Args:
            provider: "silero" ou "webrtc".
            **kwargs: Argumentos extras.
        """
        if provider == "silero":
            from voice_pipeline.providers.vad import SileroVADProvider
            self._vad = SileroVADProvider(**kwargs)
        elif provider == "webrtc":
            from voice_pipeline.providers.vad import WebRTCVADProvider
            self._vad = WebRTCVADProvider(**kwargs)
        else:
            raise ValueError(f"VAD provider desconhecido: {provider}")
        return self

    def system_prompt(self, prompt: str) -> "VoiceAgentBuilder":
        """Define o prompt do sistema."""
        self._system_prompt = prompt
        return self

    def language(self, lang: str) -> "VoiceAgentBuilder":
        """Define o idioma."""
        self._language = lang
        return self

    def memory(self, max_messages: int = 20) -> "VoiceAgentBuilder":
        """Configura memória de conversação."""
        self._memory = ConversationBufferMemory(max_messages=max_messages)
        return self

    def temperature(self, temp: float) -> "VoiceAgentBuilder":
        """Define temperatura do LLM."""
        self._config.temperature = temp
        return self

    def build(self) -> VoiceAgent:
        """Constrói o VoiceAgent."""
        return VoiceAgent(
            asr=self._asr,
            llm=self._llm,
            tts=self._tts,
            vad=self._vad,
            memory=self._memory,
            system_prompt=self._system_prompt,
            language=self._language,
            config=self._config,
        )

"""VoiceAgent - Simple LangChain-style API for voice agents.

Usage example:

    # One-liner
    agent = VoiceAgent.local()
    response = await agent.chat("Hello!")

    # Fluent builder
    agent = (
        VoiceAgent.builder()
        .asr("whisper", model="base")
        .llm("ollama", model="qwen2.5:0.5b")
        .tts("kokoro", voice="af_heart")
        .system_prompt("You are an assistant...")
        .build()
    )

    # Use
    response = await agent.chat("Hello!")       # Text -> Text
    audio = await agent.speak("Hello!")         # Text -> Audio
    audio = await agent.process(audio_bytes)    # Audio -> Audio
    await agent.conversation()                   # Interactive loop
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
    """VoiceAgent configuration."""

    system_prompt: str = "You are a helpful voice assistant. Respond concisely."
    language: str = "en"
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
    tts_voice: str = "af_heart"

    # VAD
    vad_provider: str = "silero"
    vad_enabled: bool = True


class VoiceAgent:
    """Voice agent with a simple LangChain-style API.

    Example:
        >>> agent = VoiceAgent.local()
        >>> response = await agent.chat("Hello, how are you?")
        >>> print(response)
        "Hello! I'm doing well, thanks for asking!"

        >>> audio = await agent.speak("Good morning!")
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
        language: str = "en",
        config: Optional[VoiceAgentConfig] = None,
    ):
        """Initialize VoiceAgent.

        Args:
            asr: ASR provider (speech-to-text).
            llm: LLM provider (language model).
            tts: TTS provider (text-to-speech).
            vad: VAD provider (voice activity detection).
            memory: Conversation memory.
            system_prompt: System prompt.
            language: Language code (default: "en").
            config: Full configuration.
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
        language: str = "en",
        asr_model: str = "base",
        llm_model: str = "qwen2.5:0.5b",
        tts_voice: str = "af_heart",
    ) -> "VoiceAgent":
        """Create agent with local providers (Whisper + Ollama + Kokoro).

        Args:
            system_prompt: System prompt.
            language: Language code.
            asr_model: Whisper model (tiny, base, small, medium, large).
            llm_model: Ollama model.
            tts_voice: Kokoro voice.

        Returns:
            VoiceAgent configured with local providers.

        Example:
            >>> agent = VoiceAgent.local()
            >>> await agent.connect()
            >>> response = await agent.chat("Hello!")
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
        language: str = "en",
        asr_model: str = "whisper-1",
        llm_model: str = "gpt-4o-mini",
        tts_voice: str = "alloy",
    ) -> "VoiceAgent":
        """Create agent with OpenAI providers.

        Args:
            api_key: OpenAI API key (or uses OPENAI_API_KEY env).
            system_prompt: System prompt.
            language: Language code.
            asr_model: ASR model.
            llm_model: LLM model.
            tts_voice: TTS voice.

        Returns:
            VoiceAgent configured with OpenAI providers.
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
        """Return a builder for fluent configuration.

        Example:
            >>> agent = (
            ...     VoiceAgent.builder()
            ...     .asr("whisper", model="base")
            ...     .llm("ollama", model="qwen2.5:0.5b")
            ...     .tts("kokoro", voice="af_heart")
            ...     .system_prompt("You are an assistant...")
            ...     .build()
            ... )
        """
        return VoiceAgentBuilder()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> "VoiceAgent":
        """Connect all providers (downloads models if needed).

        Returns:
            Self for chaining.

        Example:
            >>> agent = VoiceAgent.local()
            >>> await agent.connect()
        """
        if self._connected:
            return self

        logger.info("Connecting providers...")

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
                logger.warning(f"  VAD not available: {e}")
                self._vad = None

        self._connected = True
        logger.info("Agent ready!")

        return self

    async def disconnect(self) -> None:
        """Disconnect all providers."""
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
        """Send text and receive text response.

        Args:
            text: User message.

        Returns:
            Assistant response.

        Example:
            >>> response = await agent.chat("What is the capital of France?")
            >>> print(response)
            "The capital of France is Paris."
        """
        if not self._connected:
            await self.connect()

        if not self._llm:
            raise RuntimeError("LLM not configured")

        # Add user message
        self._messages.append({"role": "user", "content": text})

        # Generate response
        response = ""
        async for chunk in self._llm.generate_stream(
            messages=self._messages,
            system_prompt=self._system_prompt,
            temperature=self._config.temperature,
        ):
            response += chunk.text

        # Add response to history
        self._messages.append({"role": "assistant", "content": response})

        # Limit history
        if len(self._messages) > self._config.max_messages * 2:
            self._messages = self._messages[-self._config.max_messages * 2:]

        return response

    async def chat_stream(self, text: str) -> AsyncIterator[str]:
        """Send text and receive streaming response.

        Args:
            text: User message.

        Yields:
            Text chunks of the response.

        Example:
            >>> async for chunk in agent.chat_stream("Tell me a story"):
            ...     print(chunk, end="", flush=True)
        """
        if not self._connected:
            await self.connect()

        if not self._llm:
            raise RuntimeError("LLM not configured")

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
        """Convert text to audio.

        Args:
            text: Text to synthesize.

        Returns:
            Audio bytes (PCM16, 24kHz, mono).

        Example:
            >>> audio = await agent.speak("Good morning!")
            >>> with open("output.wav", "wb") as f:
            ...     write_wav(f, audio, 24000)
        """
        if not self._connected:
            await self.connect()

        if not self._tts:
            raise RuntimeError("TTS not configured")

        chunks = []
        async for chunk in self._tts.synthesize_stream(
            self._text_iterator(text),
            voice=self._config.tts_voice,
        ):
            chunks.append(chunk.data)

        return b"".join(chunks)

    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        """Convert text to audio with streaming.

        Args:
            text: Text to synthesize.

        Yields:
            Audio chunks.
        """
        if not self._connected:
            await self.connect()

        if not self._tts:
            raise RuntimeError("TTS not configured")

        async for chunk in self._tts.synthesize_stream(
            self._text_iterator(text),
            voice=self._config.tts_voice,
        ):
            yield chunk.data

    async def listen(self, audio: bytes) -> str:
        """Convert audio to text.

        Args:
            audio: Audio bytes (PCM16, 16kHz, mono).

        Returns:
            Transcribed text.

        Example:
            >>> text = await agent.listen(audio_bytes)
            >>> print(text)
            "Hello, how are you?"
        """
        if not self._connected:
            await self.connect()

        if not self._asr:
            raise RuntimeError("ASR not configured")

        result = await self._asr.ainvoke(audio)
        return result.text

    async def process(self, audio: bytes) -> bytes:
        """Process full audio: ASR -> LLM -> TTS.

        Args:
            audio: Input audio (PCM16, 16kHz, mono).

        Returns:
            Response audio (PCM16, 24kHz, mono).

        Example:
            >>> response_audio = await agent.process(user_audio)
            >>> play_audio(response_audio)
        """
        if not self._connected:
            await self.connect()

        # ASR: Audio -> Text
        user_text = await self.listen(audio)
        if not user_text.strip():
            return b""

        logger.info(f"User: {user_text}")

        # LLM: Text -> Response
        response_text = await self.chat(user_text)
        logger.info(f"Assistant: {response_text}")

        # TTS: Response -> Audio
        response_audio = await self.speak(response_text)

        return response_audio

    async def process_stream(self, audio: bytes) -> AsyncIterator[bytes]:
        """Process audio with streaming response.

        Args:
            audio: Input audio.

        Yields:
            Response audio chunks.
        """
        if not self._connected:
            await self.connect()

        # ASR
        user_text = await self.listen(audio)
        if not user_text.strip():
            return

        logger.info(f"User: {user_text}")

        # LLM + TTS with streaming
        self._messages.append({"role": "user", "content": user_text})

        response = ""
        sentence_buffer = ""

        async for chunk in self._llm.generate_stream(
            messages=self._messages,
            system_prompt=self._system_prompt,
        ):
            response += chunk.text
            sentence_buffer += chunk.text

            # When a sentence is complete, synthesize
            if any(sentence_buffer.rstrip().endswith(p) for p in ".!?"):
                if len(sentence_buffer.strip()) > 10:
                    async for audio_chunk in self._tts.synthesize_stream(
                        self._text_iterator(sentence_buffer),
                    ):
                        yield audio_chunk.data
                    sentence_buffer = ""

        # Synthesize remainder
        if sentence_buffer.strip():
            async for audio_chunk in self._tts.synthesize_stream(
                self._text_iterator(sentence_buffer),
            ):
                yield audio_chunk.data

        self._messages.append({"role": "assistant", "content": response})
        logger.info(f"Assistant: {response}")

    # =========================================================================
    # Conversation Loop
    # =========================================================================

    async def conversation(
        self,
        on_user_text: Optional[Callable[[str], None]] = None,
        on_assistant_text: Optional[Callable[[str], None]] = None,
        on_audio: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        """Start interactive conversation loop (for terminal).

        Args:
            on_user_text: Callback when user speaks.
            on_assistant_text: Callback when assistant responds.
            on_audio: Callback to play audio.

        Example:
            >>> await agent.conversation()
            You: Hello!
            Assistant: Hello! How can I help?
            You: Bye
            Assistant: Goodbye!
        """
        if not self._connected:
            await self.connect()

        print("\n" + "=" * 50)
        print("Conversation started! Type 'exit' to end.")
        print("=" * 50 + "\n")

        while True:
            try:
                user_input = input("You: ").strip()

                if user_input.lower() in ("exit", "quit", "q"):
                    print("\nGoodbye!")
                    break

                if not user_input:
                    continue

                if on_user_text:
                    on_user_text(user_input)

                # Generate response
                print("Assistant: ", end="", flush=True)
                response = ""
                async for chunk in self.chat_stream(user_input):
                    print(chunk, end="", flush=True)
                    response += chunk
                print("\n")

                if on_assistant_text:
                    on_assistant_text(response)

                # Synthesize audio if callback provided
                if on_audio:
                    audio = await self.speak(response)
                    on_audio(audio)

            except KeyboardInterrupt:
                print("\n\nInterrupted!")
                break
            except EOFError:
                break

    # =========================================================================
    # Utilities
    # =========================================================================

    async def _text_iterator(self, text: str) -> AsyncIterator[str]:
        """Convert text to async iterator."""
        yield text

    def reset(self) -> None:
        """Clear conversation history."""
        self._messages.clear()
        if self._memory:
            self._memory.clear()

    @property
    def messages(self) -> list[dict[str, str]]:
        """Return message history."""
        return self._messages.copy()

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
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
    """Fluent builder for VoiceAgent.

    Example:
        >>> agent = (
        ...     VoiceAgent.builder()
        ...     .asr("whisper", model="base")
        ...     .llm("ollama", model="qwen2.5:0.5b")
        ...     .tts("kokoro", voice="af_heart")
        ...     .system_prompt("You are an assistant...")
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
        self._language = "en"
        self._memory = None
        self._config = VoiceAgentConfig()

    def asr(
        self,
        provider: str = "whisper",
        model: str = "base",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configure ASR provider.

        Args:
            provider: "whisper" or "openai".
            model: Model to use.
            **kwargs: Extra arguments.
        """
        if provider in ("whisper", "whispercpp"):
            from voice_pipeline.providers.asr import WhisperCppASRProvider
            self._asr = WhisperCppASRProvider(model=model, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.asr import OpenAIASRProvider
            self._asr = OpenAIASRProvider(model=model, **kwargs)
        else:
            raise ValueError(f"Unknown ASR provider: {provider}")
        return self

    def llm(
        self,
        provider: str = "ollama",
        model: str = "qwen2.5:0.5b",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configure LLM provider.

        Args:
            provider: "ollama" or "openai".
            model: Model to use.
            **kwargs: Extra arguments.
        """
        if provider == "ollama":
            from voice_pipeline.providers.llm import OllamaLLMProvider
            self._llm = OllamaLLMProvider(model=model, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.llm import OpenAILLMProvider
            self._llm = OpenAILLMProvider(model=model, **kwargs)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
        return self

    def tts(
        self,
        provider: str = "kokoro",
        voice: str = "af_heart",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configure TTS provider.

        Args:
            provider: "kokoro" or "openai".
            voice: Voice to use.
            **kwargs: Extra arguments.
        """
        if provider == "kokoro":
            from voice_pipeline.providers.tts import KokoroTTSProvider
            self._tts = KokoroTTSProvider(voice=voice, **kwargs)
        elif provider == "openai":
            from voice_pipeline.providers.tts import OpenAITTSProvider
            self._tts = OpenAITTSProvider(voice=voice, **kwargs)
        else:
            raise ValueError(f"Unknown TTS provider: {provider}")
        return self

    def vad(
        self,
        provider: str = "silero",
        **kwargs,
    ) -> "VoiceAgentBuilder":
        """Configure VAD provider.

        Args:
            provider: "silero" or "webrtc".
            **kwargs: Extra arguments.
        """
        if provider == "silero":
            from voice_pipeline.providers.vad import SileroVADProvider
            self._vad = SileroVADProvider(**kwargs)
        elif provider == "webrtc":
            from voice_pipeline.providers.vad import WebRTCVADProvider
            self._vad = WebRTCVADProvider(**kwargs)
        else:
            raise ValueError(f"Unknown VAD provider: {provider}")
        return self

    def system_prompt(self, prompt: str) -> "VoiceAgentBuilder":
        """Set the system prompt."""
        self._system_prompt = prompt
        return self

    def language(self, lang: str) -> "VoiceAgentBuilder":
        """Set the language."""
        self._language = lang
        return self

    def memory(self, max_messages: int = 20) -> "VoiceAgentBuilder":
        """Configure conversation memory."""
        self._memory = ConversationBufferMemory(max_messages=max_messages)
        return self

    def temperature(self, temp: float) -> "VoiceAgentBuilder":
        """Set LLM temperature."""
        self._config.temperature = temp
        return self

    def build(self) -> VoiceAgent:
        """Build the VoiceAgent."""
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

"""Integration between VoiceAgentSession and voice_pipeline framework.

This module uses the VoiceAgent.builder() pattern to create a fully
configured voice agent with all framework features:
- AgentLoop: ReAct pattern for reasoning + tools
- ToolFeedbackConfig: Verbal feedback during tool execution
- EpisodicMemory: Long-term context persistence
- Streaming: Low-latency token streaming
"""

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import AppConfig
from ..webrtc.events import EventType
from .session import SessionState, VoiceAgentSession

# Import tools and agent from our new module
from .agent import (
    SYSTEM_PROMPT,
    get_current_time,
    get_weather,
    calculate,
)

logger = logging.getLogger(__name__)

# Simple system prompt for models without tool support
SIMPLE_SYSTEM_PROMPT = """Você é Dora, uma assistente de voz brasileira amigável e concisa.

Regras:
1. Responda em português brasileiro
2. Seja breve (1-2 frases)
3. Seja natural e conversacional
4. Se não souber algo, diga que não sabe

Exemplos:
- "Oi" → "Oi! Tudo bem? Como posso ajudar?"
- "Que horas são?" → "Desculpa, não tenho acesso a um relógio. Você pode verificar no seu dispositivo?"
- "Como está o tempo?" → "Não tenho acesso a informações meteorológicas no momento."
"""


@dataclass
class IntegrationConfig:
    """Configuration for agent integration."""

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:0.6b"

    # ASR - Use "parakeet" for NVIDIA Parakeet or "faster-whisper" for Whisper
    asr_provider: str = "parakeet"  # "parakeet" or "faster-whisper"
    asr_model: str = "base"  # Only used for faster-whisper
    asr_language: str = "pt"

    # TTS
    tts_provider: str = "kokoro"
    tts_voice: str = "pf_dora"
    tts_sample_rate: int = 24000

    # System prompt
    system_prompt: str = SYSTEM_PROMPT

    # Memory
    memory_enabled: bool = True
    memory_store_path: str = "./episodes"
    max_messages: int = 50

    # Tool feedback (verbal feedback during tool execution)
    tool_feedback_enabled: bool = True
    tool_feedback_phrases: list[str] = field(
        default_factory=lambda: [
            "Deixa eu verificar...",
            "Um momento...",
            "Estou buscando essa informação...",
            "Só um instante...",
        ]
    )
    tool_feedback_per_tool: dict[str, list[str]] = field(
        default_factory=lambda: {
            "get_current_time": ["Deixa eu ver as horas...", "Verificando o relógio..."],
            "get_weather": ["Consultando a previsão do tempo...", "Verificando o clima..."],
            "calculate": ["Calculando...", "Fazendo as contas..."],
        }
    )

    # Agent loop
    max_iterations: int = 5
    tool_execution_timeout: float = 30.0

    @classmethod
    def from_app_config(cls, config: AppConfig) -> "IntegrationConfig":
        """Create from AppConfig."""
        return cls(
            llm_provider=config.llm.provider,
            llm_model=config.llm.model,
            asr_provider=config.asr.provider,
            asr_model=config.asr.model,
            asr_language=config.asr.language,
            tts_provider=config.tts.provider,
            tts_voice=config.tts.voice,
            tts_sample_rate=config.tts.sample_rate,
            system_prompt=config.system_prompt or SYSTEM_PROMPT,
            memory_enabled=config.memory.enabled,
            memory_store_path=config.memory.store_path,
        )


class AgentIntegration:
    """Integrates voice session with the voice-pipeline framework.

    Uses VoiceAgent.builder() pattern for clean configuration of:
    - ASR, LLM, TTS providers
    - Turn-taking and interruption strategies
    - Streaming granularity
    - Tools and memory
    """

    def __init__(self, session: VoiceAgentSession, config: IntegrationConfig):
        """Initialize the agent integration.

        Args:
            session: Voice agent session.
            config: Integration configuration.
        """
        self.session = session
        self.config = config

        # Components (lazy loaded via builder)
        self._agent: Optional[Any] = None  # VoiceAgent or StreamingVoiceChain
        self._asr: Optional[Any] = None
        self._llm: Optional[Any] = None
        self._tts: Optional[Any] = None
        self._memory: Optional[Any] = None

        # Register session callbacks
        self.session.on_speech_end(self._on_speech_end)

    async def initialize(self) -> None:
        """Initialize all components using the builder pattern."""
        logger.info("=== INITIALIZING AGENT INTEGRATION (Builder Pattern) ===")

        try:
            await self._build_agent()

            # Emit tools list to frontend
            tools_list = self._get_tools_list()
            await self.session.event_emitter.emit(
                EventType.AGENT_READY,
                {
                    "tools": tools_list,
                    "memory_enabled": self.config.memory_enabled,
                    "feedback_enabled": self.config.tool_feedback_enabled,
                    "llm_provider": self.config.llm_provider,
                    "llm_model": self.config.llm_model,
                    "tts_provider": self.config.tts_provider,
                    "tts_voice": self.config.tts_voice,
                },
            )

            logger.info("=== AGENT INTEGRATION READY ===")

        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}", exc_info=True)
            # Fallback to manual initialization
            await self._fallback_initialization()

    async def _build_agent(self) -> None:
        """Build the agent using VoiceAgent.builder() pattern."""
        from voice_pipeline import VoiceAgent
        from voice_pipeline.agents.loop import ToolFeedbackConfig

        logger.info("Building agent with VoiceAgent.builder()...")

        # Create tool feedback config
        tool_feedback = None
        if self.config.tool_feedback_enabled:
            tool_feedback = ToolFeedbackConfig(
                enabled=True,
                phrases=self.config.tool_feedback_phrases,
                per_tool_phrases=self.config.tool_feedback_per_tool,
            )

        # Get demo tools - disabled for small models that don't support tool calling well
        # Tools can be enabled for larger models like llama3.1:8b, qwen3:4b+
        small_models = ["qwen3:0.6b", "llama3.2:1b", "qwen2.5:0.5b", "tinyllama:latest"]
        tools_enabled = self.config.llm_model not in small_models
        tools = [get_current_time, get_weather, calculate] if tools_enabled else []

        # Use simple prompt for small models without tools
        system_prompt = self.config.system_prompt if tools_enabled else SIMPLE_SYSTEM_PROMPT

        if not tools_enabled:
            logger.info(f"Tools DISABLED for small model: {self.config.llm_model}")
            logger.info("Using simplified system prompt for conversational mode")

        # Build the agent with all configurations
        builder = (
            VoiceAgent.builder()
            # LLM Configuration
            .llm(self.config.llm_provider, model=self.config.llm_model)
            # System prompt (simple for small models, full for larger models)
            .system_prompt(system_prompt)
            # Memory (conversation buffer)
            .memory(max_messages=self.config.max_messages)
        )

        # Only add tools if enabled (larger models)
        if tools:
            builder = (
                builder
                .tools(tools)
                .tool_execution_timeout(self.config.tool_execution_timeout)
                .max_iterations(self.config.max_iterations)
            )

        # Build and connect
        logger.info("Building agent...")
        self._agent = builder.build()

        # Connect LLM
        if hasattr(self._agent, 'llm'):
            logger.info(f"Connecting LLM: {self.config.llm_provider}/{self.config.llm_model}...")
            await self._agent.llm.connect()
            self._llm = self._agent.llm
            logger.info("LLM connected")

        # Store tool feedback for later use
        if hasattr(self._agent, '_loop'):
            self._agent._loop.tool_feedback = tool_feedback

        # Initialize ASR separately (not part of text agent)
        await self._init_asr()

        # Initialize TTS separately (not part of text agent)
        await self._init_tts()

        # Initialize memory if enabled
        if self.config.memory_enabled:
            await self._init_memory()

        logger.info(f"Agent built successfully. Tools: {self._get_tools_list()}")

    async def _init_asr(self) -> None:
        """Initialize ASR component."""
        try:
            if self.config.asr_provider == "parakeet":
                from voice_pipeline.providers.asr.parakeet import ParakeetProvider

                self._asr = ParakeetProvider(
                    language=self.config.asr_language,
                    quantization="int8",
                )
                logger.info(f"Connecting ASR: {self.config.asr_provider}/parakeet-tdt-0.6b-v3...")
                await self._asr.connect()
                logger.info(f"ASR connected (Parakeet)")

            elif self.config.asr_provider == "faster-whisper":
                from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

                self._asr = FasterWhisperProvider(
                    model=self.config.asr_model,
                    language=self.config.asr_language,
                )
                logger.info(f"Connecting ASR: {self.config.asr_provider}/{self.config.asr_model}...")
                await self._asr.connect()
                logger.info(f"ASR connected")
        except ImportError as e:
            logger.warning(f"Could not import ASR provider: {e}")
        except Exception as e:
            logger.error(f"Error initializing ASR: {e}", exc_info=True)

    async def _init_tts(self) -> None:
        """Initialize TTS component."""
        try:
            if self.config.tts_provider == "kokoro":
                from voice_pipeline.providers.tts.kokoro import KokoroTTSProvider

                self._tts = KokoroTTSProvider(voice=self.config.tts_voice)
                logger.info(f"Connecting TTS: {self.config.tts_provider}/{self.config.tts_voice}...")
                await self._tts.connect()
                logger.info(f"TTS connected")
        except ImportError as e:
            logger.warning(f"Could not import TTS provider: {e}")
        except Exception as e:
            logger.error(f"Error initializing TTS: {e}", exc_info=True)

    async def _init_memory(self) -> None:
        """Initialize episodic memory."""
        try:
            from voice_pipeline.memory.episodic import EpisodicMemory, FileEpisodeStore

            store = FileEpisodeStore(self.config.memory_store_path)
            self._memory = EpisodicMemory(
                store=store,
                max_recall_episodes=3,
                include_episode_context=True,
            )
            logger.info(f"Memory initialized with store at {self.config.memory_store_path}")
        except ImportError as e:
            logger.warning(f"Could not import memory: {e}")
        except Exception as e:
            logger.error(f"Error initializing memory: {e}")

    async def _fallback_initialization(self) -> None:
        """Fallback initialization if builder fails."""
        logger.warning("Using fallback initialization...")

        await asyncio.gather(
            self._init_asr(),
            self._init_llm_direct(),
            self._init_tts(),
        )

        if self.config.memory_enabled:
            await self._init_memory()

    async def _init_llm_direct(self) -> None:
        """Initialize LLM directly (fallback)."""
        try:
            if self.config.llm_provider == "ollama":
                from voice_pipeline.providers.llm.ollama import OllamaLLMProvider

                self._llm = OllamaLLMProvider(model=self.config.llm_model)
                await self._llm.connect()
                logger.info(f"LLM connected (direct): {self.config.llm_provider}/{self.config.llm_model}")
        except Exception as e:
            logger.error(f"Error initializing LLM: {e}", exc_info=True)

    def _get_tools_list(self) -> list[str]:
        """Get list of available tool names."""
        if self._agent and hasattr(self._agent, 'list_tools'):
            return self._agent.list_tools()
        return ["get_current_time", "get_weather", "calculate"]

    async def _on_speech_end(self, audio_bytes: bytes) -> None:
        """Handle speech end - process through ASR -> Agent -> TTS.

        Args:
            audio_bytes: Recorded speech audio.
        """
        logger.info(f"*** SPEECH END *** Received {len(audio_bytes)} bytes of audio")

        try:
            # ASR
            logger.info("Starting ASR transcription...")
            transcript = await self._transcribe(audio_bytes)
            logger.info(f"ASR result: {transcript}")

            if not transcript:
                logger.warning("Empty transcript, returning to listening")
                self.session._set_state(SessionState.LISTENING)
                return

            # Emit transcript event
            await self.session.event_emitter.emit(
                EventType.ASR_FINAL, {"text": transcript, "timestamp": time.time()}
            )

            if self.session._on_transcript:
                result = self.session._on_transcript(transcript)
                if asyncio.iscoroutine(result):
                    await result

            # Process through agent
            response_text = await self._process_with_agent(transcript)

            # Emit response
            if self.session._on_response:
                result = self.session._on_response(response_text)
                if asyncio.iscoroutine(result):
                    await result

            # TTS - synthesize and play
            await self._synthesize_and_play(response_text)

            # Save to memory
            if self._memory:
                await self._memory.save_context(transcript, response_text)

            # Reset for next turn
            self.session.reset_turn_metrics()

        except Exception as e:
            logger.error(f"Error processing speech: {e}", exc_info=True)
            await self.session.event_emitter.emit(EventType.ERROR, {"error": str(e)})
            self.session._set_state(SessionState.LISTENING)

    async def _transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """Transcribe audio to text."""
        if not self._asr:
            logger.warning("No ASR available")
            return None

        await self.session.event_emitter.emit(EventType.ASR_START, {"timestamp": time.time()})

        try:
            logger.info(f"Transcribing {len(audio_bytes)} bytes of audio...")
            result = await self._asr.transcribe(audio_bytes)
            transcript = result.text if hasattr(result, "text") else str(result)

            self.session._metrics.last_asr_end = time.time()

            logger.info(f"*** TRANSCRIPT: {transcript} ***")
            return transcript.strip() if transcript else None

        except Exception as e:
            logger.error(f"ASR error: {e}", exc_info=True)
            return None

    def _is_simple_greeting(self, text: str) -> bool:
        """Check if the input is a simple greeting that doesn't need tools.

        Args:
            text: User input text.

        Returns:
            True if it's a simple greeting.
        """
        # Exact greetings (or with minor variations)
        exact_greetings = [
            "oi", "olá", "ola", "alô", "alo", "ei", "hey", "hi", "hello",
            "bom dia", "boa tarde", "boa noite", "e aí", "e ai",
            "fala", "beleza", "suave", "tranquilo",
        ]

        # Greetings that can have "?" or "!" at the end
        question_greetings = [
            "tudo bem", "tudo bom", "como vai", "como você está",
            "oi tudo bem", "olá tudo bem", "alô tudo bem",
        ]

        text_lower = text.lower().strip()
        # Remove punctuation for comparison
        text_clean = ''.join(c for c in text_lower if c.isalnum() or c.isspace()).strip()

        # Check exact matches
        if text_clean in exact_greetings:
            return True

        # Check question greetings
        for greeting in question_greetings:
            if text_clean == greeting or text_clean.startswith(greeting):
                return True

        # Check combinations like "oi, tudo bem?"
        words = text_clean.split()
        if len(words) <= 4:  # Short phrases only
            for greeting in exact_greetings:
                if greeting in words or text_clean.startswith(greeting):
                    return True

        return False

    async def _respond_to_greeting(self, transcript: str) -> str:
        """Generate a simple greeting response without using tools.

        Args:
            transcript: User greeting.

        Returns:
            Friendly greeting response.
        """
        responses = [
            "Oi! Tudo bem? Como posso ajudar?",
            "Olá! Tudo ótimo por aqui! E você?",
            "Oi! Estou aqui para ajudar!",
            "Olá! Em que posso ser útil?",
            "Oi! Tudo bem sim! O que você precisa?",
        ]
        return random.choice(responses)

    def _clean_thinking_tags(self, text: str) -> str:
        """Remove <think>...</think> tags from Qwen3 responses.

        Qwen3 models include thinking process in responses which should
        not be spoken aloud.

        Args:
            text: Raw response text.

        Returns:
            Cleaned text without thinking tags.
        """
        # Remove <think>...</think> blocks (including multiline)
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        # Clean up extra whitespace
        cleaned = re.sub(r'\n\s*\n', '\n', cleaned)
        return cleaned.strip()

    async def _process_with_agent(self, transcript: str) -> str:
        """Process user input through the agent with streaming.

        Args:
            transcript: User's transcribed speech.

        Returns:
            Final response text.
        """
        # Check for simple greetings - bypass agent/tools entirely
        if self._is_simple_greeting(transcript):
            logger.info(f"Detected simple greeting, bypassing tools: {transcript}")
            response = await self._respond_to_greeting(transcript)
            await self.session.event_emitter.emit(EventType.LLM_TOKEN, {"token": response})
            return response

        self.session._metrics.last_llm_start = time.time()
        await self.session.event_emitter.emit(EventType.LLM_START, {"timestamp": time.time()})

        try:
            # Use agent's streaming interface
            if self._agent and hasattr(self._agent, 'astream'):
                logger.info(f"Processing with agent.astream(): {transcript}")

                response_tokens: list[str] = []
                first_token = True

                async for token in self._agent.astream(transcript):
                    # Check if this is a tool feedback phrase
                    if self._is_tool_feedback(token):
                        logger.info(f"Tool feedback: {token}")
                        await self.session.event_emitter.emit(
                            EventType.TOOL_FEEDBACK, {"phrase": token}
                        )
                        # Synthesize and play feedback immediately
                        if self._tts:
                            try:
                                feedback_audio = await self._tts.synthesize(token)
                                await self.session.send_audio(feedback_audio)
                            except Exception as e:
                                logger.warning(f"Could not play tool feedback: {e}")
                        continue

                    # Skip thinking tokens from Qwen3
                    if '<think>' in token or '</think>' in token:
                        continue

                    # Regular token
                    if first_token:
                        first_token = False
                        self.session._metrics.last_llm_first_token = time.time()
                        logger.info("*** FIRST LLM TOKEN ***")

                        if self.session._metrics.last_asr_end:
                            self.session._metrics.ttft = (
                                self.session._metrics.last_llm_first_token
                                - self.session._metrics.last_asr_end
                            )

                    await self.session.event_emitter.emit(EventType.LLM_TOKEN, {"token": token})
                    response_tokens.append(token)

                response_text = "".join(response_tokens)

            elif self._agent and hasattr(self._agent, 'ainvoke'):
                # Non-streaming fallback
                logger.info(f"Processing with agent.ainvoke(): {transcript}")
                response_text = await self._agent.ainvoke(transcript)

            elif self._llm:
                # Direct LLM fallback
                logger.info(f"Processing with direct LLM: {transcript}")
                response_text = await self._llm.generate(
                    messages=[{"role": "user", "content": transcript}],
                    system_prompt=self.config.system_prompt,
                )

            else:
                response_text = "Desculpe, não consigo processar sua solicitação no momento."

            await self.session.event_emitter.emit(EventType.LLM_END, {"timestamp": time.time()})

            # Clean Qwen3 thinking tags from response
            response_text = self._clean_thinking_tags(response_text)
            logger.info(f"*** RESPONSE: {response_text[:100]}... ***")

            return response_text

        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            return "Desculpe, ocorreu um erro ao processar sua solicitação."

    def _is_tool_feedback(self, token: str) -> bool:
        """Check if a token is a tool feedback phrase."""
        all_phrases = self.config.tool_feedback_phrases.copy()
        for phrases in self.config.tool_feedback_per_tool.values():
            all_phrases.extend(phrases)
        return token in all_phrases

    async def _synthesize_and_play(self, text: str) -> None:
        """Synthesize text to speech and play."""
        if not self._tts:
            logger.warning("No TTS available - skipping synthesis")
            self.session._set_state(SessionState.LISTENING)
            return

        self.session._metrics.last_tts_start = time.time()

        await self.session.event_emitter.emit(EventType.TTS_START, {"timestamp": time.time()})

        try:
            logger.info(f"Synthesizing text: {text[:100]}...")

            # Synthesize complete audio
            audio_bytes = await self._tts.synthesize(text)
            logger.info(f"*** TTS COMPLETE: {len(audio_bytes)} bytes ***")

            self.session._metrics.last_tts_first_audio = time.time()

            # Calculate TTFA
            if self.session._metrics.last_vad_start:
                self.session._metrics.ttfa = (
                    self.session._metrics.last_tts_first_audio
                    - self.session._metrics.last_vad_start
                )
                self.session._metrics.e2e = self.session._metrics.ttfa

            # Check for interruption
            if not self.session._interrupted:
                await self.session.send_audio(audio_bytes)

            await self.session.event_emitter.emit(EventType.TTS_END, {"timestamp": time.time()})

            # Emit metrics
            await self.session.event_emitter.emit(
                EventType.METRICS, self.session.metrics.to_dict()
            )

        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)

        finally:
            if not self.session._interrupted:
                self.session._set_state(SessionState.LISTENING)

    async def handle_tool_event(self, event_type: str, data: dict) -> None:
        """Handle tool-related events from the frontend."""
        if event_type == "tool_confirm":
            tool_name = data.get("tool_name")
            logger.info(f"User confirmed tool execution: {tool_name}")
        elif event_type == "tool_deny":
            tool_name = data.get("tool_name")
            logger.info(f"User denied tool execution: {tool_name}")

    async def recall_memory(self, query: str) -> list[dict]:
        """Recall relevant episodes from memory."""
        if not self._memory:
            return []

        try:
            episodes = await self._memory.recall(query)

            await self.session.event_emitter.emit(
                EventType.MEMORY_RECALL,
                {
                    "query": query,
                    "episodes": [
                        {"id": ep.id, "summary": ep.summary, "timestamp": ep.timestamp}
                        for ep in episodes
                    ],
                },
            )

            return [ep.to_dict() for ep in episodes]
        except Exception as e:
            logger.error(f"Memory recall error: {e}")
            return []

    async def commit_episode(
        self,
        summary: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Commit current conversation as an episode."""
        if not self._memory:
            return None

        try:
            episode = await self._memory.commit_episode(
                summary=summary,
                tags=tags,
                importance=0.5,
                clear_after=True,
            )

            await self.session.event_emitter.emit(
                EventType.MEMORY_SAVE,
                {
                    "episode_id": episode.id,
                    "summary": episode.summary,
                    "timestamp": episode.timestamp,
                },
            )

            logger.info(f"Committed episode: {episode.id}")
            return episode.to_dict()
        except Exception as e:
            logger.error(f"Error committing episode: {e}")
            return None

    def get_tools_info(self) -> list[dict]:
        """Get information about available tools."""
        tools_info = []
        tools = [get_current_time, get_weather, calculate]
        for tool in tools:
            tools_info.append({
                "name": tool.name,
                "description": tool.description,
            })
        return tools_info

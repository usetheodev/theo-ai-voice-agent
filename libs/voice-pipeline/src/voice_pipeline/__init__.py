"""Voice Pipeline - A modular voice conversation pipeline.

This library provides a framework for building voice AI applications,
inspired by LangChain's composability patterns.

Quick Start:
    >>> from voice_pipeline import ASRInterface, LLMInterface, TTSInterface
    >>> # Create a chain using the | operator
    >>> chain = my_asr | my_llm | my_tts
    >>> result = await chain.ainvoke(audio_bytes)

    >>> # Or use streaming for low-latency
    >>> async for audio_chunk in chain.astream(audio_bytes):
    ...     play(audio_chunk)
"""

# Runnable (base for all components)
from .runnable import (
    RunnableConfig,
    VoiceFallback,
    VoiceFilter,
    VoiceLambda,
    VoiceParallel,
    VoicePassthrough,
    VoiceRaceParallel,
    VoiceRetry,
    VoiceRouter,
    VoiceRunnable,
    VoiceRunnableBound,
    VoiceRunnableWithConfig,
    VoiceSequence,
    VoiceStreamingSequence,
    ensure_config,
    get_callback_manager,
)

# Core
from .core.config import PipelineConfig
from .core.events import EventEmitter, PipelineEvent, PipelineEventType
from .core.pipeline import Pipeline
from .core.state_machine import ConversationState, ConversationStateMachine

# Interfaces
from .interfaces.asr import ASRInput, ASRInterface, TranscriptionResult
from .interfaces.llm import LLMChunk, LLMInput, LLMInterface, LLMResponse
from .interfaces.tts import AudioChunk, TTSInput, TTSInterface
from .interfaces.vad import SpeechState, VADEvent, VADInput, VADInterface

# Streaming
from .streaming.buffer import AsyncQueue, AudioBuffer, TextBuffer
from .streaming.sentence_streamer import SentenceStreamer, SentenceStreamerConfig

# Providers
from .providers import (
    ASRCapabilities,
    LLMCapabilities,
    ProviderInfo,
    ProviderRegistry,
    ProviderType,
    TTSCapabilities,
    VADCapabilities,
    get_registry,
    register_asr,
    register_llm,
    register_tts,
    register_vad,
    reset_registry,
)

# Callbacks
from .callbacks import (
    CallbackManager,
    LoggingHandler,
    MetricsHandler,
    PipelineMetrics,
    RunContext,
    StdOutHandler,
    VoiceCallbackHandler,
    run_with_callbacks,
)

# Chains
from .chains import (
    ConversationChain,
    ParallelStreamingChain,
    SimpleVoiceChain,
    StreamingVoiceChain,
    VoiceChain,
    VoiceChainBuilder,
    voice_chain,
)

# Memory
from .memory import (
    BaseMemoryStore,
    ConversationBufferMemory,
    ConversationSummaryBufferMemory,
    ConversationSummaryMemory,
    ConversationWindowMemory,
    InMemoryStore,
    MemoryContext,
    VoiceMemory,
)

# Tools
from .tools import (
    FunctionTool,
    ToolCall,
    ToolExecutor,
    ToolParameter,
    ToolResult,
    VoiceTool,
    create_executor,
    tool,
    voice_tool,
)

# Prompts
from .prompts import (
    ASSISTANT_PERSONA,
    CONCIERGE_PERSONA,
    CUSTOMER_SERVICE_PERSONA,
    Message,
    SimplePrompt,
    TUTOR_PERSONA,
    TurnPrompt,
    VoiceChatPrompt,
    VoicePersona,
    VoicePromptTemplate,
    VoiceStyle,
    create_chat_prompt,
    voice_prompt,
)

# Agents
from .agents import (
    AgentLoop,
    AgentMessage,
    AgentRouter,
    AgentState,
    AgentStatus,
    BatchToolNode,
    ConditionalBranch,
    StreamingVoiceAgent,
    ToolNode,
    VoiceAgent,
    create_tool_router,
    create_voice_agent,
    should_continue,
    status_condition,
    tools_condition,
)

__version__ = "0.1.0"

__all__ = [
    # Runnable (base)
    "VoiceRunnable",
    "VoiceRunnableBound",
    "VoiceRunnableWithConfig",
    "VoiceSequence",
    "VoiceStreamingSequence",
    "VoiceParallel",
    "VoiceRaceParallel",
    "VoicePassthrough",
    "VoiceLambda",
    "VoiceRouter",
    "VoiceFilter",
    "VoiceRetry",
    "VoiceFallback",
    "RunnableConfig",
    "ensure_config",
    "get_callback_manager",
    # Core
    "Pipeline",
    "PipelineConfig",
    "ConversationState",
    "ConversationStateMachine",
    "EventEmitter",
    "PipelineEvent",
    "PipelineEventType",
    # Interfaces
    "ASRInterface",
    "ASRInput",
    "TranscriptionResult",
    "LLMInterface",
    "LLMInput",
    "LLMChunk",
    "LLMResponse",
    "TTSInterface",
    "TTSInput",
    "AudioChunk",
    "VADInterface",
    "VADInput",
    "VADEvent",
    "SpeechState",
    # Streaming
    "SentenceStreamer",
    "SentenceStreamerConfig",
    "AudioBuffer",
    "TextBuffer",
    "AsyncQueue",
    # Providers
    "ProviderRegistry",
    "ProviderType",
    "ProviderInfo",
    "ASRCapabilities",
    "LLMCapabilities",
    "TTSCapabilities",
    "VADCapabilities",
    "get_registry",
    "reset_registry",
    "register_asr",
    "register_llm",
    "register_tts",
    "register_vad",
    # Callbacks
    "VoiceCallbackHandler",
    "CallbackManager",
    "RunContext",
    "run_with_callbacks",
    "LoggingHandler",
    "MetricsHandler",
    "StdOutHandler",
    "PipelineMetrics",
    # Chains
    "VoiceChain",
    "SimpleVoiceChain",
    "VoiceChainBuilder",
    "voice_chain",
    "ConversationChain",
    "StreamingVoiceChain",
    "ParallelStreamingChain",
    # Memory
    "VoiceMemory",
    "MemoryContext",
    "BaseMemoryStore",
    "ConversationBufferMemory",
    "ConversationWindowMemory",
    "ConversationSummaryMemory",
    "ConversationSummaryBufferMemory",
    "InMemoryStore",
    # Tools
    "VoiceTool",
    "FunctionTool",
    "ToolParameter",
    "ToolResult",
    "ToolExecutor",
    "ToolCall",
    "voice_tool",
    "tool",
    "create_executor",
    # Prompts
    "VoicePromptTemplate",
    "VoiceStyle",
    "SimplePrompt",
    "voice_prompt",
    "VoiceChatPrompt",
    "Message",
    "TurnPrompt",
    "create_chat_prompt",
    "VoicePersona",
    "ASSISTANT_PERSONA",
    "CUSTOMER_SERVICE_PERSONA",
    "TUTOR_PERSONA",
    "CONCIERGE_PERSONA",
    # Agents
    "VoiceAgent",
    "StreamingVoiceAgent",
    "AgentState",
    "AgentMessage",
    "AgentStatus",
    "AgentLoop",
    "AgentRouter",
    "ToolNode",
    "BatchToolNode",
    "ConditionalBranch",
    "tools_condition",
    "should_continue",
    "status_condition",
    "create_tool_router",
    "create_voice_agent",
]

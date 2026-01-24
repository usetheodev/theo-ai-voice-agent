"""API Schemas package."""

from .agent_schemas import (
    # LLM
    LLMConfigRequest,
    # TTS
    TTSConfigRequest,
    FallbackVoiceRequest,
    # ASR
    ASRConfigRequest,
    FallbackTranscriberRequest,
    # Plans
    StartSpeakingPlanRequest,
    StopSpeakingPlanRequest,
    # Settings
    CallTimeoutRequest,
    MessagesConfigRequest,
    IdleMessageRequest,
    ToolsConfigRequest,
    ToolRequest,
    AnalysisConfigRequest,
    StructuredOutputRequest,
    PrivacyConfigRequest,
    ServerConfigRequest,
    # Voice Agent
    CreateVoiceAgentRequest,
    VoiceAgentResponse,
    ListVoiceAgentsResponse,
    # Presets
    PresetInfo,
    ListPresetsResponse,
)

__all__ = [
    # LLM
    "LLMConfigRequest",
    # TTS
    "TTSConfigRequest",
    "FallbackVoiceRequest",
    # ASR
    "ASRConfigRequest",
    "FallbackTranscriberRequest",
    # Plans
    "StartSpeakingPlanRequest",
    "StopSpeakingPlanRequest",
    # Settings
    "CallTimeoutRequest",
    "MessagesConfigRequest",
    "IdleMessageRequest",
    "ToolsConfigRequest",
    "ToolRequest",
    "AnalysisConfigRequest",
    "StructuredOutputRequest",
    "PrivacyConfigRequest",
    "ServerConfigRequest",
    # Voice Agent
    "CreateVoiceAgentRequest",
    "VoiceAgentResponse",
    "ListVoiceAgentsResponse",
    # Presets
    "PresetInfo",
    "ListPresetsResponse",
]

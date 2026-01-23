"""Session configuration models for the AI Inference service."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .audio import AudioFormat


class Modality(str, Enum):
    """Supported modalities."""

    TEXT = "text"
    AUDIO = "audio"


class TurnDetectionType(str, Enum):
    """Turn detection types."""

    SERVER_VAD = "server_vad"
    NONE = "none"


class TurnDetectionConfig(BaseModel):
    """Configuration for turn detection."""

    type: TurnDetectionType = Field(
        default=TurnDetectionType.SERVER_VAD, description="Turn detection type"
    )
    threshold: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Voice activity detection threshold"
    )
    prefix_padding_ms: int = Field(
        default=300, ge=0, description="Amount of audio to include before speech starts"
    )
    silence_duration_ms: int = Field(
        default=500, ge=0, description="Duration of silence to detect end of speech"
    )
    create_response: bool = Field(
        default=True, description="Whether to automatically create response after turn"
    )


class InputAudioTranscriptionConfig(BaseModel):
    """Configuration for input audio transcription."""

    model: str = Field(default="whisper-1", description="Transcription model to use")


class ToolType(str, Enum):
    """Tool types."""

    FUNCTION = "function"


class ToolDefinition(BaseModel):
    """Definition of a tool/function that can be called."""

    type: ToolType = Field(default=ToolType.FUNCTION, description="Tool type")
    name: str = Field(..., description="Function name")
    description: str = Field(..., description="Function description")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for function parameters"
    )


class ToolChoice(str, Enum):
    """Tool choice options."""

    AUTO = "auto"
    NONE = "none"
    REQUIRED = "required"


class SessionConfig(BaseModel):
    """Configuration for a realtime session."""

    modalities: List[Modality] = Field(
        default=[Modality.TEXT, Modality.AUDIO], description="Enabled modalities"
    )
    instructions: Optional[str] = Field(
        default=None, description="System instructions for the model"
    )
    voice: str = Field(default="alloy", description="Voice for audio output")
    input_audio_format: AudioFormat = Field(
        default=AudioFormat.PCM16, description="Input audio format"
    )
    output_audio_format: AudioFormat = Field(
        default=AudioFormat.PCM16, description="Output audio format"
    )
    input_audio_transcription: Optional[InputAudioTranscriptionConfig] = Field(
        default=None, description="Input audio transcription config"
    )
    turn_detection: Optional[TurnDetectionConfig] = Field(
        default_factory=TurnDetectionConfig, description="Turn detection config"
    )
    tools: List[ToolDefinition] = Field(
        default_factory=list, description="Available tools"
    )
    tool_choice: ToolChoice = Field(
        default=ToolChoice.AUTO, description="Tool choice setting"
    )
    temperature: float = Field(
        default=0.8, ge=0.0, le=2.0, description="Sampling temperature"
    )
    max_response_output_tokens: Optional[int] = Field(
        default=None, description="Maximum tokens in response (None for inf)"
    )


class ResponseConfig(BaseModel):
    """Configuration for generating a response."""

    modalities: Optional[List[Modality]] = Field(
        default=None, description="Override session modalities"
    )
    instructions: Optional[str] = Field(
        default=None, description="Override session instructions"
    )
    voice: Optional[str] = Field(default=None, description="Override session voice")
    output_audio_format: Optional[AudioFormat] = Field(
        default=None, description="Override output audio format"
    )
    tools: Optional[List[ToolDefinition]] = Field(
        default=None, description="Override session tools"
    )
    tool_choice: Optional[ToolChoice] = Field(
        default=None, description="Override tool choice"
    )
    temperature: Optional[float] = Field(
        default=None, description="Override temperature"
    )
    max_output_tokens: Optional[int] = Field(
        default=None, description="Override max tokens"
    )
    conversation: Optional[Literal["auto", "none"]] = Field(
        default="auto", description="Conversation mode"
    )
    metadata: Optional[Dict[str, str]] = Field(
        default=None, description="Response metadata"
    )

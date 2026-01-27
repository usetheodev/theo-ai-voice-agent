"""
Semantic conventions for Voice Pipeline OpenTelemetry instrumentation.

Follows OTel GenAI semantic conventions where applicable,
with custom `voice.*` namespace for voice-specific attributes.

References:
- https://opentelemetry.io/docs/specs/semconv/gen-ai/
"""

# ==============================================================================
# GenAI Semantic Conventions (OTel standard)
# ==============================================================================

GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

# ==============================================================================
# Voice Session Attributes
# ==============================================================================

VOICE_SESSION_ID = "voice.session.id"
VOICE_TURN_NUMBER = "voice.turn.number"
VOICE_PIPELINE_NAME = "voice.pipeline.name"

# ==============================================================================
# Voice Provider Attributes
# ==============================================================================

VOICE_PROVIDER_NAME = "voice.provider.name"

# ==============================================================================
# Voice ASR Attributes
# ==============================================================================

VOICE_ASR_LANGUAGE = "voice.asr.language"
VOICE_ASR_CONFIDENCE = "voice.asr.confidence"
VOICE_ASR_INPUT_BYTES = "voice.asr.input_bytes"
VOICE_ASR_IS_STREAMING = "voice.asr.is_streaming"

# ==============================================================================
# Voice LLM Attributes
# ==============================================================================

VOICE_LLM_TOKEN_COUNT = "voice.llm.token_count"
VOICE_LLM_TTFT_MS = "voice.llm.ttft_ms"
VOICE_LLM_RESPONSE_LENGTH = "voice.llm.response_length"

# ==============================================================================
# Voice TTS Attributes
# ==============================================================================

VOICE_TTS_VOICE = "voice.tts.voice"
VOICE_TTS_TTFA_MS = "voice.tts.ttfa_ms"
VOICE_TTS_AUDIO_BYTES = "voice.tts.audio_bytes"
VOICE_TTS_CHUNK_COUNT = "voice.tts.chunk_count"
VOICE_TTS_SAMPLE_RATE = "voice.tts.sample_rate"

# ==============================================================================
# Voice VAD Attributes
# ==============================================================================

VOICE_VAD_CONFIDENCE = "voice.vad.confidence"
VOICE_VAD_SPEECH_DURATION_MS = "voice.vad.speech_duration_ms"

# ==============================================================================
# Voice Pipeline Attributes
# ==============================================================================

VOICE_PIPELINE_E2E_LATENCY_MS = "voice.pipeline.e2e_latency_ms"
VOICE_PIPELINE_BARGE_IN = "voice.pipeline.barge_in"

# ==============================================================================
# Metric Instrument Names
# ==============================================================================

METRIC_ASR_DURATION = "voice.asr.duration"
METRIC_LLM_TTFT = "voice.llm.time_to_first_token"
METRIC_LLM_DURATION = "voice.llm.duration"
METRIC_TTS_TTFA = "voice.tts.time_to_first_audio"
METRIC_TTS_DURATION = "voice.tts.duration"
METRIC_PIPELINE_E2E_LATENCY = "voice.pipeline.e2e_latency"

METRIC_LLM_TOKENS_GENERATED = "voice.llm.tokens_generated"
METRIC_TTS_AUDIO_BYTES_TOTAL = "voice.tts.audio_bytes_total"
METRIC_PIPELINE_BARGE_IN_TOTAL = "voice.pipeline.barge_in_total"
METRIC_PIPELINE_ERRORS_TOTAL = "voice.pipeline.errors_total"
METRIC_PIPELINE_TURNS_TOTAL = "voice.pipeline.turns_total"

METRIC_PIPELINE_ACTIVE_SESSIONS = "voice.pipeline.active_sessions"

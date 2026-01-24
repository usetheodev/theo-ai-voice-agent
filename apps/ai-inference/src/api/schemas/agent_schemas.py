"""Pydantic schemas para Voice Agent API.

Schemas para criar, atualizar e retornar Voice Agents via API REST.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# LLM CONFIG SCHEMAS
# =============================================================================

class LLMConfigRequest(BaseModel):
    """Configuração do LLM para criar/atualizar agente."""

    provider: str = Field(
        default="ollama",
        description="Provider do LLM: ollama, openai, anthropic, groq, together, custom",
        json_schema_extra={"examples": ["ollama", "openai", "groq"]},
    )
    model: str = Field(
        default="llama3:8b",
        description="Modelo a ser usado",
        json_schema_extra={"examples": ["llama3:8b", "gpt-4o", "claude-3-sonnet"]},
    )
    first_message_mode: str = Field(
        default="assistant-speaks-first",
        description="Quem fala primeiro: assistant-speaks-first, user-speaks-first",
    )
    first_message: str = Field(
        default="Olá! Como posso ajudá-lo hoje?",
        description="Primeira mensagem do assistente",
    )
    system_prompt: str = Field(
        default="Você é um assistente de voz amigável e prestativo.",
        description="System prompt do assistente",
    )
    max_tokens: int = Field(
        default=250,
        ge=1,
        le=4096,
        description="Máximo de tokens na resposta",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Temperatura para geração (0 = determinístico, 2 = criativo)",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key para providers cloud (OpenAI, Anthropic, etc.)",
    )


# =============================================================================
# VOICE CONFIG SCHEMAS (TTS)
# =============================================================================

class FallbackVoiceRequest(BaseModel):
    """Voz de fallback."""
    provider: str
    voice: str
    priority: int = 0


class TTSConfigRequest(BaseModel):
    """Configuração do TTS para criar/atualizar agente."""

    provider: str = Field(
        default="piper",
        description="Provider do TTS: piper, elevenlabs, openai-tts, azure, google, coqui",
        json_schema_extra={"examples": ["piper", "elevenlabs", "openai-tts"]},
    )
    voice: str = Field(
        default="pt_BR-faber-medium",
        description="Voz a ser usada",
        json_schema_extra={"examples": ["pt_BR-faber-medium", "rachel", "alloy"]},
    )
    speed: float = Field(
        default=1.0,
        ge=0.25,
        le=4.0,
        description="Velocidade da fala (1.0 = normal)",
    )
    background_sound: str = Field(
        default="off",
        description="Som de fundo: off, office, call-center, custom",
    )
    background_sound_url: Optional[str] = Field(
        default=None,
        description="URL do som de fundo customizado",
    )
    input_min_characters: int = Field(
        default=30,
        ge=1,
        le=500,
        description="Mínimo de caracteres antes de sintetizar",
    )
    punctuation_boundaries: list[str] = Field(
        default=[".", "!", "?", ";", ":", ","],
        description="Pontuações que delimitam chunks de síntese",
    )
    fallback_voices: list[FallbackVoiceRequest] = Field(
        default=[],
        description="Vozes de fallback caso a primária falhe",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key para providers cloud (ElevenLabs, etc.)",
    )


# =============================================================================
# TRANSCRIBER CONFIG SCHEMAS (ASR)
# =============================================================================

class FallbackTranscriberRequest(BaseModel):
    """Transcriber de fallback."""
    provider: str
    model: str
    priority: int = 0


class ASRConfigRequest(BaseModel):
    """Configuração do ASR/Transcriber para criar/atualizar agente."""

    provider: str = Field(
        default="whisper-local",
        description="Provider do ASR: whisper-local, deepgram, assemblyai, google, azure, parakeet",
        json_schema_extra={"examples": ["whisper-local", "deepgram", "parakeet"]},
    )
    model: str = Field(
        default="large-v3",
        description="Modelo a ser usado",
        json_schema_extra={"examples": ["large-v3", "nova-3", "parakeet-tdt"]},
    )
    language: str = Field(
        default="pt-BR",
        description="Idioma para transcrição",
        json_schema_extra={"examples": ["pt-BR", "en-US", "es-ES", "multi"]},
    )
    background_denoising: bool = Field(
        default=True,
        description="Filtrar ruído de fundo",
    )
    use_numerals: bool = Field(
        default=True,
        description="Converter números por extenso para dígitos",
    )
    confidence_threshold: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Threshold de confiança para filtrar transcrições",
    )
    keyterms: list[str] = Field(
        default=[],
        description="Palavras-chave para boost de reconhecimento",
    )
    fallback_transcribers: list[FallbackTranscriberRequest] = Field(
        default=[],
        description="Transcribers de fallback caso o primário falhe",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key para providers cloud (Deepgram, etc.)",
    )


# =============================================================================
# START/STOP SPEAKING PLANS
# =============================================================================

class StartSpeakingPlanRequest(BaseModel):
    """Plano de quando o assistente começa a falar."""

    wait_seconds: float = Field(
        default=0.4,
        ge=0.0,
        le=5.0,
        description="Segundos de espera antes de falar",
    )
    smart_endpointing: str = Field(
        default="off",
        description="Smart endpointing: off, on",
    )
    on_punctuation_seconds: float = Field(
        default=0.1,
        ge=0.0,
        le=3.0,
        description="Segundos após pontuação",
    )
    on_no_punctuation_seconds: float = Field(
        default=1.5,
        ge=0.0,
        le=3.0,
        description="Segundos sem pontuação",
    )
    on_number_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=3.0,
        description="Segundos após número",
    )


class StopSpeakingPlanRequest(BaseModel):
    """Plano de quando o assistente para de falar (barge-in)."""

    num_words: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Número de palavras para interromper (0 = qualquer)",
    )
    voice_seconds: float = Field(
        default=0.2,
        ge=0.0,
        le=0.5,
        description="Segundos de voz para interromper",
    )
    backoff_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="Segundos antes de voltar a falar",
    )


# =============================================================================
# CALL TIMEOUT SETTINGS
# =============================================================================

class CallTimeoutRequest(BaseModel):
    """Configurações de timeout."""

    silence_timeout_seconds: int = Field(
        default=30,
        ge=10,
        le=3600,
        description="Timeout por silêncio",
    )
    max_duration_seconds: int = Field(
        default=600,
        ge=10,
        le=43200,
        description="Duração máxima da chamada",
    )


# =============================================================================
# MESSAGES CONFIG
# =============================================================================

class IdleMessageRequest(BaseModel):
    """Mensagem de idle."""
    message: str
    wait_seconds: float = 7.5


class MessagesConfigRequest(BaseModel):
    """Configuração de mensagens."""

    voicemail_message: Optional[str] = Field(
        default=None,
        description="Mensagem para voicemail",
    )
    end_call_message: Optional[str] = Field(
        default=None,
        description="Mensagem de encerramento",
    )
    idle_messages: list[IdleMessageRequest] = Field(
        default=[],
        description="Mensagens de idle",
    )
    max_idle_messages: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Máximo de mensagens idle",
    )
    idle_timeout_seconds: float = Field(
        default=7.5,
        ge=1.0,
        le=60.0,
        description="Timeout para mensagem idle",
    )


# =============================================================================
# TOOLS CONFIG
# =============================================================================

class ToolRequest(BaseModel):
    """Definição de ferramenta customizada."""
    name: str
    description: str
    parameters: dict[str, Any] = {}
    endpoint_url: Optional[str] = None
    enabled: bool = True


class ToolsConfigRequest(BaseModel):
    """Configuração de ferramentas."""

    end_call_enabled: bool = Field(
        default=True,
        description="Permitir que o assistente encerre a chamada",
    )
    dial_keypad_enabled: bool = Field(
        default=False,
        description="Permitir digitar no teclado",
    )
    forwarding_phone_number: Optional[str] = Field(
        default=None,
        description="Número para encaminhar chamadas",
    )
    custom_tools: list[ToolRequest] = Field(
        default=[],
        description="Ferramentas customizadas",
    )


# =============================================================================
# ANALYSIS CONFIG
# =============================================================================

class StructuredOutputRequest(BaseModel):
    """Definição de output estruturado."""
    name: str
    description: str
    json_schema: dict[str, Any]


class AnalysisConfigRequest(BaseModel):
    """Configuração de análise."""

    structured_outputs: list[StructuredOutputRequest] = Field(
        default=[],
        description="Outputs estruturados para extração",
    )
    summary_enabled: bool = Field(
        default=True,
        description="Gerar sumário da chamada",
    )
    summary_prompt: str = Field(
        default="Resuma a chamada em 2-3 frases.",
        description="Prompt para sumário",
    )


# =============================================================================
# PRIVACY CONFIG
# =============================================================================

class PrivacyConfigRequest(BaseModel):
    """Configuração de privacidade."""

    hipaa_enabled: bool = Field(
        default=False,
        description="Modo HIPAA (desabilita logs)",
    )
    audio_recording_enabled: bool = Field(
        default=True,
        description="Gravar áudio da chamada",
    )
    audio_recording_format: str = Field(
        default="wav",
        description="Formato da gravação: wav, mp3, ogg, webm",
    )
    logging_enabled: bool = Field(
        default=True,
        description="Habilitar logs",
    )
    transcript_enabled: bool = Field(
        default=True,
        description="Salvar transcrição",
    )


# =============================================================================
# SERVER CONFIG
# =============================================================================

class ServerConfigRequest(BaseModel):
    """Configuração de servidor/webhooks."""

    server_url: Optional[str] = Field(
        default=None,
        description="URL para webhooks",
    )
    timeout_seconds: int = Field(
        default=20,
        ge=1,
        le=300,
        description="Timeout para webhooks",
    )
    custom_headers: dict[str, str] = Field(
        default={},
        description="Headers customizados",
    )
    server_messages: list[str] = Field(
        default=["transcript", "function-call", "end-of-call-report"],
        description="Eventos a enviar para o servidor",
    )


# =============================================================================
# VOICE AGENT REQUEST/RESPONSE
# =============================================================================

class CreateVoiceAgentRequest(BaseModel):
    """Request para criar um Voice Agent.

    Baseado no formulário do Vapi.ai.
    """

    # Identificação
    name: str = Field(
        default="Voice Agent",
        description="Nome do agente",
    )
    description: str = Field(
        default="",
        description="Descrição do agente",
    )

    # Configurações principais
    model: LLMConfigRequest = Field(
        default_factory=LLMConfigRequest,
        description="Configuração do LLM",
    )
    voice: TTSConfigRequest = Field(
        default_factory=TTSConfigRequest,
        description="Configuração do TTS",
    )
    transcriber: ASRConfigRequest = Field(
        default_factory=ASRConfigRequest,
        description="Configuração do ASR",
    )

    # Planos de fala
    start_speaking_plan: StartSpeakingPlanRequest = Field(
        default_factory=StartSpeakingPlanRequest,
        description="Quando o assistente começa a falar",
    )
    stop_speaking_plan: StopSpeakingPlanRequest = Field(
        default_factory=StopSpeakingPlanRequest,
        description="Quando o assistente para de falar",
    )

    # Timeouts
    call_timeout: CallTimeoutRequest = Field(
        default_factory=CallTimeoutRequest,
        description="Configurações de timeout",
    )

    # Mensagens
    messages: MessagesConfigRequest = Field(
        default_factory=MessagesConfigRequest,
        description="Mensagens configuráveis",
    )

    # Ferramentas
    tools: ToolsConfigRequest = Field(
        default_factory=ToolsConfigRequest,
        description="Ferramentas disponíveis",
    )

    # Análise
    analysis: AnalysisConfigRequest = Field(
        default_factory=AnalysisConfigRequest,
        description="Configuração de análise",
    )

    # Privacidade
    privacy: PrivacyConfigRequest = Field(
        default_factory=PrivacyConfigRequest,
        description="Configuração de privacidade",
    )

    # Servidor
    server: ServerConfigRequest = Field(
        default_factory=ServerConfigRequest,
        description="Configuração de servidor",
    )

    # Metadados
    metadata: dict[str, Any] = Field(
        default={},
        description="Metadados customizados",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Atendente Virtual",
                    "description": "Agente para agendamento de consultas",
                    "model": {
                        "provider": "ollama",
                        "model": "llama3:8b",
                        "first_message": "Olá! Bem-vindo à Clínica Saúde. Como posso ajudá-lo hoje?",
                        "system_prompt": "Você é um assistente virtual para agendamento de consultas médicas.",
                        "max_tokens": 250,
                        "temperature": 0.7,
                    },
                    "voice": {
                        "provider": "piper",
                        "voice": "pt_BR-faber-medium",
                        "speed": 1.0,
                    },
                    "transcriber": {
                        "provider": "whisper-local",
                        "model": "large-v3",
                        "language": "pt-BR",
                    },
                }
            ]
        }
    }


class VoiceAgentResponse(BaseModel):
    """Response com dados do Voice Agent."""

    id: str = Field(description="ID único do agente")
    name: str
    description: str

    # Configurações (resumidas)
    model: LLMConfigRequest
    voice: TTSConfigRequest
    transcriber: ASRConfigRequest

    # Estimativas
    estimated_cost_per_minute: float = Field(
        description="Custo estimado por minuto (USD)"
    )
    estimated_latency_ms: int = Field(
        description="Latência estimada (ms)"
    )

    # Timestamps
    created_at: str
    updated_at: str

    # Status
    status: str = Field(
        default="active",
        description="Status do agente: active, inactive, deleted",
    )


class ListVoiceAgentsResponse(BaseModel):
    """Response com lista de Voice Agents."""

    agents: list[VoiceAgentResponse]
    total: int
    page: int
    page_size: int


# =============================================================================
# PRESETS
# =============================================================================

class PresetInfo(BaseModel):
    """Informações sobre um preset."""
    id: str
    name: str
    description: str
    estimated_cost_per_minute: float
    estimated_latency_ms: int
    providers: dict[str, str]  # {"llm": "ollama", "tts": "piper", "asr": "whisper"}


class ListPresetsResponse(BaseModel):
    """Lista de presets disponíveis."""
    presets: list[PresetInfo]

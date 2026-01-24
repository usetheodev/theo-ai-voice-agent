"""Voice Agent Configuration Models.

Modelos de configuração para Voice Agents, seguindo o padrão do Vapi.ai.
Permite que o cliente escolha providers e configure cada aspecto do agente.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# =============================================================================
# ENUMS - Providers e Opções
# =============================================================================

class LLMProvider(str, Enum):
    """Providers de LLM disponíveis."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    TOGETHER = "together"
    CUSTOM = "custom"


class LLMModel(str, Enum):
    """Modelos de LLM disponíveis."""
    # Ollama (local)
    LLAMA3_8B = "llama3:8b"
    LLAMA3_70B = "llama3:70b"
    MISTRAL_7B = "mistral:7b"
    MIXTRAL_8X7B = "mixtral:8x7b"
    QWEN2_7B = "qwen2:7b"

    # OpenAI
    GPT4O = "gpt-4o"
    GPT4O_MINI = "gpt-4o-mini"
    GPT4_TURBO = "gpt-4-turbo"
    GPT35_TURBO = "gpt-3.5-turbo"

    # Anthropic
    CLAUDE_3_OPUS = "claude-3-opus"
    CLAUDE_3_SONNET = "claude-3-sonnet"
    CLAUDE_3_HAIKU = "claude-3-haiku"

    # Groq
    LLAMA3_70B_GROQ = "llama3-70b-8192"
    MIXTRAL_8X7B_GROQ = "mixtral-8x7b-32768"


class ASRProvider(str, Enum):
    """Providers de ASR (Speech-to-Text) disponíveis."""
    WHISPER_LOCAL = "whisper-local"
    WHISPER_API = "whisper-api"
    DEEPGRAM = "deepgram"
    ASSEMBLYAI = "assemblyai"
    GOOGLE = "google"
    AZURE = "azure"
    PARAKEET = "parakeet"
    CUSTOM = "custom"


class ASRModel(str, Enum):
    """Modelos de ASR disponíveis."""
    # Whisper (local)
    WHISPER_TINY = "tiny"
    WHISPER_BASE = "base"
    WHISPER_SMALL = "small"
    WHISPER_MEDIUM = "medium"
    WHISPER_LARGE_V2 = "large-v2"
    WHISPER_LARGE_V3 = "large-v3"
    WHISPER_TURBO = "turbo"

    # Deepgram
    DEEPGRAM_NOVA_2 = "nova-2"
    DEEPGRAM_NOVA_3 = "nova-3"
    DEEPGRAM_ENHANCED = "enhanced"
    DEEPGRAM_BASE = "base"

    # Parakeet (NVIDIA)
    PARAKEET_TDT = "parakeet-tdt"
    PARAKEET_CTC = "parakeet-ctc"


class TTSProvider(str, Enum):
    """Providers de TTS (Text-to-Speech) disponíveis."""
    PIPER = "piper"
    ELEVENLABS = "elevenlabs"
    OPENAI_TTS = "openai-tts"
    AZURE = "azure"
    GOOGLE = "google"
    COQUI = "coqui"
    CUSTOM = "custom"


class TTSVoice(str, Enum):
    """Vozes TTS disponíveis (exemplos)."""
    # Piper (PT-BR)
    PIPER_FABER = "pt_BR-faber-medium"
    PIPER_EDRESSON = "pt_BR-edresson-low"

    # ElevenLabs
    ELEVENLABS_RACHEL = "rachel"
    ELEVENLABS_DREW = "drew"
    ELEVENLABS_CLYDE = "clyde"
    ELEVENLABS_PAUL = "paul"
    ELEVENLABS_DOMI = "domi"
    ELEVENLABS_DAVE = "dave"
    ELEVENLABS_FIN = "fin"
    ELEVENLABS_SARAH = "sarah"
    ELEVENLABS_ANTONI = "antoni"
    ELEVENLABS_THOMAS = "thomas"

    # OpenAI TTS
    OPENAI_ALLOY = "alloy"
    OPENAI_ECHO = "echo"
    OPENAI_FABLE = "fable"
    OPENAI_ONYX = "onyx"
    OPENAI_NOVA = "nova"
    OPENAI_SHIMMER = "shimmer"


class VADProvider(str, Enum):
    """Providers de VAD (Voice Activity Detection) disponíveis."""
    SILERO = "silero"
    WEBRTC = "webrtc"
    ENERGY = "energy"
    CUSTOM = "custom"


class FirstMessageMode(str, Enum):
    """Modo da primeira mensagem."""
    ASSISTANT_SPEAKS_FIRST = "assistant-speaks-first"
    USER_SPEAKS_FIRST = "user-speaks-first"
    ASSISTANT_WAITS_FOR_USER = "assistant-waits-for-user"


class BackgroundSound(str, Enum):
    """Sons de fundo disponíveis."""
    OFF = "off"
    OFFICE = "office"
    CALL_CENTER = "call-center"
    CUSTOM = "custom"


class AudioRecordingFormat(str, Enum):
    """Formatos de gravação de áudio."""
    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"
    WEBM = "webm"


class SmartEndpointing(str, Enum):
    """Modos de Smart Endpointing."""
    OFF = "off"
    ON = "on"


class VoicemailDetectionProvider(str, Enum):
    """Providers de detecção de voicemail."""
    OFF = "off"
    VAPI = "vapi"
    GOOGLE = "google"
    TWILIO = "twilio"


# =============================================================================
# MODEL CONFIG - Configuração do LLM
# =============================================================================

@dataclass
class LLMConfig:
    """Configuração do modelo de linguagem (LLM).

    Equivalente à seção "MODEL" do Vapi.ai.
    """

    # Provider e modelo
    provider: LLMProvider = LLMProvider.OLLAMA
    model: str = "llama3:8b"

    # Mensagens
    first_message_mode: FirstMessageMode = FirstMessageMode.ASSISTANT_SPEAKS_FIRST
    first_message: str = "Olá! Como posso ajudá-lo hoje?"
    system_prompt: str = "Você é um assistente de voz amigável e prestativo."

    # Parâmetros de geração
    max_tokens: int = 250
    temperature: float = 0.7
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    # API (para providers cloud)
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None

    # Ollama específico
    ollama_host: str = "http://localhost:11434"

    # Timeout
    timeout_seconds: int = 30


# =============================================================================
# VOICE CONFIG - Configuração do TTS
# =============================================================================

@dataclass
class FallbackVoice:
    """Voz de fallback caso a primária falhe."""
    provider: TTSProvider
    voice: str
    priority: int = 0


@dataclass
class TTSConfig:
    """Configuração de Text-to-Speech (TTS).

    Equivalente à seção "VOICE" do Vapi.ai.
    """

    # Provider e voz
    provider: TTSProvider = TTSProvider.PIPER
    voice: str = "pt_BR-faber-medium"

    # Configurações de áudio
    sample_rate: int = 24000
    speed: float = 1.0
    pitch: float = 1.0

    # Som de fundo
    background_sound: BackgroundSound = BackgroundSound.OFF
    background_sound_url: Optional[str] = None
    background_sound_volume: float = 0.1

    # Streaming
    input_min_characters: int = 30
    punctuation_boundaries: list[str] = field(
        default_factory=lambda: [".", "!", "?", ";", ":", ","]
    )

    # Fallbacks
    fallback_voices: list[FallbackVoice] = field(default_factory=list)

    # API (para providers cloud)
    api_key: Optional[str] = None

    # Piper específico
    piper_model_path: Optional[str] = None

    # ElevenLabs específico
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity_boost: float = 0.75

    # Timeout
    timeout_seconds: int = 30


# =============================================================================
# TRANSCRIBER CONFIG - Configuração do ASR
# =============================================================================

@dataclass
class FallbackTranscriber:
    """Transcriber de fallback caso o primário falhe."""
    provider: ASRProvider
    model: str
    priority: int = 0


@dataclass
class ASRConfig:
    """Configuração de Speech-to-Text (ASR/Transcriber).

    Equivalente à seção "TRANSCRIBER" do Vapi.ai.
    """

    # Provider e modelo
    provider: ASRProvider = ASRProvider.WHISPER_LOCAL
    model: str = "large-v3"
    language: str = "pt-BR"

    # Processamento
    background_denoising: bool = True
    use_numerals: bool = True

    # Confiança
    confidence_threshold: float = 0.4

    # Keyterms (boost para palavras específicas)
    keyterms: list[str] = field(default_factory=list)

    # Streaming
    streaming_enabled: bool = True
    interim_results: bool = True

    # VAD integrado ao ASR
    vad_enabled: bool = True
    vad_threshold: float = 0.5

    # Fallbacks
    fallback_transcribers: list[FallbackTranscriber] = field(default_factory=list)

    # API (para providers cloud)
    api_key: Optional[str] = None

    # Whisper específico
    whisper_compute_type: str = "float16"  # float16, int8, int8_float16
    whisper_device: str = "cuda"  # cuda, cpu
    whisper_beam_size: int = 5

    # Deepgram específico
    deepgram_tier: str = "nova"
    deepgram_punctuate: bool = True
    deepgram_diarize: bool = False

    # Timeout
    timeout_seconds: int = 30


# =============================================================================
# VAD CONFIG - Configuração de Voice Activity Detection
# =============================================================================

@dataclass
class VADConfig:
    """Configuração de Voice Activity Detection (VAD)."""

    provider: VADProvider = VADProvider.SILERO

    # Thresholds
    speech_threshold: float = 0.5
    silence_threshold: float = 0.3

    # Durações
    min_speech_duration_ms: int = 200
    min_silence_duration_ms: int = 500
    max_speech_duration_ms: int = 30000

    # Padding
    speech_pad_ms: int = 30


# =============================================================================
# START SPEAKING PLAN - Quando o assistente deve começar a falar
# =============================================================================

@dataclass
class StartSpeakingPlan:
    """Plano de quando o assistente deve começar a falar.

    Equivalente à seção "Start Speaking Plan" do Vapi.ai.
    """

    # Delay inicial
    wait_seconds: float = 0.4

    # Smart Endpointing
    smart_endpointing: SmartEndpointing = SmartEndpointing.OFF

    # Segundos de espera após diferentes tipos de transcrição
    on_punctuation_seconds: float = 0.1  # Após pontuação
    on_no_punctuation_seconds: float = 1.5  # Sem pontuação
    on_number_seconds: float = 0.5  # Após número


# =============================================================================
# STOP SPEAKING PLAN - Quando o assistente deve parar de falar (barge-in)
# =============================================================================

@dataclass
class StopSpeakingPlan:
    """Plano de quando o assistente deve parar de falar (barge-in).

    Equivalente à seção "Stop Speaking Plan" do Vapi.ai.
    """

    # Número de palavras que o usuário precisa falar para interromper
    num_words: int = 0  # 0 = qualquer palavra interrompe

    # Segundos que o usuário precisa falar para interromper
    voice_seconds: float = 0.2

    # Segundos de espera antes de voltar a falar após interrupção
    backoff_seconds: float = 1.0


# =============================================================================
# CALL TIMEOUT SETTINGS - Configurações de timeout
# =============================================================================

@dataclass
class CallTimeoutSettings:
    """Configurações de timeout da chamada.

    Equivalente à seção "Call Timeout Settings" do Vapi.ai.
    """

    # Timeout por silêncio (segundos)
    silence_timeout_seconds: int = 30

    # Duração máxima da chamada (segundos)
    max_duration_seconds: int = 600  # 10 minutos


# =============================================================================
# MESSAGES CONFIG - Mensagens configuráveis
# =============================================================================

@dataclass
class IdleMessage:
    """Mensagem para quando o usuário não responde."""
    message: str
    wait_seconds: float = 7.5


@dataclass
class MessagesConfig:
    """Configuração de mensagens do assistente.

    Equivalente à seção "Messaging" do Vapi.ai.
    """

    # Mensagem de voicemail
    voicemail_message: Optional[str] = None

    # Mensagem de encerramento
    end_call_message: Optional[str] = None

    # Mensagens de idle
    idle_messages: list[IdleMessage] = field(default_factory=list)
    max_idle_messages: int = 3
    idle_timeout_seconds: float = 7.5


# =============================================================================
# PRIVACY CONFIG - Configurações de privacidade
# =============================================================================

@dataclass
class PrivacyConfig:
    """Configurações de privacidade e gravação.

    Equivalente à seção "Privacy" do Vapi.ai.
    """

    # HIPAA compliance (desabilita logs)
    hipaa_enabled: bool = False

    # Gravação
    audio_recording_enabled: bool = True
    audio_recording_format: AudioRecordingFormat = AudioRecordingFormat.WAV
    video_recording_enabled: bool = False

    # Logs e transcrições
    logging_enabled: bool = True
    transcript_enabled: bool = True


# =============================================================================
# TOOLS CONFIG - Configuração de ferramentas
# =============================================================================

@dataclass
class ToolConfig:
    """Configuração de uma ferramenta/função."""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    endpoint_url: Optional[str] = None
    enabled: bool = True


@dataclass
class ToolsConfig:
    """Configuração de ferramentas disponíveis.

    Equivalente à seção "TOOLS" do Vapi.ai.
    """

    # Funções predefinidas
    end_call_enabled: bool = True
    dial_keypad_enabled: bool = False
    forwarding_phone_number: Optional[str] = None

    # Ferramentas customizadas
    custom_tools: list[ToolConfig] = field(default_factory=list)


# =============================================================================
# ANALYSIS CONFIG - Configuração de análise pós-chamada
# =============================================================================

@dataclass
class StructuredOutput:
    """Definição de output estruturado para análise."""
    name: str
    description: str
    json_schema: dict[str, Any]


@dataclass
class AnalysisConfig:
    """Configuração de análise de chamadas.

    Equivalente à seção "ANALYSIS" do Vapi.ai.
    """

    # Structured outputs
    structured_outputs: list[StructuredOutput] = field(default_factory=list)

    # Summary (deprecated no Vapi, mas útil)
    summary_enabled: bool = True
    summary_prompt: str = "Resuma a chamada em 2-3 frases."
    summary_timeout_seconds: int = 10

    # Success evaluation
    success_evaluation_enabled: bool = False
    success_evaluation_prompt: Optional[str] = None
    success_evaluation_timeout_seconds: int = 10


# =============================================================================
# SERVER CONFIG - Configuração de servidor/webhooks
# =============================================================================

@dataclass
class ServerConfig:
    """Configuração de servidor para webhooks.

    Equivalente à seção "Server Settings" do Vapi.ai.
    """

    # URL do servidor
    server_url: Optional[str] = None
    timeout_seconds: int = 20

    # Autenticação
    auth_header: Optional[str] = None
    auth_value: Optional[str] = None

    # Headers customizados
    custom_headers: dict[str, str] = field(default_factory=dict)

    # Mensagens para enviar ao servidor
    server_messages: list[str] = field(default_factory=lambda: [
        "transcript",
        "function-call",
        "end-of-call-report",
    ])


# =============================================================================
# VOICE AGENT CONFIG - Configuração completa do agente
# =============================================================================

@dataclass
class VoiceAgentConfig:
    """Configuração completa de um Voice Agent.

    Esta é a configuração principal que agrupa todas as outras.
    O cliente pode personalizar cada aspecto do agente.

    Baseado no formulário do Vapi.ai.
    """

    # Identificação
    name: str = "Voice Agent"
    description: str = ""

    # Configurações principais
    model: LLMConfig = field(default_factory=LLMConfig)
    voice: TTSConfig = field(default_factory=TTSConfig)
    transcriber: ASRConfig = field(default_factory=ASRConfig)
    vad: VADConfig = field(default_factory=VADConfig)

    # Planos de fala
    start_speaking_plan: StartSpeakingPlan = field(default_factory=StartSpeakingPlan)
    stop_speaking_plan: StopSpeakingPlan = field(default_factory=StopSpeakingPlan)

    # Timeouts
    call_timeout: CallTimeoutSettings = field(default_factory=CallTimeoutSettings)

    # Mensagens
    messages: MessagesConfig = field(default_factory=MessagesConfig)

    # Ferramentas
    tools: ToolsConfig = field(default_factory=ToolsConfig)

    # Análise
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)

    # Privacidade
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)

    # Servidor
    server: ServerConfig = field(default_factory=ServerConfig)

    # Metadados
    metadata: dict[str, Any] = field(default_factory=dict)

    def estimate_cost_per_minute(self) -> float:
        """Estima custo por minuto baseado nos providers selecionados."""
        cost = 0.0

        # LLM costs (estimativa)
        llm_costs = {
            LLMProvider.OLLAMA: 0.00,  # Local
            LLMProvider.OPENAI: 0.06,
            LLMProvider.ANTHROPIC: 0.08,
            LLMProvider.GROQ: 0.01,
        }
        cost += llm_costs.get(self.model.provider, 0.05)

        # ASR costs (estimativa)
        asr_costs = {
            ASRProvider.WHISPER_LOCAL: 0.00,  # Local
            ASRProvider.DEEPGRAM: 0.0043,
            ASRProvider.ASSEMBLYAI: 0.006,
        }
        cost += asr_costs.get(self.transcriber.provider, 0.004)

        # TTS costs (estimativa)
        tts_costs = {
            TTSProvider.PIPER: 0.00,  # Local
            TTSProvider.ELEVENLABS: 0.03,
            TTSProvider.OPENAI_TTS: 0.015,
        }
        cost += tts_costs.get(self.voice.provider, 0.02)

        return cost

    def estimate_latency_ms(self) -> int:
        """Estima latência baseado nos providers selecionados."""
        latency = 0

        # LLM latency (estimativa)
        llm_latency = {
            LLMProvider.OLLAMA: 200,  # Local
            LLMProvider.OPENAI: 400,
            LLMProvider.ANTHROPIC: 500,
            LLMProvider.GROQ: 100,  # Muito rápido
        }
        latency += llm_latency.get(self.model.provider, 300)

        # ASR latency (estimativa)
        asr_latency = {
            ASRProvider.WHISPER_LOCAL: 300,  # Local
            ASRProvider.DEEPGRAM: 150,
            ASRProvider.PARAKEET: 100,  # Streaming local
        }
        latency += asr_latency.get(self.transcriber.provider, 200)

        # TTS latency (estimativa)
        tts_latency = {
            TTSProvider.PIPER: 50,  # Local
            TTSProvider.ELEVENLABS: 200,
            TTSProvider.OPENAI_TTS: 300,
        }
        latency += tts_latency.get(self.voice.provider, 150)

        return latency


# =============================================================================
# FACTORY FUNCTIONS - Criação de configurações pré-definidas
# =============================================================================

def create_local_agent_config(
    name: str = "Local Voice Agent",
    system_prompt: str = "Você é um assistente de voz amigável.",
    first_message: str = "Olá! Como posso ajudá-lo hoje?",
    language: str = "pt-BR",
) -> VoiceAgentConfig:
    """Cria configuração de agente totalmente local (sem APIs externas).

    Ideal para:
    - Privacidade máxima
    - Custo zero
    - Funcionamento offline

    Trade-off: Latência pode ser maior dependendo do hardware.
    """
    return VoiceAgentConfig(
        name=name,
        model=LLMConfig(
            provider=LLMProvider.OLLAMA,
            model="llama3:8b",
            system_prompt=system_prompt,
            first_message=first_message,
            first_message_mode=FirstMessageMode.ASSISTANT_SPEAKS_FIRST,
        ),
        voice=TTSConfig(
            provider=TTSProvider.PIPER,
            voice="pt_BR-faber-medium",
        ),
        transcriber=ASRConfig(
            provider=ASRProvider.WHISPER_LOCAL,
            model="large-v3",
            language=language,
        ),
        vad=VADConfig(
            provider=VADProvider.SILERO,
        ),
    )


def create_low_latency_agent_config(
    name: str = "Low Latency Agent",
    system_prompt: str = "Você é um assistente de voz amigável.",
    first_message: str = "Olá! Como posso ajudá-lo hoje?",
    language: str = "pt-BR",
    groq_api_key: Optional[str] = None,
    deepgram_api_key: Optional[str] = None,
) -> VoiceAgentConfig:
    """Cria configuração de agente otimizada para baixa latência.

    Usa:
    - Groq para LLM (inferência ultra-rápida)
    - Deepgram para ASR (streaming de baixa latência)
    - Piper local para TTS

    Latência estimada: ~350ms
    """
    return VoiceAgentConfig(
        name=name,
        model=LLMConfig(
            provider=LLMProvider.GROQ,
            model="llama3-70b-8192",
            system_prompt=system_prompt,
            first_message=first_message,
            api_key=groq_api_key,
        ),
        voice=TTSConfig(
            provider=TTSProvider.PIPER,
            voice="pt_BR-faber-medium",
        ),
        transcriber=ASRConfig(
            provider=ASRProvider.DEEPGRAM,
            model="nova-3",
            language=language,
            api_key=deepgram_api_key,
        ),
        vad=VADConfig(
            provider=VADProvider.SILERO,
        ),
    )


def create_high_quality_agent_config(
    name: str = "High Quality Agent",
    system_prompt: str = "Você é um assistente de voz amigável.",
    first_message: str = "Olá! Como posso ajudá-lo hoje?",
    language: str = "pt-BR",
    openai_api_key: Optional[str] = None,
    elevenlabs_api_key: Optional[str] = None,
) -> VoiceAgentConfig:
    """Cria configuração de agente otimizada para qualidade.

    Usa:
    - OpenAI GPT-4o para LLM (melhor compreensão)
    - Whisper para ASR (alta precisão)
    - ElevenLabs para TTS (melhor qualidade de voz)

    Trade-off: Maior latência e custo.
    """
    return VoiceAgentConfig(
        name=name,
        model=LLMConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            system_prompt=system_prompt,
            first_message=first_message,
            api_key=openai_api_key,
        ),
        voice=TTSConfig(
            provider=TTSProvider.ELEVENLABS,
            voice="rachel",
            api_key=elevenlabs_api_key,
        ),
        transcriber=ASRConfig(
            provider=ASRProvider.WHISPER_LOCAL,
            model="large-v3",
            language=language,
        ),
        vad=VADConfig(
            provider=VADProvider.SILERO,
        ),
    )

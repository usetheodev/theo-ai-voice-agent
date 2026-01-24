"""Voice Agent API endpoints.

Endpoints REST para criar, listar, atualizar e deletar Voice Agents.
Similar à API do Vapi.ai.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .schemas.agent_schemas import (
    CreateVoiceAgentRequest,
    ListPresetsResponse,
    ListVoiceAgentsResponse,
    PresetInfo,
    VoiceAgentResponse,
)
from ..models.agent_config import (
    VoiceAgentConfig,
    LLMConfig,
    TTSConfig,
    ASRConfig,
    LLMProvider,
    TTSProvider,
    ASRProvider,
    create_local_agent_config,
    create_low_latency_agent_config,
    create_high_quality_agent_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agents", tags=["Voice Agents"])

# In-memory storage (em produção, usar banco de dados)
_agents: dict[str, dict] = {}


def _request_to_config(request: CreateVoiceAgentRequest) -> VoiceAgentConfig:
    """Converte request da API para VoiceAgentConfig interno."""
    return VoiceAgentConfig(
        name=request.name,
        description=request.description,
        model=LLMConfig(
            provider=LLMProvider(request.model.provider),
            model=request.model.model,
            first_message=request.model.first_message,
            system_prompt=request.model.system_prompt,
            max_tokens=request.model.max_tokens,
            temperature=request.model.temperature,
            api_key=request.model.api_key,
        ),
        voice=TTSConfig(
            provider=TTSProvider(request.voice.provider),
            voice=request.voice.voice,
            speed=request.voice.speed,
            api_key=request.voice.api_key,
        ),
        transcriber=ASRConfig(
            provider=ASRProvider(request.transcriber.provider),
            model=request.transcriber.model,
            language=request.transcriber.language,
            background_denoising=request.transcriber.background_denoising,
            confidence_threshold=request.transcriber.confidence_threshold,
            keyterms=request.transcriber.keyterms,
            api_key=request.transcriber.api_key,
        ),
    )


def _config_to_response(
    agent_id: str,
    config: VoiceAgentConfig,
    created_at: str,
    updated_at: str,
    status: str = "active",
) -> VoiceAgentResponse:
    """Converte VoiceAgentConfig para response da API."""
    from .schemas.agent_schemas import LLMConfigRequest, TTSConfigRequest, ASRConfigRequest

    return VoiceAgentResponse(
        id=agent_id,
        name=config.name,
        description=config.description,
        model=LLMConfigRequest(
            provider=config.model.provider.value,
            model=config.model.model,
            first_message_mode=config.model.first_message_mode.value,
            first_message=config.model.first_message,
            system_prompt=config.model.system_prompt,
            max_tokens=config.model.max_tokens,
            temperature=config.model.temperature,
        ),
        voice=TTSConfigRequest(
            provider=config.voice.provider.value,
            voice=config.voice.voice,
            speed=config.voice.speed,
        ),
        transcriber=ASRConfigRequest(
            provider=config.transcriber.provider.value,
            model=config.transcriber.model,
            language=config.transcriber.language,
            background_denoising=config.transcriber.background_denoising,
            confidence_threshold=config.transcriber.confidence_threshold,
            keyterms=config.transcriber.keyterms,
        ),
        estimated_cost_per_minute=config.estimate_cost_per_minute(),
        estimated_latency_ms=config.estimate_latency_ms(),
        created_at=created_at,
        updated_at=updated_at,
        status=status,
    )


# =============================================================================
# PRESETS - Configurações pré-definidas
# =============================================================================

PRESETS = {
    "local": {
        "name": "100% Local",
        "description": "Totalmente local, sem APIs externas. Custo zero, máxima privacidade.",
        "factory": create_local_agent_config,
        "providers": {"llm": "ollama", "tts": "piper", "asr": "whisper-local"},
    },
    "low-latency": {
        "name": "Baixa Latência",
        "description": "Otimizado para resposta rápida. Usa Groq + Deepgram.",
        "factory": create_low_latency_agent_config,
        "providers": {"llm": "groq", "tts": "piper", "asr": "deepgram"},
    },
    "high-quality": {
        "name": "Alta Qualidade",
        "description": "Melhor compreensão e voz. Usa GPT-4o + ElevenLabs.",
        "factory": create_high_quality_agent_config,
        "providers": {"llm": "openai", "tts": "elevenlabs", "asr": "whisper-local"},
    },
}


@router.get("/presets", response_model=ListPresetsResponse)
async def list_presets() -> ListPresetsResponse:
    """Lista presets de configuração disponíveis.

    Presets são configurações pré-definidas otimizadas para diferentes casos de uso:
    - **local**: 100% local, custo zero, máxima privacidade
    - **low-latency**: Otimizado para baixa latência (~350ms)
    - **high-quality**: Melhor qualidade de compreensão e voz
    """
    presets = []

    for preset_id, preset_data in PRESETS.items():
        config = preset_data["factory"]()
        presets.append(
            PresetInfo(
                id=preset_id,
                name=preset_data["name"],
                description=preset_data["description"],
                estimated_cost_per_minute=config.estimate_cost_per_minute(),
                estimated_latency_ms=config.estimate_latency_ms(),
                providers=preset_data["providers"],
            )
        )

    return ListPresetsResponse(presets=presets)


@router.post("/from-preset/{preset_id}", response_model=VoiceAgentResponse)
async def create_agent_from_preset(
    preset_id: str,
    name: str = Query(default="Voice Agent", description="Nome do agente"),
    system_prompt: str = Query(
        default="Você é um assistente de voz amigável.",
        description="System prompt",
    ),
    first_message: str = Query(
        default="Olá! Como posso ajudá-lo hoje?",
        description="Primeira mensagem",
    ),
    language: str = Query(default="pt-BR", description="Idioma"),
) -> VoiceAgentResponse:
    """Cria um Voice Agent a partir de um preset.

    Simplifica a criação usando configurações pré-otimizadas.
    """
    if preset_id not in PRESETS:
        raise HTTPException(
            status_code=404,
            detail=f"Preset não encontrado: {preset_id}. Disponíveis: {list(PRESETS.keys())}",
        )

    preset = PRESETS[preset_id]
    config = preset["factory"](
        name=name,
        system_prompt=system_prompt,
        first_message=first_message,
        language=language,
    )

    # Gerar ID e timestamps
    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # Salvar
    _agents[agent_id] = {
        "config": config,
        "created_at": now,
        "updated_at": now,
        "status": "active",
    }

    logger.info(f"Agent created from preset: {agent_id} (preset={preset_id})")

    return _config_to_response(agent_id, config, now, now)


# =============================================================================
# CRUD - Voice Agents
# =============================================================================

@router.post("", response_model=VoiceAgentResponse)
async def create_agent(request: CreateVoiceAgentRequest) -> VoiceAgentResponse:
    """Cria um novo Voice Agent com configuração customizada.

    Permite configurar todos os aspectos do agente:
    - **model**: LLM (provider, modelo, prompt, temperature, etc.)
    - **voice**: TTS (provider, voz, velocidade, etc.)
    - **transcriber**: ASR (provider, modelo, idioma, etc.)
    - **start_speaking_plan**: Quando o assistente começa a falar
    - **stop_speaking_plan**: Quando o assistente para de falar (barge-in)
    - **tools**: Ferramentas disponíveis
    - **analysis**: Configuração de análise pós-chamada
    - **privacy**: Configurações de privacidade

    Similar ao formulário de criação do Vapi.ai.
    """
    config = _request_to_config(request)

    # Gerar ID e timestamps
    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # Salvar
    _agents[agent_id] = {
        "config": config,
        "created_at": now,
        "updated_at": now,
        "status": "active",
    }

    logger.info(f"Agent created: {agent_id} (name={config.name})")

    return _config_to_response(agent_id, config, now, now)


@router.get("", response_model=ListVoiceAgentsResponse)
async def list_agents(
    page: int = Query(default=1, ge=1, description="Página"),
    page_size: int = Query(default=20, ge=1, le=100, description="Itens por página"),
    status: Optional[str] = Query(default=None, description="Filtrar por status"),
) -> ListVoiceAgentsResponse:
    """Lista todos os Voice Agents."""
    agents_list = []

    for agent_id, agent_data in _agents.items():
        if agent_data["status"] == "deleted":
            continue

        if status and agent_data["status"] != status:
            continue

        agents_list.append(
            _config_to_response(
                agent_id,
                agent_data["config"],
                agent_data["created_at"],
                agent_data["updated_at"],
                agent_data["status"],
            )
        )

    # Paginação
    total = len(agents_list)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = agents_list[start:end]

    return ListVoiceAgentsResponse(
        agents=paginated,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{agent_id}", response_model=VoiceAgentResponse)
async def get_agent(agent_id: str) -> VoiceAgentResponse:
    """Obtém detalhes de um Voice Agent."""
    if agent_id not in _agents:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_data = _agents[agent_id]

    if agent_data["status"] == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")

    return _config_to_response(
        agent_id,
        agent_data["config"],
        agent_data["created_at"],
        agent_data["updated_at"],
        agent_data["status"],
    )


@router.patch("/{agent_id}", response_model=VoiceAgentResponse)
async def update_agent(
    agent_id: str,
    request: CreateVoiceAgentRequest,
) -> VoiceAgentResponse:
    """Atualiza um Voice Agent existente."""
    if agent_id not in _agents:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_data = _agents[agent_id]

    if agent_data["status"] == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")

    # Atualizar config
    config = _request_to_config(request)
    now = datetime.now(timezone.utc).isoformat()

    agent_data["config"] = config
    agent_data["updated_at"] = now

    logger.info(f"Agent updated: {agent_id}")

    return _config_to_response(
        agent_id,
        config,
        agent_data["created_at"],
        now,
        agent_data["status"],
    )


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str) -> dict:
    """Deleta um Voice Agent (soft delete)."""
    if agent_id not in _agents:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_data = _agents[agent_id]
    agent_data["status"] = "deleted"
    agent_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info(f"Agent deleted: {agent_id}")

    return {"message": "Agent deleted", "id": agent_id}


# =============================================================================
# PROVIDERS - Listar providers disponíveis
# =============================================================================

@router.get("/providers/llm")
async def list_llm_providers() -> dict:
    """Lista providers de LLM disponíveis com seus modelos."""
    return {
        "providers": [
            {
                "id": "ollama",
                "name": "Ollama (Local)",
                "description": "Execução local de LLMs. Custo zero.",
                "models": [
                    {"id": "llama3:8b", "name": "Llama 3 8B", "context_length": 8192},
                    {"id": "llama3:70b", "name": "Llama 3 70B", "context_length": 8192},
                    {"id": "mistral:7b", "name": "Mistral 7B", "context_length": 32768},
                    {"id": "mixtral:8x7b", "name": "Mixtral 8x7B", "context_length": 32768},
                    {"id": "qwen2:7b", "name": "Qwen2 7B", "context_length": 32768},
                ],
                "requires_api_key": False,
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "description": "GPT-4o e outros modelos OpenAI.",
                "models": [
                    {"id": "gpt-4o", "name": "GPT-4o", "context_length": 128000},
                    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context_length": 128000},
                    {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "context_length": 128000},
                ],
                "requires_api_key": True,
            },
            {
                "id": "anthropic",
                "name": "Anthropic",
                "description": "Claude 3 e outros modelos Anthropic.",
                "models": [
                    {"id": "claude-3-opus", "name": "Claude 3 Opus", "context_length": 200000},
                    {"id": "claude-3-sonnet", "name": "Claude 3 Sonnet", "context_length": 200000},
                    {"id": "claude-3-haiku", "name": "Claude 3 Haiku", "context_length": 200000},
                ],
                "requires_api_key": True,
            },
            {
                "id": "groq",
                "name": "Groq",
                "description": "Inferência ultra-rápida. Ideal para baixa latência.",
                "models": [
                    {"id": "llama3-70b-8192", "name": "Llama 3 70B", "context_length": 8192},
                    {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "context_length": 32768},
                ],
                "requires_api_key": True,
            },
        ]
    }


@router.get("/providers/tts")
async def list_tts_providers() -> dict:
    """Lista providers de TTS disponíveis com suas vozes."""
    return {
        "providers": [
            {
                "id": "piper",
                "name": "Piper (Local)",
                "description": "TTS local de alta qualidade. Custo zero.",
                "voices": [
                    {"id": "pt_BR-faber-medium", "name": "Faber (PT-BR)", "language": "pt-BR"},
                    {"id": "pt_BR-edresson-low", "name": "Edresson (PT-BR)", "language": "pt-BR"},
                    {"id": "en_US-lessac-medium", "name": "Lessac (EN-US)", "language": "en-US"},
                ],
                "requires_api_key": False,
            },
            {
                "id": "elevenlabs",
                "name": "ElevenLabs",
                "description": "Vozes de altíssima qualidade e naturalidade.",
                "voices": [
                    {"id": "rachel", "name": "Rachel", "language": "multi"},
                    {"id": "drew", "name": "Drew", "language": "multi"},
                    {"id": "paul", "name": "Paul", "language": "multi"},
                    {"id": "sarah", "name": "Sarah", "language": "multi"},
                ],
                "requires_api_key": True,
            },
            {
                "id": "openai-tts",
                "name": "OpenAI TTS",
                "description": "TTS da OpenAI com vozes naturais.",
                "voices": [
                    {"id": "alloy", "name": "Alloy", "language": "multi"},
                    {"id": "echo", "name": "Echo", "language": "multi"},
                    {"id": "fable", "name": "Fable", "language": "multi"},
                    {"id": "onyx", "name": "Onyx", "language": "multi"},
                    {"id": "nova", "name": "Nova", "language": "multi"},
                    {"id": "shimmer", "name": "Shimmer", "language": "multi"},
                ],
                "requires_api_key": True,
            },
        ]
    }


@router.get("/providers/asr")
async def list_asr_providers() -> dict:
    """Lista providers de ASR disponíveis com seus modelos."""
    return {
        "providers": [
            {
                "id": "whisper-local",
                "name": "Whisper (Local)",
                "description": "OpenAI Whisper executado localmente. Custo zero.",
                "models": [
                    {"id": "tiny", "name": "Tiny", "size": "39M", "speed": "32x"},
                    {"id": "base", "name": "Base", "size": "74M", "speed": "16x"},
                    {"id": "small", "name": "Small", "size": "244M", "speed": "6x"},
                    {"id": "medium", "name": "Medium", "size": "769M", "speed": "2x"},
                    {"id": "large-v3", "name": "Large V3", "size": "1550M", "speed": "1x"},
                    {"id": "turbo", "name": "Turbo", "size": "809M", "speed": "8x"},
                ],
                "requires_api_key": False,
            },
            {
                "id": "deepgram",
                "name": "Deepgram",
                "description": "ASR de baixa latência com streaming.",
                "models": [
                    {"id": "nova-3", "name": "Nova 3", "description": "Mais preciso"},
                    {"id": "nova-2", "name": "Nova 2", "description": "Balanceado"},
                    {"id": "enhanced", "name": "Enhanced", "description": "Melhor para ruído"},
                ],
                "requires_api_key": True,
            },
            {
                "id": "parakeet",
                "name": "Parakeet (NVIDIA)",
                "description": "ASR streaming local com NVIDIA NeMo.",
                "models": [
                    {"id": "parakeet-tdt", "name": "Parakeet TDT", "description": "Token-and-Duration Transducer"},
                    {"id": "parakeet-ctc", "name": "Parakeet CTC", "description": "CTC decoder"},
                ],
                "requires_api_key": False,
            },
        ]
    }

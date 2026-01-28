"""Voice Agent using the full VoiceAgent.builder() API.

This demonstrates all the features of the voice-pipeline framework
using the fluent builder pattern.
"""

import os
from voice_pipeline import VoiceAgent
from voice_pipeline.tools import voice_tool


# =============================================================================
# Environment Configuration
# =============================================================================

VP_LANGUAGE = os.environ.get("ASR_LANGUAGE", "pt")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:0.6b")
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "kokoro")
TTS_VOICE = os.environ.get("TTS_VOICE", "pf_dora")
ASR_MODEL = os.environ.get("ASR_MODEL", "base")


# =============================================================================
# Demo Tools
# =============================================================================

@voice_tool
def get_current_time() -> str:
    """Get the current time."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


@voice_tool
def get_weather(city: str) -> str:
    """Get the weather forecast for a city.

    Args:
        city: Name of the city
    """
    # Simulated weather data
    import random
    temps = random.randint(15, 35)
    conditions = random.choice(["ensolarado", "nublado", "chuvoso", "parcialmente nublado"])
    return f"O clima em {city} está {conditions} com temperatura de {temps}°C"


@voice_tool
def calculate(expression: str) -> str:
    """Perform a mathematical calculation.

    Args:
        expression: Mathematical expression to evaluate (e.g., "2 + 2")
    """
    try:
        # Safe evaluation for basic math
        allowed = set("0123456789+-*/.() ")
        if all(c in allowed for c in expression):
            result = eval(expression)
            return f"O resultado é {result}"
        else:
            return "Expressão inválida"
    except Exception as e:
        return f"Erro no cálculo: {str(e)}"


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """Você é Dora, uma assistente de voz brasileira amigável e concisa.

## Ferramentas disponíveis:
- get_current_time: Use APENAS quando perguntarem as horas
- get_weather: Use APENAS quando perguntarem sobre clima/tempo meteorológico de uma cidade
- calculate: Use APENAS quando pedirem cálculos matemáticos

## Regras:
1. Responda em português brasileiro
2. Seja breve (1-2 frases)
3. Para saudações (oi, olá, tudo bem, etc): responda diretamente SEM usar ferramentas
4. Use ferramentas SOMENTE quando necessário para responder à pergunta
5. Após usar uma ferramenta, responda com base no resultado retornado

## Exemplos:
- "Oi" → "Oi! Como posso ajudar?"
- "Que horas são?" → [use get_current_time] → "São 14:30"
- "Clima em SP?" → [use get_weather com city="São Paulo"] → responda com o resultado"""


# =============================================================================
# Agent Builder
# =============================================================================

def create_voice_agent():
    """Create a configured voice agent using the builder pattern.

    This demonstrates the full builder API with all available features.
    """
    # Build the agent using the fluent builder API
    builder = (
        VoiceAgent.builder()
        # ASR Configuration
        .asr(
            "faster-whisper",
            model=ASR_MODEL,
            language=VP_LANGUAGE,
            compute_type="int8",
            vad_filter=True,
        )
        # LLM Configuration
        .llm(
            LLM_PROVIDER,
            model=LLM_MODEL,
        )
        # TTS Configuration
        .tts(
            TTS_PROVIDER,
            voice=TTS_VOICE,
        )
        # VAD Configuration
        .vad("silero")
        # Turn-taking (when user finishes speaking)
        .turn_taking(
            "adaptive",
            base_threshold_ms=600,
            min_threshold_ms=400,
            max_threshold_ms=1500,
        )
        # Streaming granularity (how LLM output is sent to TTS)
        .streaming_granularity(
            "adaptive",
            first_chunk_words=3,
            clause_min_chars=10,
            clause_max_chars=150,
            language=VP_LANGUAGE,
        )
        # Interruption handling (barge-in)
        .interruption(
            "backchannel",
            backchannel_max_ms=500,
            interruption_min_ms=800,
            language=VP_LANGUAGE,
            use_transcript=True,
        )
        # System prompt
        .system_prompt(SYSTEM_PROMPT)
        # Enable streaming for low latency
        .streaming(True)
        # Basic memory for conversation context
        .memory(max_messages=50)
        # Tools
        .tools([
            get_current_time,
            get_weather,
            calculate,
        ])
        # Tool execution timeout
        .tool_execution_timeout(30)
        # Maximum agent iterations (for tool loops)
        .max_iterations(10)
    )

    return builder


def create_agent_with_mcp(mcp_server_url: str = "http://localhost:8001/mcp"):
    """Create an agent with MCP server integration.

    Args:
        mcp_server_url: URL of the MCP server
    """
    builder = (
        VoiceAgent.builder()
        .llm(LLM_PROVIDER, model=LLM_MODEL)
        .system_prompt(SYSTEM_PROMPT)
        # Local tools
        .tools([get_current_time, get_weather, calculate])
        # MCP server configuration
        .mcp_servers({
            "external": mcp_server_url,
        })
        .mcp_timeout(10)
        .tool_execution_timeout(30)
    )

    return builder


async def build_and_connect():
    """Build and connect all providers.

    Returns:
        Configured and connected voice chain/agent
    """
    builder = create_voice_agent()

    # build_async() connects all providers and performs warmup
    agent = await builder.build_async()

    return agent


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "create_voice_agent",
    "create_agent_with_mcp",
    "build_and_connect",
    "SYSTEM_PROMPT",
    "get_current_time",
    "get_weather",
    "calculate",
]

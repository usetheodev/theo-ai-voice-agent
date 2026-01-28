"""Demo tools for the WebRTC voice agent demo."""

import random
from datetime import datetime
from typing import Any

from voice_pipeline.tools.base import FunctionTool, ToolResult, VoiceTool


async def get_current_time(timezone: str = "America/Sao_Paulo") -> ToolResult:
    """Get the current time.

    Args:
        timezone: Timezone name (default: America/Sao_Paulo).

    Returns:
        Current time information.
    """
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        return ToolResult(
            success=True,
            output={
                "time": now.strftime("%H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "day_of_week": now.strftime("%A"),
                "timezone": timezone,
                "formatted": now.strftime("%d de %B de %Y, %H:%M"),
            },
        )
    except Exception as e:
        return ToolResult(success=False, output=None, error=str(e))


async def get_weather(city: str) -> ToolResult:
    """Get weather information for a city (simulated).

    Args:
        city: City name.

    Returns:
        Weather information.
    """
    # Simulated weather data
    conditions = ["ensolarado", "nublado", "chuvoso", "parcialmente nublado", "ventoso"]
    condition = random.choice(conditions)
    temperature = random.randint(15, 35)
    humidity = random.randint(40, 90)
    wind_speed = random.randint(5, 30)

    return ToolResult(
        success=True,
        output={
            "city": city,
            "condition": condition,
            "temperature_celsius": temperature,
            "humidity_percent": humidity,
            "wind_speed_kmh": wind_speed,
            "description": f"Em {city}, o clima esta {condition} com temperatura de {temperature} graus Celsius.",
        },
    )


async def web_search(query: str, num_results: int = 3) -> ToolResult:
    """Perform a web search (simulated).

    Args:
        query: Search query.
        num_results: Number of results to return.

    Returns:
        Search results.
    """
    # Simulated search results
    results = [
        {
            "title": f"Resultado {i+1} para: {query}",
            "snippet": f"Este e um resultado simulado para a busca '{query}'. "
            f"Contem informacoes relevantes sobre o topico.",
            "url": f"https://example.com/result{i+1}",
        }
        for i in range(num_results)
    ]

    return ToolResult(
        success=True,
        output={
            "query": query,
            "num_results": len(results),
            "results": results,
        },
    )


async def calculate(expression: str) -> ToolResult:
    """Evaluate a mathematical expression.

    Args:
        expression: Mathematical expression to evaluate.

    Returns:
        Calculation result.
    """
    try:
        # Sanitize and evaluate expression
        allowed_chars = set("0123456789+-*/().^ ")
        if not all(c in allowed_chars for c in expression):
            return ToolResult(
                success=False, output=None, error="Expressao contem caracteres nao permitidos"
            )

        # Replace ^ with ** for exponentiation
        expression = expression.replace("^", "**")

        result = eval(expression, {"__builtins__": {}}, {})

        return ToolResult(
            success=True,
            output={
                "expression": expression,
                "result": result,
                "formatted": f"O resultado de {expression} e {result}",
            },
        )
    except Exception as e:
        return ToolResult(success=False, output=None, error=f"Erro ao calcular: {str(e)}")


async def set_reminder(message: str, minutes: int = 5) -> ToolResult:
    """Set a reminder (simulated).

    Args:
        message: Reminder message.
        minutes: Minutes from now.

    Returns:
        Reminder confirmation.
    """
    reminder_time = datetime.now()
    # In a real implementation, this would schedule the reminder

    return ToolResult(
        success=True,
        output={
            "message": message,
            "minutes": minutes,
            "set_at": reminder_time.isoformat(),
            "confirmation": f"Lembrete configurado para daqui a {minutes} minutos: {message}",
        },
    )


async def translate(text: str, target_language: str = "en") -> ToolResult:
    """Translate text (simulated).

    Args:
        text: Text to translate.
        target_language: Target language code.

    Returns:
        Translation result.
    """
    # Simulated translation
    translations = {
        "en": {
            "ola": "hello",
            "bom dia": "good morning",
            "como vai": "how are you",
        },
        "es": {
            "ola": "hola",
            "bom dia": "buenos dias",
            "como vai": "como estas",
        },
    }

    text_lower = text.lower()
    lang_dict = translations.get(target_language, {})
    translated = lang_dict.get(text_lower, f"[traducao de '{text}' para {target_language}]")

    return ToolResult(
        success=True,
        output={
            "original": text,
            "translated": translated,
            "source_language": "pt",
            "target_language": target_language,
        },
    )


async def get_news(topic: str = "geral", count: int = 3) -> ToolResult:
    """Get news headlines (simulated).

    Args:
        topic: News topic.
        count: Number of headlines.

    Returns:
        News headlines.
    """
    headlines = [
        {
            "title": f"Manchete {i+1} sobre {topic}",
            "summary": f"Resumo da noticia {i+1} sobre {topic}. "
            f"Esta e uma noticia simulada para demonstracao.",
            "source": random.choice(["G1", "Folha", "UOL", "CNN Brasil"]),
            "published": datetime.now().isoformat(),
        }
        for i in range(count)
    ]

    return ToolResult(
        success=True,
        output={
            "topic": topic,
            "headlines": headlines,
            "count": len(headlines),
        },
    )


def get_demo_tools() -> list[VoiceTool]:
    """Get list of demo tools.

    Returns:
        List of VoiceTool instances.
    """
    return [
        FunctionTool.from_function(
            get_current_time,
            name="get_current_time",
            description="Obter a hora e data atual. Use quando o usuario perguntar que horas sao ou qual e a data.",
        ),
        FunctionTool.from_function(
            get_weather,
            name="get_weather",
            description="Obter informacoes do clima para uma cidade. Use quando o usuario perguntar sobre o tempo ou clima.",
        ),
        FunctionTool.from_function(
            web_search,
            name="web_search",
            description="Realizar uma busca na web. Use quando precisar de informacoes atualizadas ou especificas.",
        ),
        FunctionTool.from_function(
            calculate,
            name="calculate",
            description="Calcular uma expressao matematica. Use para calculos numericos.",
        ),
        FunctionTool.from_function(
            set_reminder,
            name="set_reminder",
            description="Configurar um lembrete. Use quando o usuario quiser ser lembrado de algo.",
        ),
        FunctionTool.from_function(
            translate,
            name="translate",
            description="Traduzir texto para outro idioma. Use para traducoes.",
        ),
        FunctionTool.from_function(
            get_news,
            name="get_news",
            description="Obter manchetes de noticias. Use para noticias e informacoes atuais.",
        ),
    ]

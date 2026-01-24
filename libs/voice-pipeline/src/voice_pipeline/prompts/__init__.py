"""Voice Prompt Templates.

Templates and utilities for creating voice-optimized prompts.

Quick Start:
    >>> from voice_pipeline.prompts import VoicePromptTemplate, VoiceStyle
    >>>
    >>> template = VoicePromptTemplate(
    ...     template="You are {name}, a {role}.",
    ...     voice_style=VoiceStyle.CONVERSATIONAL,
    ...     max_words=50,
    ... )
    >>>
    >>> prompt = template.format(name="Julia", role="assistant")

Using Personas:
    >>> from voice_pipeline.prompts import VoicePersona
    >>>
    >>> persona = VoicePersona(
    ...     name="Julia",
    ...     personality="friendly and helpful",
    ...     language="pt-BR",
    ...     voice_id="pt_BR-faber-medium",
    ... )
    >>>
    >>> system_prompt = persona.to_system_prompt()

Chat Prompts:
    >>> from voice_pipeline.prompts import VoiceChatPrompt
    >>>
    >>> chat = VoiceChatPrompt(
    ...     system="You are a helpful assistant.",
    ...     max_words=50,
    ... )
    >>>
    >>> messages = chat.format_messages("Hello!")
"""

from voice_pipeline.prompts.base import (
    SimplePrompt,
    VoicePromptTemplate,
    VoiceStyle,
    voice_prompt,
)
from voice_pipeline.prompts.chat import (
    Message,
    TurnPrompt,
    VoiceChatPrompt,
    create_chat_prompt,
)
from voice_pipeline.prompts.persona import (
    ASSISTANT_PERSONA,
    CONCIERGE_PERSONA,
    CUSTOMER_SERVICE_PERSONA,
    TUTOR_PERSONA,
    VoicePersona,
)

__all__ = [
    # Base
    "VoicePromptTemplate",
    "VoiceStyle",
    "SimplePrompt",
    "voice_prompt",
    # Chat
    "VoiceChatPrompt",
    "Message",
    "TurnPrompt",
    "create_chat_prompt",
    # Persona
    "VoicePersona",
    "ASSISTANT_PERSONA",
    "CUSTOMER_SERVICE_PERSONA",
    "TUTOR_PERSONA",
    "CONCIERGE_PERSONA",
]

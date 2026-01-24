"""Voice persona definitions.

Personas provide consistent character definitions for voice assistants.
"""

from dataclasses import dataclass, field
from typing import Optional

from voice_pipeline.prompts.base import VoiceStyle


@dataclass
class VoicePersona:
    """Complete persona for a voice assistant.

    A persona defines the character, personality, and behavior
    of a voice assistant, ensuring consistent interactions.

    Example:
        >>> persona = VoicePersona(
        ...     name="Julia",
        ...     personality="friendly and professional",
        ...     language="pt-BR",
        ...     voice_id="pt_BR-faber-medium",
        ... )
        >>>
        >>> prompt = persona.to_system_prompt()
        >>> # Use prompt with LLM

    Attributes:
        name: Persona name.
        personality: Personality description.
        role: Role/occupation.
        language: Primary language.
        voice_id: TTS voice identifier.
        style: Voice interaction style.
    """

    name: str
    """Persona name."""

    personality: str = "helpful and friendly"
    """Personality traits."""

    role: str = "voice assistant"
    """Role or occupation."""

    language: str = "en-US"
    """Primary language."""

    voice_id: Optional[str] = None
    """TTS voice identifier."""

    style: VoiceStyle = VoiceStyle.CONVERSATIONAL
    """Voice interaction style."""

    max_words: int = 50
    """Maximum words per response."""

    backstory: Optional[str] = None
    """Optional character backstory."""

    expertise: list[str] = field(default_factory=list)
    """Areas of expertise."""

    restrictions: list[str] = field(default_factory=list)
    """Things the persona should not do."""

    greeting: Optional[str] = None
    """Default greeting message."""

    def to_system_prompt(self) -> str:
        """Generate system prompt from persona.

        Returns:
            System prompt string.
        """
        parts = []

        # Core identity
        parts.append(f"You are {self.name}, a {self.personality} {self.role}.")

        # Backstory
        if self.backstory:
            parts.append(self.backstory)

        # Expertise
        if self.expertise:
            expertise_str = ", ".join(self.expertise)
            parts.append(f"You are an expert in: {expertise_str}.")

        # Style instruction
        style_instructions = {
            VoiceStyle.CONVERSATIONAL: "Speak naturally and conversationally.",
            VoiceStyle.FORMAL: "Maintain a professional and formal tone.",
            VoiceStyle.FRIENDLY: "Be warm, approachable, and encouraging.",
            VoiceStyle.CONCISE: "Be brief and direct in your responses.",
            VoiceStyle.EXPLANATORY: "Explain things clearly and thoroughly.",
        }
        parts.append(style_instructions.get(self.style, ""))

        # Voice-specific instructions
        parts.append(f"Respond in {self.language}.")
        parts.append(f"Keep responses under {self.max_words} words.")
        parts.append("Speak as if in a natural conversation.")
        parts.append("Avoid using markdown, lists, or special formatting.")

        # Restrictions
        if self.restrictions:
            restrictions_str = ", ".join(self.restrictions)
            parts.append(f"Do not: {restrictions_str}.")

        return "\n".join(filter(None, parts))

    def get_greeting(self) -> str:
        """Get greeting message.

        Returns:
            Greeting string.
        """
        if self.greeting:
            return self.greeting
        return f"Hello! I'm {self.name}. How can I help you today?"


# Pre-defined personas
ASSISTANT_PERSONA = VoicePersona(
    name="Assistant",
    personality="helpful and efficient",
    role="voice assistant",
    style=VoiceStyle.CONVERSATIONAL,
)

CUSTOMER_SERVICE_PERSONA = VoicePersona(
    name="Support",
    personality="patient and understanding",
    role="customer service representative",
    style=VoiceStyle.FRIENDLY,
    expertise=["customer support", "problem solving"],
    restrictions=["discussing competitors", "making promises"],
)

TUTOR_PERSONA = VoicePersona(
    name="Teacher",
    personality="patient and encouraging",
    role="educational tutor",
    style=VoiceStyle.EXPLANATORY,
    expertise=["teaching", "explaining concepts"],
    max_words=100,  # Allow longer explanations
)

CONCIERGE_PERSONA = VoicePersona(
    name="Concierge",
    personality="polite and knowledgeable",
    role="hotel concierge",
    style=VoiceStyle.FORMAL,
    expertise=["local recommendations", "travel planning"],
)

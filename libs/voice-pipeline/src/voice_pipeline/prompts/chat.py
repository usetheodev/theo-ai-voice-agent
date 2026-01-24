"""Chat prompt utilities for voice interactions.

Provides utilities for formatting chat messages in voice-optimized ways.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from voice_pipeline.prompts.base import VoicePromptTemplate, VoiceStyle


@dataclass
class Message:
    """A chat message."""

    role: str
    """Message role (system, user, assistant)."""

    content: str
    """Message content."""

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary.

        Returns:
            Dictionary with role and content.
        """
        return {"role": self.role, "content": self.content}


@dataclass
class VoiceChatPrompt:
    """Chat prompt builder for voice interactions.

    Helps construct chat message sequences with proper
    system prompts and formatting for voice.

    Example:
        >>> chat = VoiceChatPrompt(
        ...     system="You are a helpful assistant.",
        ...     max_words=50,
        ... )
        >>>
        >>> messages = chat.format_messages(
        ...     user_input="What time is it?",
        ...     history=[
        ...         {"role": "user", "content": "Hello"},
        ...         {"role": "assistant", "content": "Hi!"},
        ...     ],
        ... )

    Attributes:
        system: System prompt content.
        max_words: Maximum words per response.
        style: Voice style.
    """

    system: str
    """System prompt content."""

    max_words: int = 50
    """Maximum words per response."""

    style: VoiceStyle = VoiceStyle.CONVERSATIONAL
    """Voice interaction style."""

    language: Optional[str] = None
    """Language code."""

    include_voice_instructions: bool = True
    """Whether to add voice-specific instructions."""

    _messages: list[dict[str, str]] = field(default_factory=list)
    """Accumulated messages."""

    def __post_init__(self):
        """Initialize messages list."""
        self._messages = []

    def get_system_message(self) -> str:
        """Get the complete system message.

        Returns:
            System message with voice instructions.
        """
        parts = [self.system]

        if self.include_voice_instructions:
            parts.append("")  # Blank line

            # Style instruction
            style_map = {
                VoiceStyle.CONVERSATIONAL: "Respond naturally and conversationally.",
                VoiceStyle.FORMAL: "Maintain a professional tone.",
                VoiceStyle.FRIENDLY: "Be warm and friendly.",
                VoiceStyle.CONCISE: "Be brief and direct.",
                VoiceStyle.EXPLANATORY: "Explain clearly.",
            }
            parts.append(style_map.get(self.style, ""))

            # Word limit
            parts.append(f"Keep responses under {self.max_words} words.")

            # Language
            if self.language:
                parts.append(f"Respond in {self.language}.")

            # Voice-specific
            parts.append("Respond as if speaking aloud.")
            parts.append("Avoid markdown or special formatting.")

        return "\n".join(parts)

    def format_messages(
        self,
        user_input: str,
        history: Optional[Sequence[dict[str, str]]] = None,
    ) -> list[dict[str, str]]:
        """Format messages for LLM.

        Args:
            user_input: Current user input.
            history: Previous conversation messages.

        Returns:
            List of message dictionaries.
        """
        messages = []

        # System message
        messages.append({
            "role": "system",
            "content": self.get_system_message(),
        })

        # History
        if history:
            for msg in history:
                messages.append(msg)

        # Current user input
        messages.append({
            "role": "user",
            "content": user_input,
        })

        return messages

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the prompt.

        Args:
            role: Message role.
            content: Message content.
        """
        self._messages.append({"role": role, "content": content})

    def get_messages(self) -> list[dict[str, str]]:
        """Get all messages.

        Returns:
            List of message dictionaries.
        """
        return [
            {"role": "system", "content": self.get_system_message()},
            *self._messages,
        ]

    def clear(self) -> None:
        """Clear accumulated messages."""
        self._messages.clear()


@dataclass
class TurnPrompt:
    """Prompt for a single conversation turn.

    Useful for formatting individual turns with context.

    Example:
        >>> turn = TurnPrompt(
        ...     transcription="What's the weather like?",
        ...     context="Previous discussion about travel plans.",
        ... )
        >>> prompt = turn.format()
    """

    transcription: str
    """User's transcribed speech."""

    context: Optional[str] = None
    """Additional context."""

    previous_response: Optional[str] = None
    """Previous assistant response."""

    def format(self) -> str:
        """Format the turn as a prompt.

        Returns:
            Formatted prompt string.
        """
        parts = []

        if self.context:
            parts.append(f"Context: {self.context}")

        if self.previous_response:
            parts.append(f"Your previous response: {self.previous_response}")

        parts.append(f"User said: {self.transcription}")

        return "\n".join(parts)


def create_chat_prompt(
    system: str,
    style: VoiceStyle = VoiceStyle.CONVERSATIONAL,
    max_words: int = 50,
    language: Optional[str] = None,
) -> VoiceChatPrompt:
    """Create a voice chat prompt.

    Args:
        system: System prompt.
        style: Voice style.
        max_words: Maximum words per response.
        language: Language code.

    Returns:
        VoiceChatPrompt instance.
    """
    return VoiceChatPrompt(
        system=system,
        style=style,
        max_words=max_words,
        language=language,
    )

"""Base classes for voice prompt templates.

Prompt templates help create consistent, voice-optimized prompts
for LLM interactions.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class VoiceStyle(Enum):
    """Voice interaction styles."""

    CONVERSATIONAL = "conversational"
    """Natural, casual conversation."""

    FORMAL = "formal"
    """Professional, formal tone."""

    FRIENDLY = "friendly"
    """Warm, approachable tone."""

    CONCISE = "concise"
    """Brief, to-the-point responses."""

    EXPLANATORY = "explanatory"
    """Detailed, educational responses."""


@dataclass
class VoicePromptTemplate:
    """Template for voice-optimized prompts.

    Voice prompts differ from text prompts:
    - Should be concise (shorter responses)
    - Natural speech patterns
    - Avoid complex formatting
    - Consider spoken delivery

    Example:
        >>> template = VoicePromptTemplate(
        ...     template="You are {name}, a {role}. {instructions}",
        ...     voice_style=VoiceStyle.CONVERSATIONAL,
        ...     max_words=50,
        ... )
        >>>
        >>> prompt = template.format(
        ...     name="Julia",
        ...     role="helpful assistant",
        ...     instructions="Be friendly and concise.",
        ... )

    Attributes:
        template: The template string with {placeholders}.
        voice_style: Preferred voice style.
        max_words: Maximum words per response (guidance).
        language: Language code (e.g., "pt-BR").
    """

    template: str
    """Template string with placeholders."""

    voice_style: VoiceStyle = VoiceStyle.CONVERSATIONAL
    """Voice interaction style."""

    max_words: int = 50
    """Maximum words per response (soft limit)."""

    language: Optional[str] = None
    """Language code for the interaction."""

    voice_instructions: Optional[str] = None
    """Additional instructions for voice delivery."""

    input_variables: list[str] = field(default_factory=list)
    """List of input variable names."""

    def __post_init__(self):
        """Extract input variables from template."""
        if not self.input_variables:
            # Extract {variable} patterns
            self.input_variables = re.findall(r"\{(\w+)\}", self.template)

    def format(self, **kwargs) -> str:
        """Format the template with given values.

        Args:
            **kwargs: Variable values.

        Returns:
            Formatted prompt string.
        """
        result = self.template.format(**kwargs)

        # Add style instruction if not present
        if self.voice_style and "style" not in self.template.lower():
            style_instruction = self._get_style_instruction()
            if style_instruction:
                result = f"{result}\n\n{style_instruction}"

        # Add max words instruction
        if self.max_words:
            result = f"{result}\n\nKeep responses under {self.max_words} words."

        return result

    def _get_style_instruction(self) -> str:
        """Get instruction text for voice style."""
        instructions = {
            VoiceStyle.CONVERSATIONAL: "Respond in a natural, conversational tone.",
            VoiceStyle.FORMAL: "Maintain a professional and formal tone.",
            VoiceStyle.FRIENDLY: "Be warm and approachable in your responses.",
            VoiceStyle.CONCISE: "Be brief and to the point.",
            VoiceStyle.EXPLANATORY: "Provide clear, detailed explanations.",
        }
        return instructions.get(self.voice_style, "")

    def to_system_prompt(self, **kwargs) -> str:
        """Convert to system prompt format.

        Args:
            **kwargs: Variable values.

        Returns:
            System prompt string.
        """
        base = self.format(**kwargs)

        # Add voice-specific instructions
        voice_parts = []

        if self.language:
            voice_parts.append(f"Respond in {self.language}.")

        if self.voice_instructions:
            voice_parts.append(self.voice_instructions)

        voice_parts.append("Avoid using markdown or special formatting.")
        voice_parts.append("Respond naturally as if speaking aloud.")

        return f"{base}\n\n" + "\n".join(voice_parts)


@dataclass
class SimplePrompt:
    """Simple string prompt wrapper.

    For cases where a full template is not needed.

    Example:
        >>> prompt = SimplePrompt("You are a helpful assistant.")
        >>> prompt.to_string()
        "You are a helpful assistant."
    """

    content: str
    """Prompt content."""

    max_words: Optional[int] = None
    """Maximum words per response."""

    def to_string(self) -> str:
        """Get prompt string.

        Returns:
            Prompt string.
        """
        if self.max_words:
            return f"{self.content}\n\nKeep responses under {self.max_words} words."
        return self.content

    def format(self, **kwargs) -> str:
        """Format the prompt (for compatibility).

        Args:
            **kwargs: Not used.

        Returns:
            Prompt string.
        """
        return self.to_string()


# Convenience function
def voice_prompt(
    template: str,
    style: VoiceStyle = VoiceStyle.CONVERSATIONAL,
    max_words: int = 50,
    language: Optional[str] = None,
) -> VoicePromptTemplate:
    """Create a voice prompt template.

    Args:
        template: Template string.
        style: Voice style.
        max_words: Maximum response words.
        language: Language code.

    Returns:
        VoicePromptTemplate instance.
    """
    return VoicePromptTemplate(
        template=template,
        voice_style=style,
        max_words=max_words,
        language=language,
    )

"""Tests for Voice Prompts."""

import pytest

from voice_pipeline.prompts import (
    ASSISTANT_PERSONA,
    CONCIERGE_PERSONA,
    CUSTOMER_SERVICE_PERSONA,
    Message,
    SimplePrompt,
    TUTOR_PERSONA,
    TurnPrompt,
    VoiceChatPrompt,
    VoicePersona,
    VoicePromptTemplate,
    VoiceStyle,
    create_chat_prompt,
    voice_prompt,
)


class TestVoiceStyle:
    """Tests for VoiceStyle enum."""

    def test_all_styles_exist(self):
        """Test that all styles are defined."""
        styles = [
            VoiceStyle.CONVERSATIONAL,
            VoiceStyle.FORMAL,
            VoiceStyle.FRIENDLY,
            VoiceStyle.CONCISE,
            VoiceStyle.EXPLANATORY,
        ]
        assert len(styles) == 5


class TestVoicePromptTemplate:
    """Tests for VoicePromptTemplate."""

    def test_basic_template(self):
        """Test basic template formatting."""
        template = VoicePromptTemplate(
            template="You are {name}, a {role}.",
            max_words=50,
        )

        result = template.format(name="Julia", role="assistant")
        assert "Julia" in result
        assert "assistant" in result

    def test_extracts_variables(self):
        """Test variable extraction from template."""
        template = VoicePromptTemplate(
            template="Hello {name}, welcome to {place}.",
        )
        assert "name" in template.input_variables
        assert "place" in template.input_variables

    def test_adds_style_instruction(self):
        """Test that style instruction is added."""
        template = VoicePromptTemplate(
            template="You are an assistant.",
            voice_style=VoiceStyle.FORMAL,
        )

        result = template.format()
        assert "professional" in result.lower() or "formal" in result.lower()

    def test_adds_max_words(self):
        """Test that max words instruction is added."""
        template = VoicePromptTemplate(
            template="You are an assistant.",
            max_words=30,
        )

        result = template.format()
        assert "30" in result
        assert "words" in result.lower()

    def test_to_system_prompt(self):
        """Test system prompt generation."""
        template = VoicePromptTemplate(
            template="You are {name}.",
            language="pt-BR",
            voice_instructions="Speak slowly and clearly.",
        )

        result = template.to_system_prompt(name="Julia")
        assert "Julia" in result
        assert "pt-BR" in result
        assert "markdown" in result.lower()

    def test_voice_prompt_helper(self):
        """Test voice_prompt helper function."""
        template = voice_prompt(
            template="Hello {name}!",
            style=VoiceStyle.FRIENDLY,
            max_words=40,
            language="en-US",
        )

        assert isinstance(template, VoicePromptTemplate)
        assert template.voice_style == VoiceStyle.FRIENDLY
        assert template.max_words == 40
        assert template.language == "en-US"


class TestSimplePrompt:
    """Tests for SimplePrompt."""

    def test_basic_prompt(self):
        """Test basic prompt."""
        prompt = SimplePrompt(content="You are helpful.")
        assert prompt.to_string() == "You are helpful."

    def test_with_max_words(self):
        """Test prompt with max words."""
        prompt = SimplePrompt(content="Be helpful.", max_words=25)
        result = prompt.to_string()
        assert "25" in result
        assert "words" in result.lower()

    def test_format_compatibility(self):
        """Test format method for compatibility."""
        prompt = SimplePrompt(content="Hello!")
        assert prompt.format() == "Hello!"


class TestVoicePersona:
    """Tests for VoicePersona."""

    def test_basic_persona(self):
        """Test basic persona creation."""
        persona = VoicePersona(
            name="Julia",
            personality="friendly",
            role="assistant",
        )

        assert persona.name == "Julia"
        assert persona.personality == "friendly"

    def test_to_system_prompt(self):
        """Test system prompt generation."""
        persona = VoicePersona(
            name="Julia",
            personality="helpful and friendly",
            role="voice assistant",
            language="pt-BR",
            style=VoiceStyle.CONVERSATIONAL,
        )

        prompt = persona.to_system_prompt()
        assert "Julia" in prompt
        assert "helpful and friendly" in prompt
        assert "pt-BR" in prompt
        assert "markdown" in prompt.lower()

    def test_with_expertise(self):
        """Test persona with expertise."""
        persona = VoicePersona(
            name="Expert",
            expertise=["Python", "Machine Learning"],
        )

        prompt = persona.to_system_prompt()
        assert "Python" in prompt
        assert "Machine Learning" in prompt

    def test_with_restrictions(self):
        """Test persona with restrictions."""
        persona = VoicePersona(
            name="Support",
            restrictions=["making promises", "sharing secrets"],
        )

        prompt = persona.to_system_prompt()
        assert "making promises" in prompt
        assert "sharing secrets" in prompt

    def test_get_greeting(self):
        """Test greeting generation."""
        persona = VoicePersona(name="Julia")
        greeting = persona.get_greeting()
        assert "Julia" in greeting

        # Test custom greeting
        persona2 = VoicePersona(
            name="Bot",
            greeting="Welcome! How may I assist you?",
        )
        assert persona2.get_greeting() == "Welcome! How may I assist you?"

    def test_predefined_personas(self):
        """Test predefined personas exist."""
        assert ASSISTANT_PERSONA.name == "Assistant"
        assert CUSTOMER_SERVICE_PERSONA.role == "customer service representative"
        assert TUTOR_PERSONA.max_words == 100
        assert CONCIERGE_PERSONA.style == VoiceStyle.FORMAL


class TestVoiceChatPrompt:
    """Tests for VoiceChatPrompt."""

    def test_basic_chat(self):
        """Test basic chat prompt."""
        chat = VoiceChatPrompt(
            system="You are helpful.",
            max_words=50,
        )

        messages = chat.format_messages("Hello!")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hello!"

    def test_with_history(self):
        """Test chat with history."""
        chat = VoiceChatPrompt(system="Be helpful.")

        history = [
            {"role": "user", "content": "Hi!"},
            {"role": "assistant", "content": "Hello!"},
        ]

        messages = chat.format_messages("How are you?", history=history)
        assert len(messages) == 4
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_system_includes_voice_instructions(self):
        """Test that system includes voice instructions."""
        chat = VoiceChatPrompt(
            system="You are an assistant.",
            style=VoiceStyle.FORMAL,
            max_words=40,
            language="en-US",
        )

        system_msg = chat.get_system_message()
        assert "professional" in system_msg.lower() or "formal" in system_msg.lower()
        assert "40" in system_msg
        assert "en-US" in system_msg

    def test_add_message(self):
        """Test adding messages."""
        chat = VoiceChatPrompt(system="Test")
        chat.add_message("user", "Hello")
        chat.add_message("assistant", "Hi!")

        messages = chat.get_messages()
        assert len(messages) == 3  # system + 2 added
        assert messages[1]["role"] == "user"

    def test_clear(self):
        """Test clearing messages."""
        chat = VoiceChatPrompt(system="Test")
        chat.add_message("user", "Hello")
        chat.clear()

        messages = chat.get_messages()
        assert len(messages) == 1  # Only system

    def test_create_chat_prompt_helper(self):
        """Test create_chat_prompt helper."""
        chat = create_chat_prompt(
            system="Be helpful.",
            style=VoiceStyle.FRIENDLY,
            max_words=30,
            language="pt-BR",
        )

        assert isinstance(chat, VoiceChatPrompt)
        assert chat.style == VoiceStyle.FRIENDLY
        assert chat.max_words == 30


class TestMessage:
    """Tests for Message."""

    def test_to_dict(self):
        """Test conversion to dict."""
        msg = Message(role="user", content="Hello!")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello!"


class TestTurnPrompt:
    """Tests for TurnPrompt."""

    def test_basic_turn(self):
        """Test basic turn formatting."""
        turn = TurnPrompt(transcription="What's the weather?")
        result = turn.format()
        assert "What's the weather?" in result

    def test_with_context(self):
        """Test turn with context."""
        turn = TurnPrompt(
            transcription="And tomorrow?",
            context="Discussing weather in New York.",
        )
        result = turn.format()
        assert "New York" in result
        assert "tomorrow" in result

    def test_with_previous_response(self):
        """Test turn with previous response."""
        turn = TurnPrompt(
            transcription="Thanks!",
            previous_response="It's sunny today.",
        )
        result = turn.format()
        assert "sunny" in result

"""
Prompt Templates for Phone Conversation AI

Handles system prompt formatting and response optimization for voice conversations
"""

import re
from typing import List, Dict


class PromptTemplate:
    """System prompt templates optimized for phone conversations"""

    @staticmethod
    def format_for_qwen(
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_text: str
    ) -> List[Dict[str, str]]:
        """
        Format conversation for Qwen chat template.

        Args:
            system_prompt: System instructions
            conversation_history: [{role: "user"/"assistant", content: "..."}]
            user_text: Current user utterance

        Returns:
            List of message dicts ready for tokenizer.apply_chat_template()
        """
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_text})
        return messages

    @staticmethod
    def truncate_response(text: str, max_sentences: int = 3) -> str:
        """
        Ensure response is concise for phone conversation.

        Args:
            text: Generated response text
            max_sentences: Maximum number of sentences to keep

        Returns:
            Truncated text (1-3 sentences)
        """
        # Split by sentence endings (., !, ?)
        sentences = re.split(r'[.!?]+', text.strip())

        # Filter out empty strings
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return text.strip()

        # Take first N sentences
        truncated = '. '.join(sentences[:max_sentences])

        # Add final period if not present
        if not truncated.endswith(('.', '!', '?')):
            truncated += '.'

        return truncated

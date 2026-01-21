"""
Conversation State Manager

Manages conversation history and context for each call session
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime
from ..common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Message:
    """Message in conversation"""
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    timestamp: datetime


class ConversationManager:
    """
    Manages conversation state for multiple sessions

    Usage:
        manager = ConversationManager(max_history_turns=10)

        # Add messages
        manager.add_user_message(session_id, "Olá")
        manager.add_assistant_message(session_id, "Olá! Como posso ajudar?")

        # Get history
        history = manager.get_history(session_id)
        # [{'role': 'user', 'content': 'Olá'}, {'role': 'assistant', 'content': 'Olá! Como posso ajudar?'}]

        # Clear session when call ends
        manager.clear_session(session_id)
    """

    def __init__(self, max_history_turns: int = 10):
        """
        Initialize conversation manager

        Args:
            max_history_turns: Maximum number of message pairs (user + assistant) to keep
        """
        self.max_history_turns = max_history_turns
        self.sessions: Dict[str, List[Message]] = {}

        logger.info("ConversationManager initialized", max_history_turns=max_history_turns)

    def add_user_message(self, session_id: str, text: str):
        """
        Add user message to conversation history

        Args:
            session_id: Unique session identifier
            text: User's message text
        """
        if session_id not in self.sessions:
            self.sessions[session_id] = []

        self.sessions[session_id].append(Message(
            role='user',
            content=text,
            timestamp=datetime.now()
        ))

        self._trim_history(session_id)

        logger.debug("User message added",
                    session_id=session_id,
                    text=text[:50],  # Log first 50 chars
                    history_length=len(self.sessions[session_id]))

    def add_assistant_message(self, session_id: str, text: str):
        """
        Add assistant response to conversation history

        Args:
            session_id: Unique session identifier
            text: Assistant's response text
        """
        if session_id not in self.sessions:
            self.sessions[session_id] = []

        self.sessions[session_id].append(Message(
            role='assistant',
            content=text,
            timestamp=datetime.now()
        ))

        self._trim_history(session_id)

        logger.debug("Assistant message added",
                    session_id=session_id,
                    text=text[:50],  # Log first 50 chars
                    history_length=len(self.sessions[session_id]))

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """
        Get conversation history for LLM context

        Args:
            session_id: Unique session identifier

        Returns:
            List of messages in format:
            [
                {'role': 'user', 'content': 'Olá'},
                {'role': 'assistant', 'content': 'Olá! Como posso ajudar?'}
            ]
        """
        if session_id not in self.sessions:
            return []

        return [
            {'role': msg.role, 'content': msg.content}
            for msg in self.sessions[session_id]
        ]

    def get_last_user_message(self, session_id: str) -> Optional[str]:
        """
        Get the last user message in this session

        Args:
            session_id: Unique session identifier

        Returns:
            Last user message text or None
        """
        if session_id not in self.sessions:
            return None

        # Find last user message
        for msg in reversed(self.sessions[session_id]):
            if msg.role == 'user':
                return msg.content

        return None

    def get_last_assistant_message(self, session_id: str) -> Optional[str]:
        """
        Get the last assistant message in this session

        Args:
            session_id: Unique session identifier

        Returns:
            Last assistant message text or None
        """
        if session_id not in self.sessions:
            return None

        # Find last assistant message
        for msg in reversed(self.sessions[session_id]):
            if msg.role == 'assistant':
                return msg.content

        return None

    def _trim_history(self, session_id: str):
        """
        Trim history to keep only last N turns (user + assistant pairs)

        Args:
            session_id: Unique session identifier
        """
        if session_id not in self.sessions:
            return

        # Each turn = 2 messages (user + assistant)
        max_messages = self.max_history_turns * 2

        if len(self.sessions[session_id]) > max_messages:
            # Keep only last N messages
            self.sessions[session_id] = self.sessions[session_id][-max_messages:]

            logger.debug("History trimmed",
                        session_id=session_id,
                        kept_messages=len(self.sessions[session_id]))

    def clear_session(self, session_id: str):
        """
        Clear conversation history for a session (e.g., when call ends)

        Args:
            session_id: Unique session identifier
        """
        if session_id in self.sessions:
            message_count = len(self.sessions[session_id])
            del self.sessions[session_id]

            logger.info("Session history cleared",
                       session_id=session_id,
                       messages_cleared=message_count)

    def get_session_count(self) -> int:
        """
        Get number of active sessions

        Returns:
            Number of sessions with conversation history
        """
        return len(self.sessions)

    def get_stats(self) -> dict:
        """
        Get conversation manager statistics

        Returns:
            Dictionary with stats
        """
        return {
            'active_sessions': len(self.sessions),
            'max_history_turns': self.max_history_turns,
            'sessions': {
                session_id: len(history)
                for session_id, history in self.sessions.items()
            }
        }

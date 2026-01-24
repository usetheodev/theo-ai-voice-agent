"""Conversation state machine.

Manages the state of a voice conversation.
"""

from enum import Enum
from typing import Callable, Optional
import logging

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    """States of a voice conversation.

    State flow:
        IDLE → LISTENING → PROCESSING → SPEAKING → IDLE
                   ↑                         │
                   └─────────────────────────┘
                        (barge-in)
    """

    IDLE = "idle"
    """Waiting for user to speak."""

    LISTENING = "listening"
    """User is speaking, collecting audio."""

    PROCESSING = "processing"
    """Processing user input (ASR → LLM)."""

    SPEAKING = "speaking"
    """Assistant is speaking (TTS output)."""

    INTERRUPTED = "interrupted"
    """User interrupted (barge-in), canceling current response."""


# Valid state transitions
VALID_TRANSITIONS = {
    ConversationState.IDLE: {
        ConversationState.LISTENING,
    },
    ConversationState.LISTENING: {
        ConversationState.PROCESSING,
        ConversationState.IDLE,  # Timeout or cancel
    },
    ConversationState.PROCESSING: {
        ConversationState.SPEAKING,
        ConversationState.IDLE,  # Error or empty response
    },
    ConversationState.SPEAKING: {
        ConversationState.IDLE,
        ConversationState.INTERRUPTED,
    },
    ConversationState.INTERRUPTED: {
        ConversationState.LISTENING,
        ConversationState.IDLE,
    },
}


class ConversationStateMachine:
    """State machine for managing conversation flow.

    Example:
        sm = ConversationStateMachine()

        sm.on_state_change(lambda old, new: print(f"{old} → {new}"))

        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.IDLE)
    """

    def __init__(self, initial_state: ConversationState = ConversationState.IDLE):
        """Initialize state machine.

        Args:
            initial_state: Starting state.
        """
        self._state = initial_state
        self._handlers: list[Callable[[ConversationState, ConversationState], None]] = []
        self._state_entry_handlers: dict[ConversationState, list[Callable]] = {}
        self._state_exit_handlers: dict[ConversationState, list[Callable]] = {}

    @property
    def state(self) -> ConversationState:
        """Current conversation state."""
        return self._state

    @property
    def is_idle(self) -> bool:
        """Whether in idle state."""
        return self._state == ConversationState.IDLE

    @property
    def is_listening(self) -> bool:
        """Whether listening to user."""
        return self._state == ConversationState.LISTENING

    @property
    def is_processing(self) -> bool:
        """Whether processing user input."""
        return self._state == ConversationState.PROCESSING

    @property
    def is_speaking(self) -> bool:
        """Whether assistant is speaking."""
        return self._state == ConversationState.SPEAKING

    @property
    def is_active(self) -> bool:
        """Whether conversation is active (not idle)."""
        return self._state != ConversationState.IDLE

    def can_transition_to(self, new_state: ConversationState) -> bool:
        """Check if transition to new state is valid.

        Args:
            new_state: Target state.

        Returns:
            True if transition is allowed.
        """
        return new_state in VALID_TRANSITIONS.get(self._state, set())

    def transition_to(self, new_state: ConversationState) -> bool:
        """Transition to a new state.

        Args:
            new_state: Target state.

        Returns:
            True if transition succeeded.

        Raises:
            ValueError: If transition is invalid.
        """
        if new_state == self._state:
            return True

        if not self.can_transition_to(new_state):
            logger.warning(
                f"Invalid state transition: {self._state.value} → {new_state.value}"
            )
            return False

        old_state = self._state
        self._state = new_state

        logger.debug(f"State: {old_state.value} → {new_state.value}")

        # Call exit handlers for old state
        for handler in self._state_exit_handlers.get(old_state, []):
            try:
                handler(old_state)
            except Exception as e:
                logger.error(f"State exit handler error: {e}")

        # Call entry handlers for new state
        for handler in self._state_entry_handlers.get(new_state, []):
            try:
                handler(new_state)
            except Exception as e:
                logger.error(f"State entry handler error: {e}")

        # Call general transition handlers
        for handler in self._handlers:
            try:
                handler(old_state, new_state)
            except Exception as e:
                logger.error(f"State change handler error: {e}")

        return True

    def force_transition(self, new_state: ConversationState) -> None:
        """Force transition to state (bypass validation).

        Use only for error recovery.

        Args:
            new_state: Target state.
        """
        old_state = self._state
        self._state = new_state
        logger.warning(f"Forced state: {old_state.value} → {new_state.value}")

    def on_state_change(
        self,
        handler: Callable[[ConversationState, ConversationState], None],
    ) -> None:
        """Register handler for any state change.

        Args:
            handler: Callback(old_state, new_state).
        """
        self._handlers.append(handler)

    def on_enter(
        self,
        state: ConversationState,
        handler: Callable[[ConversationState], None],
    ) -> None:
        """Register handler for entering a specific state.

        Args:
            state: State to monitor.
            handler: Callback(state).
        """
        if state not in self._state_entry_handlers:
            self._state_entry_handlers[state] = []
        self._state_entry_handlers[state].append(handler)

    def on_exit(
        self,
        state: ConversationState,
        handler: Callable[[ConversationState], None],
    ) -> None:
        """Register handler for exiting a specific state.

        Args:
            state: State to monitor.
            handler: Callback(state).
        """
        if state not in self._state_exit_handlers:
            self._state_exit_handlers[state] = []
        self._state_exit_handlers[state].append(handler)

    def reset(self) -> None:
        """Reset state machine to idle."""
        self._state = ConversationState.IDLE

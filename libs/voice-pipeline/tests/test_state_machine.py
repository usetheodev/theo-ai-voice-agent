"""Tests for ConversationStateMachine."""

import pytest
from voice_pipeline.core.state_machine import (
    ConversationState,
    ConversationStateMachine,
    VALID_TRANSITIONS,
)


class TestConversationState:
    """Tests for ConversationState enum."""

    def test_all_states_defined(self):
        """Test all expected states exist."""
        assert ConversationState.IDLE
        assert ConversationState.LISTENING
        assert ConversationState.PROCESSING
        assert ConversationState.SPEAKING
        assert ConversationState.INTERRUPTED


class TestConversationStateMachine:
    """Tests for ConversationStateMachine."""

    def test_initial_state(self):
        """Test default initial state is IDLE."""
        sm = ConversationStateMachine()
        assert sm.state == ConversationState.IDLE
        assert sm.is_idle

    def test_custom_initial_state(self):
        """Test custom initial state."""
        sm = ConversationStateMachine(initial_state=ConversationState.LISTENING)
        assert sm.state == ConversationState.LISTENING

    def test_state_properties(self):
        """Test state check properties."""
        sm = ConversationStateMachine()

        sm._state = ConversationState.IDLE
        assert sm.is_idle
        assert not sm.is_active

        sm._state = ConversationState.LISTENING
        assert sm.is_listening
        assert sm.is_active

        sm._state = ConversationState.PROCESSING
        assert sm.is_processing
        assert sm.is_active

        sm._state = ConversationState.SPEAKING
        assert sm.is_speaking
        assert sm.is_active

    def test_valid_transition(self):
        """Test valid state transitions."""
        sm = ConversationStateMachine()

        # IDLE → LISTENING
        assert sm.can_transition_to(ConversationState.LISTENING)
        result = sm.transition_to(ConversationState.LISTENING)
        assert result
        assert sm.state == ConversationState.LISTENING

        # LISTENING → PROCESSING
        assert sm.can_transition_to(ConversationState.PROCESSING)
        result = sm.transition_to(ConversationState.PROCESSING)
        assert result
        assert sm.state == ConversationState.PROCESSING

        # PROCESSING → SPEAKING
        result = sm.transition_to(ConversationState.SPEAKING)
        assert result
        assert sm.state == ConversationState.SPEAKING

        # SPEAKING → IDLE
        result = sm.transition_to(ConversationState.IDLE)
        assert result
        assert sm.state == ConversationState.IDLE

    def test_invalid_transition(self):
        """Test invalid state transitions."""
        sm = ConversationStateMachine()

        # IDLE → PROCESSING (invalid)
        assert not sm.can_transition_to(ConversationState.PROCESSING)
        result = sm.transition_to(ConversationState.PROCESSING)
        assert not result
        assert sm.state == ConversationState.IDLE

    def test_same_state_transition(self):
        """Test transitioning to same state."""
        sm = ConversationStateMachine()
        result = sm.transition_to(ConversationState.IDLE)
        assert result  # Should succeed (no-op)

    def test_force_transition(self):
        """Test forced transition bypasses validation."""
        sm = ConversationStateMachine()

        # Force invalid transition
        sm.force_transition(ConversationState.SPEAKING)
        assert sm.state == ConversationState.SPEAKING

    def test_reset(self):
        """Test resetting to IDLE."""
        sm = ConversationStateMachine()
        sm._state = ConversationState.SPEAKING
        sm.reset()
        assert sm.state == ConversationState.IDLE

    def test_state_change_handler(self):
        """Test state change callback."""
        sm = ConversationStateMachine()
        transitions = []

        def handler(old, new):
            transitions.append((old, new))

        sm.on_state_change(handler)

        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)

        assert len(transitions) == 2
        assert transitions[0] == (ConversationState.IDLE, ConversationState.LISTENING)
        assert transitions[1] == (ConversationState.LISTENING, ConversationState.PROCESSING)

    def test_on_enter_handler(self):
        """Test state entry callback."""
        sm = ConversationStateMachine()
        entered = []

        sm.on_enter(ConversationState.LISTENING, lambda s: entered.append(s))

        sm.transition_to(ConversationState.LISTENING)

        assert len(entered) == 1
        assert entered[0] == ConversationState.LISTENING

    def test_on_exit_handler(self):
        """Test state exit callback."""
        sm = ConversationStateMachine()
        exited = []

        sm.on_exit(ConversationState.IDLE, lambda s: exited.append(s))

        sm.transition_to(ConversationState.LISTENING)

        assert len(exited) == 1
        assert exited[0] == ConversationState.IDLE


class TestValidTransitions:
    """Tests for valid transition map."""

    def test_idle_transitions(self):
        """Test valid transitions from IDLE."""
        valid = VALID_TRANSITIONS[ConversationState.IDLE]
        assert ConversationState.LISTENING in valid
        assert ConversationState.PROCESSING not in valid

    def test_listening_transitions(self):
        """Test valid transitions from LISTENING."""
        valid = VALID_TRANSITIONS[ConversationState.LISTENING]
        assert ConversationState.PROCESSING in valid
        assert ConversationState.IDLE in valid

    def test_speaking_transitions(self):
        """Test valid transitions from SPEAKING."""
        valid = VALID_TRANSITIONS[ConversationState.SPEAKING]
        assert ConversationState.IDLE in valid
        assert ConversationState.INTERRUPTED in valid

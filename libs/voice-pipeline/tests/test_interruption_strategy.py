"""Tests for interruption strategies (Phase 9).

Tests the InterruptionStrategy interface and all implementations:
- ImmediateInterruption
- GracefulInterruption
- BackchannelAwareInterruption

Also tests:
- ConversationStateMachine v2 (FULL_DUPLEX state)
- Builder integration (.interruption() method)
- Chain integration
"""

import pytest

from voice_pipeline.interfaces.interruption import (
    InterruptionContext,
    InterruptionDecision,
    InterruptionStrategy,
)
from voice_pipeline.providers.interruption.immediate import ImmediateInterruption
from voice_pipeline.providers.interruption.graceful import GracefulInterruption
from voice_pipeline.providers.interruption.backchannel import BackchannelAwareInterruption
from voice_pipeline.core.state_machine import ConversationState, ConversationStateMachine


# =============================================================================
# InterruptionStrategy Interface
# =============================================================================


class TestInterruptionInterface:
    """Test the abstract interface and enums."""

    def test_decision_enum_values(self):
        assert InterruptionDecision.IGNORE.value == "ignore"
        assert InterruptionDecision.INTERRUPT_IMMEDIATE.value == "interrupt_immediate"
        assert InterruptionDecision.INTERRUPT_GRACEFUL.value == "interrupt_graceful"
        assert InterruptionDecision.BACKCHANNEL.value == "backchannel"

    def test_context_defaults(self):
        ctx = InterruptionContext()
        assert ctx.user_is_speaking is False
        assert ctx.agent_is_speaking is False
        assert ctx.user_speech_duration_ms == 0.0
        assert ctx.user_speech_confidence == 0.0
        assert ctx.agent_speech_duration_ms == 0.0
        assert ctx.agent_chunks_remaining == 0
        assert ctx.current_chunk_progress == 0.0
        assert ctx.partial_transcript is None
        assert ctx.conversation_turn_count == 0

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            InterruptionStrategy()

    def test_all_strategies_implement_interface(self):
        strategies = [
            ImmediateInterruption(),
            GracefulInterruption(),
            BackchannelAwareInterruption(),
        ]
        for s in strategies:
            assert isinstance(s, InterruptionStrategy)
            assert hasattr(s, "decide")
            assert hasattr(s, "reset")
            assert hasattr(s, "on_interruption_executed")
            assert hasattr(s, "name")

    def test_strategy_name_property(self):
        assert "ImmediateInterruption" in ImmediateInterruption().name
        assert "GracefulInterruption" in GracefulInterruption().name
        assert "BackchannelAwareInterruption" in BackchannelAwareInterruption().name


# =============================================================================
# ImmediateInterruption
# =============================================================================


class TestImmediateInterruption:
    """Test immediate interruption strategy."""

    @pytest.fixture
    def strategy(self):
        return ImmediateInterruption(
            min_speech_ms=200,
            min_confidence=0.5,
            debounce_ms=500,
        )

    @pytest.mark.asyncio
    async def test_ignore_no_user_speech(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=False,
            agent_is_speaking=True,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_ignore_no_agent_speech(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=False,
            user_speech_duration_ms=500,
            user_speech_confidence=0.9,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_ignore_low_confidence(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=500,
            user_speech_confidence=0.3,  # Below 0.5 threshold
        )
        assert await strategy.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_ignore_short_speech(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=100,  # Below 200ms threshold
            user_speech_confidence=0.9,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_interrupt_on_sustained_speech(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_debounce_prevents_rapid_interruptions(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
            time_since_last_interruption_ms=200,  # Within 500ms debounce
        )
        assert await strategy.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_debounce_expired_allows_interruption(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
            time_since_last_interruption_ms=600,  # Past 500ms debounce
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        strategy = ImmediateInterruption(min_speech_ms=100)
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=150,
            user_speech_confidence=0.9,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_exact_threshold_boundary(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=200,  # Exactly at threshold
            user_speech_confidence=0.5,   # Exactly at confidence threshold
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_IMMEDIATE


# =============================================================================
# GracefulInterruption
# =============================================================================


class TestGracefulInterruption:
    """Test graceful interruption strategy."""

    @pytest.fixture
    def strategy(self):
        return GracefulInterruption(
            min_speech_ms=300,
            finish_threshold=0.3,
        )

    @pytest.mark.asyncio
    async def test_ignore_no_speech(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=False,
            agent_is_speaking=True,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_ignore_short_speech(self, strategy):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=200,  # Below 300ms
            user_speech_confidence=0.9,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_graceful_when_chunk_advanced(self, strategy):
        """Graceful interrupt when chunk progress >= finish_threshold."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=400,
            user_speech_confidence=0.9,
            current_chunk_progress=0.5,  # >= 0.3 threshold
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_GRACEFUL

    @pytest.mark.asyncio
    async def test_immediate_when_chunk_early(self, strategy):
        """Immediate interrupt when chunk progress < finish_threshold."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=400,
            user_speech_confidence=0.9,
            current_chunk_progress=0.1,  # < 0.3 threshold
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_graceful_at_threshold_boundary(self, strategy):
        """Exactly at finish_threshold → graceful."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=400,
            user_speech_confidence=0.9,
            current_chunk_progress=0.3,  # Exactly at threshold
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_GRACEFUL

    @pytest.mark.asyncio
    async def test_custom_finish_threshold(self):
        strategy = GracefulInterruption(min_speech_ms=200, finish_threshold=0.7)
        # Chunk at 50% — below 70% threshold → immediate
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
            current_chunk_progress=0.5,
        )
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_IMMEDIATE

        # Chunk at 80% — above 70% threshold → graceful
        ctx.current_chunk_progress = 0.8
        assert await strategy.decide(ctx) == InterruptionDecision.INTERRUPT_GRACEFUL


# =============================================================================
# BackchannelAwareInterruption
# =============================================================================


class TestBackchannelAwareInterruption:
    """Test backchannel-aware interruption strategy."""

    @pytest.fixture
    def strategy_pt(self):
        return BackchannelAwareInterruption(
            backchannel_max_ms=500,
            interruption_min_ms=800,
            language="pt",
        )

    @pytest.fixture
    def strategy_en(self):
        return BackchannelAwareInterruption(
            backchannel_max_ms=500,
            interruption_min_ms=800,
            language="en",
        )

    @pytest.mark.asyncio
    async def test_ignore_no_speech(self, strategy_pt):
        ctx = InterruptionContext(
            user_is_speaking=False,
            agent_is_speaking=True,
        )
        assert await strategy_pt.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_backchannel_by_duration_short(self, strategy_pt):
        """Short speech (<500ms) classified as backchannel."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
        )
        assert await strategy_pt.decide(ctx) == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_interrupt_long_speech(self, strategy_pt):
        """Long speech (>800ms) classified as real interruption."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=900,
            user_speech_confidence=0.9,
        )
        assert await strategy_pt.decide(ctx) == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_uncertain_zone_no_transcript(self, strategy_pt):
        """Uncertain zone (500-800ms) without transcript → IGNORE (wait)."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=650,
            user_speech_confidence=0.9,
            partial_transcript=None,
        )
        assert await strategy_pt.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_backchannel_by_transcript_pt(self, strategy_pt):
        """Backchannel detected by Portuguese transcript."""
        backchannel_words = ["uhum", "sim", "entendi", "certo", "ok"]
        for word in backchannel_words:
            ctx = InterruptionContext(
                user_is_speaking=True,
                agent_is_speaking=True,
                user_speech_duration_ms=400,
                user_speech_confidence=0.9,
                partial_transcript=word,
            )
            decision = await strategy_pt.decide(ctx)
            assert decision == InterruptionDecision.BACKCHANNEL, (
                f"Expected BACKCHANNEL for '{word}', got {decision}"
            )

    @pytest.mark.asyncio
    async def test_backchannel_by_transcript_en(self, strategy_en):
        """Backchannel detected by English transcript."""
        backchannel_words = ["yeah", "ok", "right", "mhm"]
        for word in backchannel_words:
            ctx = InterruptionContext(
                user_is_speaking=True,
                agent_is_speaking=True,
                user_speech_duration_ms=400,
                user_speech_confidence=0.9,
                partial_transcript=word,
            )
            decision = await strategy_en.decide(ctx)
            assert decision == InterruptionDecision.BACKCHANNEL, (
                f"Expected BACKCHANNEL for '{word}', got {decision}"
            )

    @pytest.mark.asyncio
    async def test_uncertain_zone_backchannel_transcript(self, strategy_pt):
        """Uncertain zone with backchannel transcript → BACKCHANNEL."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=650,  # Uncertain zone
            user_speech_confidence=0.9,
            partial_transcript="uhum",
        )
        assert await strategy_pt.decide(ctx) == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_uncertain_zone_real_speech_transcript(self, strategy_pt):
        """Uncertain zone with real speech transcript → IGNORE (wait for more)."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=650,
            user_speech_confidence=0.9,
            partial_transcript="Eu quero falar sobre",
        )
        # Not a backchannel word, in uncertain zone → IGNORE
        assert await strategy_pt.decide(ctx) == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_backchannel_count_tracking(self, strategy_pt):
        """Track backchannel count."""
        assert strategy_pt.backchannel_count == 0
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
        )
        await strategy_pt.decide(ctx)
        assert strategy_pt.backchannel_count == 1

    @pytest.mark.asyncio
    async def test_interruption_count_tracking(self, strategy_pt):
        """Track real interruption count."""
        assert strategy_pt.interruption_count == 0
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=900,
            user_speech_confidence=0.9,
        )
        await strategy_pt.decide(ctx)
        assert strategy_pt.interruption_count == 1

    @pytest.mark.asyncio
    async def test_reset_clears_counts(self, strategy_pt):
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
        )
        await strategy_pt.decide(ctx)
        assert strategy_pt.backchannel_count > 0
        strategy_pt.reset()
        assert strategy_pt.backchannel_count == 0
        assert strategy_pt.interruption_count == 0

    @pytest.mark.asyncio
    async def test_debounce(self, strategy_pt):
        """Debounce prevents rapid decisions."""
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
            time_since_last_interruption_ms=100,  # Within 300ms debounce
        )
        assert await strategy_pt.decide(ctx) == InterruptionDecision.IGNORE

    def test_is_backchannel_text_pt(self):
        """Test backchannel text detection for Portuguese."""
        strategy = BackchannelAwareInterruption(language="pt")
        assert strategy._is_backchannel_text("uhum") is True
        assert strategy._is_backchannel_text("Sim") is True
        assert strategy._is_backchannel_text("ok") is True
        assert strategy._is_backchannel_text("entendi") is True
        assert strategy._is_backchannel_text("") is False
        assert strategy._is_backchannel_text("Eu quero saber mais") is False

    def test_is_backchannel_text_en(self):
        """Test backchannel text detection for English."""
        strategy = BackchannelAwareInterruption(language="en")
        assert strategy._is_backchannel_text("yeah") is True
        assert strategy._is_backchannel_text("ok") is True
        assert strategy._is_backchannel_text("right") is True
        assert strategy._is_backchannel_text("") is False
        assert strategy._is_backchannel_text("I want to ask something") is False


# =============================================================================
# ConversationStateMachine v2 (FULL_DUPLEX)
# =============================================================================


class TestStateMachineFullDuplex:
    """Test the enhanced state machine with FULL_DUPLEX state."""

    def test_full_duplex_state_exists(self):
        assert ConversationState.FULL_DUPLEX.value == "full_duplex"

    def test_speaking_to_full_duplex_transition(self):
        sm = ConversationStateMachine()
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        assert sm.can_transition_to(ConversationState.FULL_DUPLEX)
        assert sm.transition_to(ConversationState.FULL_DUPLEX)
        assert sm.is_full_duplex

    def test_full_duplex_to_listening(self):
        """User takes floor after overlap."""
        sm = ConversationStateMachine()
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.FULL_DUPLEX)
        assert sm.transition_to(ConversationState.LISTENING)
        assert sm.is_listening

    def test_full_duplex_to_speaking(self):
        """Backchannel — agent continues speaking."""
        sm = ConversationStateMachine()
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.FULL_DUPLEX)
        assert sm.transition_to(ConversationState.SPEAKING)
        assert sm.is_speaking

    def test_full_duplex_to_interrupted(self):
        """Immediate interruption from full duplex."""
        sm = ConversationStateMachine()
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.FULL_DUPLEX)
        assert sm.transition_to(ConversationState.INTERRUPTED)

    def test_full_duplex_to_idle(self):
        """Both stop — conversation ends."""
        sm = ConversationStateMachine()
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.FULL_DUPLEX)
        assert sm.transition_to(ConversationState.IDLE)
        assert sm.is_idle

    def test_full_duplex_invalid_transitions(self):
        """FULL_DUPLEX cannot go to PROCESSING."""
        sm = ConversationStateMachine()
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.FULL_DUPLEX)
        assert not sm.can_transition_to(ConversationState.PROCESSING)
        assert not sm.transition_to(ConversationState.PROCESSING)

    def test_idle_cannot_go_to_full_duplex(self):
        """IDLE cannot transition directly to FULL_DUPLEX."""
        sm = ConversationStateMachine()
        assert not sm.can_transition_to(ConversationState.FULL_DUPLEX)

    def test_is_full_duplex_property(self):
        sm = ConversationStateMachine()
        assert not sm.is_full_duplex
        sm.transition_to(ConversationState.LISTENING)
        assert not sm.is_full_duplex

    def test_backward_compatible_flow(self):
        """Original flow (without FULL_DUPLEX) still works."""
        sm = ConversationStateMachine()
        assert sm.is_idle
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.INTERRUPTED)
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.IDLE)
        assert sm.is_idle

    def test_handlers_called_on_full_duplex(self):
        """State change handlers fire for FULL_DUPLEX transitions."""
        transitions = []
        sm = ConversationStateMachine()
        sm.on_state_change(lambda old, new: transitions.append((old, new)))

        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.FULL_DUPLEX)

        assert (ConversationState.SPEAKING, ConversationState.FULL_DUPLEX) in transitions

    def test_entry_exit_handlers_full_duplex(self):
        entered = []
        exited = []
        sm = ConversationStateMachine()
        sm.on_enter(ConversationState.FULL_DUPLEX, lambda s: entered.append(s))
        sm.on_exit(ConversationState.FULL_DUPLEX, lambda s: exited.append(s))

        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)
        sm.transition_to(ConversationState.FULL_DUPLEX)
        assert len(entered) == 1
        assert entered[0] == ConversationState.FULL_DUPLEX

        sm.transition_to(ConversationState.SPEAKING)
        assert len(exited) == 1
        assert exited[0] == ConversationState.FULL_DUPLEX


# =============================================================================
# Builder Integration
# =============================================================================


class TestBuilderInterruption:
    """Test VoiceAgentBuilder.interruption()."""

    def test_immediate_strategy(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        result = b.interruption("immediate", min_speech_ms=100)
        assert result is b
        assert isinstance(b._interruption_strategy, ImmediateInterruption)
        assert b._interruption_strategy.min_speech_ms == 100

    def test_graceful_strategy(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        b.interruption("graceful", finish_threshold=0.5)
        assert isinstance(b._interruption_strategy, GracefulInterruption)
        assert b._interruption_strategy.finish_threshold == 0.5

    def test_backchannel_strategy(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        b.interruption("backchannel", language="en")
        assert isinstance(b._interruption_strategy, BackchannelAwareInterruption)
        assert b._interruption_strategy.language == "en"

    def test_invalid_strategy_raises(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = VoiceAgentBuilder()
        with pytest.raises(ValueError, match="Unknown interruption strategy"):
            b.interruption("unknown")

    def test_chaining_with_other_methods(self):
        from voice_pipeline.agents.base import VoiceAgentBuilder
        b = (
            VoiceAgentBuilder()
            .interruption("backchannel")
            .streaming_granularity("clause")
        )
        assert isinstance(b._interruption_strategy, BackchannelAwareInterruption)


# =============================================================================
# Chain Integration
# =============================================================================


class TestChainInterruption:
    """Test StreamingVoiceChain accepts interruption_strategy."""

    def test_chain_accepts_strategy(self):
        from unittest.mock import MagicMock
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        strategy = BackchannelAwareInterruption(language="pt")
        chain = StreamingVoiceChain(
            asr=MagicMock(),
            llm=MagicMock(),
            tts=MagicMock(),
            interruption_strategy=strategy,
        )
        assert chain.interruption_strategy is strategy

    def test_chain_default_none(self):
        from unittest.mock import MagicMock
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        chain = StreamingVoiceChain(
            asr=MagicMock(),
            llm=MagicMock(),
            tts=MagicMock(),
        )
        assert chain.interruption_strategy is None


# =============================================================================
# Full-Duplex Flow Simulation
# =============================================================================


class TestFullDuplexFlow:
    """Simulate full-duplex conversation flow with all components."""

    @pytest.mark.asyncio
    async def test_backchannel_flow(self):
        """Simulate: agent speaking → user backchannels → agent continues."""
        sm = ConversationStateMachine()
        strategy = BackchannelAwareInterruption(language="pt")

        # Agent starts speaking
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)

        # User says "uhum" (backchannel)
        sm.transition_to(ConversationState.FULL_DUPLEX)
        assert sm.is_full_duplex

        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=300,
            user_speech_confidence=0.9,
            partial_transcript="uhum",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

        # Agent continues speaking
        sm.transition_to(ConversationState.SPEAKING)
        assert sm.is_speaking

    @pytest.mark.asyncio
    async def test_real_interruption_flow(self):
        """Simulate: agent speaking → user interrupts → agent stops."""
        sm = ConversationStateMachine()
        strategy = BackchannelAwareInterruption(language="pt")

        # Agent starts speaking
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)

        # User starts speaking (enters full duplex)
        sm.transition_to(ConversationState.FULL_DUPLEX)

        # User keeps speaking — long duration → real interruption
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=1000,
            user_speech_confidence=0.9,
            partial_transcript="Eu quero falar sobre outra coisa",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

        # Agent stops, user takes floor
        sm.transition_to(ConversationState.INTERRUPTED)
        sm.transition_to(ConversationState.LISTENING)
        assert sm.is_listening

    @pytest.mark.asyncio
    async def test_graceful_flow(self):
        """Simulate: agent speaking → user interrupts → graceful stop."""
        sm = ConversationStateMachine()
        strategy = GracefulInterruption(min_speech_ms=200, finish_threshold=0.4)

        # Agent speaking
        sm.transition_to(ConversationState.LISTENING)
        sm.transition_to(ConversationState.PROCESSING)
        sm.transition_to(ConversationState.SPEAKING)

        # User interrupts while chunk is 50% done
        sm.transition_to(ConversationState.FULL_DUPLEX)
        ctx = InterruptionContext(
            user_is_speaking=True,
            agent_is_speaking=True,
            user_speech_duration_ms=400,
            user_speech_confidence=0.9,
            current_chunk_progress=0.5,  # >= 0.4 threshold
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_GRACEFUL

        # Agent finishes current chunk, then stops
        sm.transition_to(ConversationState.LISTENING)

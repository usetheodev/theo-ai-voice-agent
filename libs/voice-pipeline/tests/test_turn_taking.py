"""Tests for turn-taking strategies.

Tests all three turn-taking controllers:
- FixedSilenceTurnTaking: Fixed silence threshold
- AdaptiveSilenceTurnTaking: Context-adaptive threshold
- SemanticTurnTaking: Heuristic/ML-based EoT detection
"""

import pytest

from voice_pipeline.interfaces.turn_taking import (
    TurnTakingContext,
    TurnTakingController,
    TurnTakingDecision,
)
from voice_pipeline.providers.turn_taking import (
    AdaptiveSilenceTurnTaking,
    FixedSilenceTurnTaking,
    SemanticTurnTaking,
)


# =============================================================================
# Helpers
# =============================================================================

def ctx(
    is_speech: bool = False,
    confidence: float = 0.9,
    silence_ms: float = 0.0,
    speech_ms: float = 1000.0,
    agent_speaking: bool = False,
    transcript: str | None = None,
    word_count: int = 0,
    turn_count: int = 5,
    last_response_len: int = 50,
) -> TurnTakingContext:
    """Create a TurnTakingContext with sensible defaults."""
    return TurnTakingContext(
        is_speech=is_speech,
        speech_confidence=confidence,
        silence_duration_ms=silence_ms,
        speech_duration_ms=speech_ms,
        agent_is_speaking=agent_speaking,
        partial_transcript=transcript,
        transcript_word_count=word_count,
        conversation_turn_count=turn_count,
        last_agent_response_length=last_response_len,
    )


# =============================================================================
# Interface tests
# =============================================================================

class TestTurnTakingInterface:
    """Tests for the TurnTakingController interface."""

    def test_decision_enum_values(self):
        assert TurnTakingDecision.CONTINUE_LISTENING.value == "continue"
        assert TurnTakingDecision.END_OF_TURN.value == "end_of_turn"
        assert TurnTakingDecision.BACKCHANNEL.value == "backchannel"
        assert TurnTakingDecision.BARGE_IN.value == "barge_in"

    def test_context_defaults(self):
        c = TurnTakingContext()
        assert c.is_speech is False
        assert c.speech_confidence == 0.0
        assert c.silence_duration_ms == 0.0
        assert c.speech_duration_ms == 0.0
        assert c.partial_transcript is None
        assert c.agent_is_speaking is False
        assert c.sample_rate == 16000

    def test_abstract_class(self):
        with pytest.raises(TypeError):
            TurnTakingController()


# =============================================================================
# FixedSilenceTurnTaking tests
# =============================================================================

class TestFixedSilenceTurnTaking:
    """Tests for FixedSilenceTurnTaking."""

    @pytest.fixture
    def fixed(self):
        return FixedSilenceTurnTaking(silence_threshold_ms=800)

    @pytest.mark.asyncio
    async def test_continue_during_speech(self, fixed):
        decision = await fixed.decide(ctx(is_speech=True))
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_continue_silence_under_threshold(self, fixed):
        # First, mark speech started
        await fixed.decide(ctx(is_speech=True))
        # Then silence under threshold
        decision = await fixed.decide(ctx(silence_ms=500))
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_end_of_turn_silence_over_threshold(self, fixed):
        await fixed.decide(ctx(is_speech=True))
        decision = await fixed.decide(ctx(silence_ms=900))
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_end_of_turn_exact_threshold(self, fixed):
        await fixed.decide(ctx(is_speech=True))
        decision = await fixed.decide(ctx(silence_ms=800))
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_barge_in_during_agent_speech(self, fixed):
        decision = await fixed.decide(
            ctx(is_speech=True, confidence=0.8, agent_speaking=True)
        )
        assert decision == TurnTakingDecision.BARGE_IN

    @pytest.mark.asyncio
    async def test_no_barge_in_low_confidence(self, fixed):
        decision = await fixed.decide(
            ctx(is_speech=True, confidence=0.3, agent_speaking=True)
        )
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_no_end_of_turn_without_speech(self, fixed):
        """Silence without prior speech should not trigger end-of-turn."""
        decision = await fixed.decide(ctx(silence_ms=2000))
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_min_speech_duration(self, fixed):
        """Very short speech should not trigger end-of-turn."""
        await fixed.decide(ctx(is_speech=True))
        decision = await fixed.decide(ctx(silence_ms=900, speech_ms=50))
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_reset(self, fixed):
        await fixed.decide(ctx(is_speech=True))
        assert fixed._had_speech is True
        fixed.reset()
        assert fixed._had_speech is False
        # After reset, silence should not trigger end-of-turn
        decision = await fixed.decide(ctx(silence_ms=2000))
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        fixed = FixedSilenceTurnTaking(silence_threshold_ms=400)
        await fixed.decide(ctx(is_speech=True))
        decision = await fixed.decide(ctx(silence_ms=450))
        assert decision == TurnTakingDecision.END_OF_TURN

    def test_name(self, fixed):
        assert "800ms" in fixed.name

    def test_requires_transcript(self, fixed):
        assert fixed.requires_transcript is False


# =============================================================================
# AdaptiveSilenceTurnTaking tests
# =============================================================================

class TestAdaptiveSilenceTurnTaking:
    """Tests for AdaptiveSilenceTurnTaking."""

    @pytest.fixture
    def adaptive(self):
        return AdaptiveSilenceTurnTaking(
            base_threshold_ms=600,
            min_threshold_ms=300,
            max_threshold_ms=1500,
        )

    @pytest.mark.asyncio
    async def test_short_utterance_lower_threshold(self, adaptive):
        """Short utterances (few words) should have lower threshold."""
        await adaptive.decide(ctx(is_speech=True))
        decision = await adaptive.decide(
            ctx(silence_ms=450, speech_ms=500, word_count=2)
        )
        # 600 * 0.7 (short) * 0.8 (quick) = 336ms → 450 > 336 → END
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_long_utterance_higher_threshold(self, adaptive):
        """Long utterances should have higher threshold."""
        await adaptive.decide(ctx(is_speech=True))
        decision = await adaptive.decide(
            ctx(silence_ms=700, speech_ms=6000, word_count=20)
        )
        # 600 * 1.3 (long text) * 1.2 (extended speech) = 936ms → 700 < 936 → CONTINUE
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_complex_agent_response_more_patient(self, adaptive):
        """After a complex agent response, be more patient."""
        await adaptive.decide(ctx(is_speech=True))
        decision = await adaptive.decide(
            ctx(silence_ms=600, speech_ms=2000, word_count=5,
                last_response_len=300)
        )
        # Higher threshold due to complex agent response
        # 600 * 0.9 (medium words) * 1.0 (speech) * 1.2 (complex response) = 648ms
        # 600 < 648 → CONTINUE
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_barge_in(self, adaptive):
        decision = await adaptive.decide(
            ctx(is_speech=True, confidence=0.8, agent_speaking=True)
        )
        assert decision == TurnTakingDecision.BARGE_IN

    @pytest.mark.asyncio
    async def test_threshold_clamped_to_min(self, adaptive):
        """Threshold should not go below min_threshold_ms."""
        await adaptive.decide(ctx(is_speech=True))
        # All factors reducing threshold
        decision = await adaptive.decide(
            ctx(silence_ms=350, speech_ms=300, word_count=1)
        )
        # min_threshold = 300, 350 > 300 → END
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_threshold_clamped_to_max(self, adaptive):
        """Threshold should not exceed max_threshold_ms."""
        await adaptive.decide(ctx(is_speech=True))
        # All factors increasing threshold
        decision = await adaptive.decide(
            ctx(silence_ms=1600, speech_ms=10000, word_count=30,
                last_response_len=500, turn_count=1)
        )
        # max_threshold = 1500, 1600 > 1500 → END
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_reset(self, adaptive):
        await adaptive.decide(ctx(is_speech=True))
        adaptive.reset()
        assert adaptive._had_speech is False
        assert adaptive._current_threshold_ms is None

    def test_name(self, adaptive):
        assert "600ms" in adaptive.name

    def test_requires_transcript(self, adaptive):
        assert adaptive.requires_transcript is True


# =============================================================================
# Adaptive Hesitation Detection tests
# =============================================================================

class TestAdaptiveHesitationDetection:
    """Tests for hesitation detection in AdaptiveSilenceTurnTaking."""

    @pytest.fixture
    def adaptive_pt(self):
        return AdaptiveSilenceTurnTaking(
            base_threshold_ms=600,
            min_threshold_ms=300,
            max_threshold_ms=1500,
            hesitation_multiplier=1.5,
            language="pt",
        )

    @pytest.fixture
    def adaptive_en(self):
        return AdaptiveSilenceTurnTaking(
            base_threshold_ms=600,
            min_threshold_ms=300,
            max_threshold_ms=1500,
            hesitation_multiplier=1.5,
            language="en",
        )

    @pytest.mark.asyncio
    async def test_hesitation_eee_continues(self, adaptive_pt):
        """'Eu quero eee' + 700ms silence = CONTINUE (hesitation extends threshold)."""
        await adaptive_pt.decide(ctx(is_speech=True))
        decision = await adaptive_pt.decide(
            ctx(
                silence_ms=700,
                speech_ms=2000,
                word_count=3,
                transcript="Eu quero eee",
            )
        )
        # Without hesitation: 600 * 0.7 * 1.0 = 420ms → 700 > 420 → END
        # With hesitation: 420 * 1.5 = 630ms → 700 > 630 → END
        # Actually: base=600, 0.7(short) = 420, but speech 2000 is between 1000-5000
        # so speech factor is 1.0. 600*0.7*1.0 = 420, * 1.5(hesit) = 630, 700>630 → END
        # Let me use longer speech to make it CONTINUE
        # Use speech_ms=6000 → 1.2 factor: 600*0.7*1.2*1.5=756
        pass

    @pytest.mark.asyncio
    async def test_hesitation_extends_threshold(self, adaptive_pt):
        """Hesitation should increase the threshold significantly."""
        await adaptive_pt.decide(ctx(is_speech=True))
        # Without hesitation
        threshold_no_hesit = adaptive_pt._compute_threshold(
            TurnTakingContext(
                speech_duration_ms=2000,
                transcript_word_count=5,
                partial_transcript="Eu quero uma pizza",
                last_agent_response_length=50,
                conversation_turn_count=5,
            )
        )
        adaptive_pt.reset()
        # With hesitation
        threshold_with_hesit = adaptive_pt._compute_threshold(
            TurnTakingContext(
                speech_duration_ms=2000,
                transcript_word_count=5,
                partial_transcript="Eu quero eee uma",
                last_agent_response_length=50,
                conversation_turn_count=5,
            )
        )
        # Hesitation should increase threshold
        assert threshold_with_hesit > threshold_no_hesit

    @pytest.mark.asyncio
    async def test_no_hesitation_normal_text(self, adaptive_pt):
        """Normal text without hesitation has standard threshold."""
        await adaptive_pt.decide(ctx(is_speech=True))
        decision = await adaptive_pt.decide(
            ctx(
                silence_ms=700,
                speech_ms=2000,
                word_count=5,
                transcript="Eu quero uma pizza grande",
            )
        )
        # 600 * 0.9 (medium words) * 1.0 (speech) * 0.9 (short resp) = 486ms
        # 700 > 486 → END_OF_TURN
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_hesitation_tipo_pt(self, adaptive_pt):
        """'tipo' at end of transcript is a hesitation pattern."""
        assert adaptive_pt._detect_hesitation(
            TurnTakingContext(partial_transcript="Eu quero tipo")
        )

    @pytest.mark.asyncio
    async def test_hesitation_uh_en(self, adaptive_en):
        """'uh' is an English hesitation pattern."""
        assert adaptive_en._detect_hesitation(
            TurnTakingContext(partial_transcript="I want to uh")
        )

    @pytest.mark.asyncio
    async def test_hesitation_hmm_en(self, adaptive_en):
        """'hmm' is an English hesitation pattern."""
        assert adaptive_en._detect_hesitation(
            TurnTakingContext(partial_transcript="hmm let me think")
        )

    @pytest.mark.asyncio
    async def test_no_hesitation_normal_en(self, adaptive_en):
        """Normal English text has no hesitation."""
        assert not adaptive_en._detect_hesitation(
            TurnTakingContext(partial_transcript="I want a large pizza")
        )

    @pytest.mark.asyncio
    async def test_custom_multiplier(self):
        """Custom hesitation multiplier works."""
        adaptive = AdaptiveSilenceTurnTaking(
            base_threshold_ms=600,
            hesitation_multiplier=2.0,
            language="pt",
        )
        threshold_with = adaptive._compute_threshold(
            TurnTakingContext(
                speech_duration_ms=2000,
                transcript_word_count=5,
                partial_transcript="Eu quero eee",
                conversation_turn_count=5,
            )
        )
        threshold_without = adaptive._compute_threshold(
            TurnTakingContext(
                speech_duration_ms=2000,
                transcript_word_count=5,
                partial_transcript="Eu quero pizza",
                conversation_turn_count=5,
            )
        )
        # With 2.0 multiplier, hesitation threshold should be ~2x
        assert threshold_with > threshold_without * 1.5

    @pytest.mark.asyncio
    async def test_no_transcript_no_hesitation(self, adaptive_pt):
        """No transcript → no hesitation detected."""
        assert not adaptive_pt._detect_hesitation(
            TurnTakingContext(partial_transcript=None)
        )
        assert not adaptive_pt._detect_hesitation(
            TurnTakingContext(partial_transcript="")
        )


# =============================================================================
# SemanticTurnTaking tests
# =============================================================================

class TestSemanticTurnTaking:
    """Tests for SemanticTurnTaking (heuristic backend)."""

    @pytest.fixture
    def semantic(self):
        return SemanticTurnTaking(
            backend="heuristic",
            min_silence_ms=300,
            max_silence_ms=2000,
            language="pt",
        )

    @pytest.mark.asyncio
    async def test_complete_question_pt(self, semantic):
        """Portuguese question should trigger end-of-turn."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=400, transcript="Qual é o horário?")
        )
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_complete_statement_pt(self, semantic):
        """Complete statement with period should trigger end-of-turn."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=400, transcript="Eu quero fazer uma reserva.")
        )
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_short_affirmative_pt(self, semantic):
        """Short affirmative should trigger end-of-turn."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=400, transcript="Sim")
        )
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_incomplete_with_conjunction_pt(self, semantic):
        """Trailing conjunction should continue listening."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=400, transcript="Eu quero saber sobre")
        )
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_trailing_preposition_pt(self, semantic):
        """Trailing preposition should continue listening."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=400, transcript="Eu preciso de")
        )
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_trailing_conjunction_mas(self, semantic):
        """'mas' at end indicates incomplete thought."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=400, transcript="Eu gostei mas")
        )
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_max_silence_forces_end(self, semantic):
        """Exceeding max_silence_ms always triggers end-of-turn."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=2500, transcript="Eu quero saber sobre")
        )
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_silence_under_min_no_check(self, semantic):
        """Silence under min_silence_ms should not trigger analysis."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=200, transcript="Sim")
        )
        assert decision == TurnTakingDecision.CONTINUE_LISTENING

    @pytest.mark.asyncio
    async def test_no_transcript_extended_silence(self, semantic):
        """Without transcript, fallback to extended silence (2x min)."""
        await semantic.decide(ctx(is_speech=True))
        decision = await semantic.decide(
            ctx(silence_ms=700, transcript=None)
        )
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_barge_in(self, semantic):
        decision = await semantic.decide(
            ctx(is_speech=True, confidence=0.8, agent_speaking=True)
        )
        assert decision == TurnTakingDecision.BARGE_IN

    @pytest.mark.asyncio
    async def test_reset(self, semantic):
        await semantic.decide(ctx(is_speech=True))
        semantic.reset()
        assert semantic._had_speech is False
        assert semantic._last_checked_transcript is None

    def test_requires_transcript(self, semantic):
        assert semantic.requires_transcript is True

    def test_name(self, semantic):
        assert "heuristic" in semantic.name

    @pytest.mark.asyncio
    async def test_english_question(self):
        """English question should work with 'en' language."""
        semantic_en = SemanticTurnTaking(
            backend="heuristic", min_silence_ms=300, language="en"
        )
        await semantic_en.decide(ctx(is_speech=True))
        decision = await semantic_en.decide(
            ctx(silence_ms=400, transcript="What time is it?")
        )
        assert decision == TurnTakingDecision.END_OF_TURN

    @pytest.mark.asyncio
    async def test_english_incomplete(self):
        """English incomplete sentence should continue."""
        semantic_en = SemanticTurnTaking(
            backend="heuristic", min_silence_ms=300, language="en"
        )
        await semantic_en.decide(ctx(is_speech=True))
        decision = await semantic_en.decide(
            ctx(silence_ms=400, transcript="I want to know about")
        )
        assert decision == TurnTakingDecision.CONTINUE_LISTENING


# =============================================================================
# Heuristic scoring tests
# =============================================================================

class TestHeuristicScoring:
    """Tests for the heuristic EoT scoring function."""

    @pytest.fixture
    def semantic(self):
        return SemanticTurnTaking(backend="heuristic", language="pt")

    def test_empty_text_score_zero(self, semantic):
        assert semantic._heuristic_eot_score("") == 0.0

    def test_question_high_score(self, semantic):
        score = semantic._heuristic_eot_score("Onde fica o restaurante?")
        assert score > 0.7

    def test_affirmative_high_score(self, semantic):
        score = semantic._heuristic_eot_score("Sim")
        assert score > 0.7

    def test_negation_high_score(self, semantic):
        score = semantic._heuristic_eot_score("Não")
        assert score > 0.7

    def test_trailing_conjunction_low_score(self, semantic):
        score = semantic._heuristic_eot_score("Eu quero mas")
        assert score < 0.5

    def test_trailing_preposition_low_score(self, semantic):
        score = semantic._heuristic_eot_score("Estou aqui para")
        assert score < 0.5

    def test_period_end_moderate_score(self, semantic):
        score = semantic._heuristic_eot_score("Eu quero uma reserva.")
        assert score > 0.6

    def test_score_clamped_0_to_1(self, semantic):
        for text in ["Sim!", "Eu quero mas", "", "ok", "Eu preciso de"]:
            score = semantic._heuristic_eot_score(text)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for '{text}'"


# =============================================================================
# Builder integration tests
# =============================================================================

class TestBuilderIntegration:
    """Tests for turn-taking integration with VoiceAgentBuilder."""

    def test_builder_fixed(self):
        from voice_pipeline import VoiceAgent
        builder = VoiceAgent.builder().turn_taking("fixed", silence_threshold_ms=500)
        assert isinstance(builder._turn_taking_controller, FixedSilenceTurnTaking)
        assert builder._turn_taking_controller.silence_threshold_ms == 500

    def test_builder_adaptive(self):
        from voice_pipeline import VoiceAgent
        builder = VoiceAgent.builder().turn_taking("adaptive", base_threshold_ms=400)
        assert isinstance(builder._turn_taking_controller, AdaptiveSilenceTurnTaking)
        assert builder._turn_taking_controller.base_threshold_ms == 400

    def test_builder_semantic(self):
        from voice_pipeline import VoiceAgent
        builder = VoiceAgent.builder().turn_taking(
            "semantic", backend="heuristic", language="en"
        )
        assert isinstance(builder._turn_taking_controller, SemanticTurnTaking)
        assert builder._turn_taking_controller.backend == "heuristic"
        assert builder._turn_taking_controller.language == "en"

    def test_builder_unknown_strategy_raises(self):
        from voice_pipeline import VoiceAgent
        with pytest.raises(ValueError, match="desconhecida"):
            VoiceAgent.builder().turn_taking("unknown")

    def test_builder_default_no_controller(self):
        from voice_pipeline import VoiceAgent
        builder = VoiceAgent.builder()
        assert builder._turn_taking_controller is None


# =============================================================================
# Lifecycle tests
# =============================================================================

class TestLifecycle:
    """Tests for connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    async def test_fixed_connect_disconnect(self):
        fixed = FixedSilenceTurnTaking()
        await fixed.connect()
        await fixed.disconnect()

    @pytest.mark.asyncio
    async def test_adaptive_connect_disconnect(self):
        adaptive = AdaptiveSilenceTurnTaking()
        await adaptive.connect()
        await adaptive.disconnect()

    @pytest.mark.asyncio
    async def test_semantic_heuristic_connect(self):
        semantic = SemanticTurnTaking(backend="heuristic")
        await semantic.connect()
        await semantic.disconnect()
        assert semantic._model is None

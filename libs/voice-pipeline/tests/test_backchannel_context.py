"""Tests for context-aware backchannel detection.

Validates that BackchannelAwareInterruption correctly distinguishes between
real user responses to agent questions vs. backchannel acknowledgments.

Key behavior:
- Pure backchannels ("uhum", "aham") → BACKCHANNEL regardless of context
- Context-dependent words ("sim", "ok", "nao") after a question → INTERRUPT_IMMEDIATE
- Context-dependent words after a statement → BACKCHANNEL
- Empty agent_response_text → backward-compatible (no question detected → BACKCHANNEL)

References:
- FireRedChat: Context-aware backchannel classification
- Full-Duplex-Bench: Question-response detection accuracy
"""

import pytest

from voice_pipeline.interfaces.interruption import (
    InterruptionContext,
    InterruptionDecision,
)
from voice_pipeline.providers.interruption.backchannel import (
    BackchannelAwareInterruption,
)


# =============================================================================
# Helpers
# =============================================================================


def _ctx(
    partial_transcript: str = "",
    agent_response_text: str = "",
    duration_ms: float = 400.0,
    confidence: float = 0.9,
) -> InterruptionContext:
    """Create a standard InterruptionContext for testing.

    Defaults represent a typical backchannel scenario: user and agent both
    speaking, short duration, high confidence.
    """
    return InterruptionContext(
        user_is_speaking=True,
        agent_is_speaking=True,
        user_speech_duration_ms=duration_ms,
        user_speech_confidence=confidence,
        partial_transcript=partial_transcript or None,
        agent_response_text=agent_response_text,
    )


# =============================================================================
# Portuguese context-aware tests
# =============================================================================


class TestContextAwareBackchannelPT:
    """Test context-aware backchannel detection for Portuguese (pt-BR).

    The core fix: words like "sim", "nao", "ok" should be classified
    differently depending on whether the agent asked a question.
    """

    @pytest.fixture
    def strategy(self):
        return BackchannelAwareInterruption(
            backchannel_max_ms=500,
            interruption_min_ms=800,
            language="pt",
        )

    # -----------------------------------------------------------------
    # Test 1: "sim" after question → INTERRUPT_IMMEDIATE
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sim_after_question_is_interrupt(self, strategy):
        """'sim' after agent asks 'Quer confirmar?' must be INTERRUPT_IMMEDIATE.

        The user is answering a question, not giving backchannel feedback.
        """
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="Quer confirmar?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_sim_after_multi_sentence_question(self, strategy):
        """'sim' after agent text ending with '?' is still INTERRUPT."""
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="Eu encontrei 3 resultados. Quer que eu leia todos?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    # -----------------------------------------------------------------
    # Test 2: "sim" after statement → BACKCHANNEL
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sim_after_statement_is_backchannel(self, strategy):
        """'sim' after agent says 'Vou explicar...' must be BACKCHANNEL.

        The agent is making a statement, so 'sim' is an acknowledgment.
        """
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="Vou explicar como funciona o sistema.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_sim_after_explanation_is_backchannel(self, strategy):
        """'sim' while agent is explaining something → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="O processo funciona da seguinte forma. Primeiro, você precisa",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    # -----------------------------------------------------------------
    # Test 3: "uhum" is ALWAYS backchannel (pure backchannel)
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_uhum_after_question_is_backchannel(self, strategy):
        """'uhum' after a question is still BACKCHANNEL — it's a pure backchannel.

        Pure backchannels like "uhum", "aham" are always backchannels
        regardless of whether the agent asked a question.
        """
        ctx = _ctx(
            partial_transcript="uhum",
            agent_response_text="Quer confirmar?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_uhum_after_statement_is_backchannel(self, strategy):
        """'uhum' after a statement is BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="uhum",
            agent_response_text="Vou explicar como funciona.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_aham_after_question_is_backchannel(self, strategy):
        """'aham' is a pure backchannel — always BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="aham",
            agent_response_text="Você entendeu?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_hum_after_question_is_backchannel(self, strategy):
        """'hum' is a pure backchannel — always BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="hum",
            agent_response_text="Posso continuar?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    # -----------------------------------------------------------------
    # Test 4: "nao" after question → INTERRUPT_IMMEDIATE
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_nao_after_question_is_interrupt(self, strategy):
        """'nao' after 'Deseja continuar?' must be INTERRUPT_IMMEDIATE.

        The user is giving a negative answer to a question.
        """
        ctx = _ctx(
            partial_transcript="nao",
            agent_response_text="Deseja continuar?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_nao_with_accent_after_question(self, strategy):
        """'não' (with accent) after question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="não",
            agent_response_text="Deseja continuar?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_nao_after_statement_is_backchannel(self, strategy):
        """'nao' after statement → BACKCHANNEL (disagreement acknowledgment)."""
        ctx = _ctx(
            partial_transcript="nao",
            agent_response_text="Isso não vai funcionar assim.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    # -----------------------------------------------------------------
    # Test 5: Uncertain zone (500-800ms) with question context
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_uncertain_zone_sim_after_question_is_interrupt(self, strategy):
        """In uncertain zone, 'sim' after question → INTERRUPT_IMMEDIATE.

        Even in the uncertain zone (500-800ms), context-dependent words
        answering a question should be treated as interruptions.
        """
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="Quer confirmar?",
            duration_ms=650.0,
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_uncertain_zone_sim_after_statement_is_backchannel(self, strategy):
        """In uncertain zone, 'sim' after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="Vou explicar o processo agora.",
            duration_ms=650.0,
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_uncertain_zone_uhum_after_question_is_backchannel(self, strategy):
        """In uncertain zone, 'uhum' (pure backchannel) → always BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="uhum",
            agent_response_text="Você entendeu?",
            duration_ms=650.0,
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_uncertain_zone_no_transcript_is_ignore(self, strategy):
        """In uncertain zone, no transcript → IGNORE (wait for more data)."""
        ctx = _ctx(
            partial_transcript="",
            agent_response_text="Quer confirmar?",
            duration_ms=650.0,
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.IGNORE

    @pytest.mark.asyncio
    async def test_uncertain_zone_nao_after_question_is_interrupt(self, strategy):
        """In uncertain zone, 'nao' after question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="nao",
            agent_response_text="Deseja continuar?",
            duration_ms=700.0,
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    # -----------------------------------------------------------------
    # Test 6: "ok" after statement → BACKCHANNEL
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_ok_after_statement_is_backchannel(self, strategy):
        """'ok' after a statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="ok",
            agent_response_text="Vou processar o seu pedido agora.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_certo_after_statement_is_backchannel(self, strategy):
        """'certo' after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="certo",
            agent_response_text="O prazo de entrega é de 3 dias úteis.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_entendi_after_statement_is_backchannel(self, strategy):
        """'entendi' after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="entendi",
            agent_response_text="O sistema funciona da seguinte forma.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    # -----------------------------------------------------------------
    # Test 7: "ok" after question → INTERRUPT_IMMEDIATE
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_ok_after_question_is_interrupt(self, strategy):
        """'ok' after a question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="ok",
            agent_response_text="Posso prosseguir com a operação?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_certo_after_question_is_interrupt(self, strategy):
        """'certo' after a question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="certo",
            agent_response_text="Ficou claro?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_claro_after_question_is_interrupt(self, strategy):
        """'claro' after a question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="claro",
            agent_response_text="Você pode fazer isso?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    # -----------------------------------------------------------------
    # Test 8: Backward compatibility — empty agent_response_text
    # -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_agent_text_sim_is_backchannel(self, strategy):
        """Empty agent_response_text: 'sim' → BACKCHANNEL (no question detected).

        Backward compatibility: when no agent text is available, the strategy
        cannot detect a question, so context-dependent words default to
        backchannel classification.
        """
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_empty_agent_text_nao_is_backchannel(self, strategy):
        """Empty agent_response_text: 'nao' → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="nao",
            agent_response_text="",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_empty_agent_text_ok_is_backchannel(self, strategy):
        """Empty agent_response_text: 'ok' → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="ok",
            agent_response_text="",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_empty_agent_text_uhum_is_backchannel(self, strategy):
        """Empty agent_response_text: 'uhum' → BACKCHANNEL (pure backchannel)."""
        ctx = _ctx(
            partial_transcript="uhum",
            agent_response_text="",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL


# =============================================================================
# English context-aware tests
# =============================================================================


class TestContextAwareBackchannelEN:
    """Test context-aware backchannel detection for English."""

    @pytest.fixture
    def strategy(self):
        return BackchannelAwareInterruption(
            backchannel_max_ms=500,
            interruption_min_ms=800,
            language="en",
        )

    @pytest.mark.asyncio
    async def test_yes_after_question_is_interrupt(self, strategy):
        """'yes' after question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="yes",
            agent_response_text="Would you like to continue?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_yes_after_statement_is_backchannel(self, strategy):
        """'yes' after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="yes",
            agent_response_text="I will explain how the system works.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_yeah_after_question_is_interrupt(self, strategy):
        """'yeah' after question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="yeah",
            agent_response_text="Do you want me to proceed?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_yeah_after_statement_is_backchannel(self, strategy):
        """'yeah' after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="yeah",
            agent_response_text="The process involves several steps.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_ok_after_question_is_interrupt(self, strategy):
        """'ok' after question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="ok",
            agent_response_text="Should I go ahead?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_ok_after_statement_is_backchannel(self, strategy):
        """'ok' after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="ok",
            agent_response_text="I will now start the process.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_sure_after_question_is_interrupt(self, strategy):
        """'sure' after question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="sure",
            agent_response_text="Can I help you with that?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_uh_huh_after_question_is_backchannel(self, strategy):
        """'uh huh' (pure backchannel) → always BACKCHANNEL, even after question."""
        ctx = _ctx(
            partial_transcript="uh huh",
            agent_response_text="Do you understand?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_mhm_after_question_is_backchannel(self, strategy):
        """'mhm' (pure backchannel) → always BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="mhm",
            agent_response_text="Is that clear?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_empty_agent_text_yes_is_backchannel(self, strategy):
        """Empty agent_response_text: 'yes' → BACKCHANNEL (backward compat)."""
        ctx = _ctx(
            partial_transcript="yes",
            agent_response_text="",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL

    @pytest.mark.asyncio
    async def test_uncertain_zone_yes_after_question(self, strategy):
        """Uncertain zone: 'yes' after question → INTERRUPT_IMMEDIATE."""
        ctx = _ctx(
            partial_transcript="yes",
            agent_response_text="Do you agree?",
            duration_ms=650.0,
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE

    @pytest.mark.asyncio
    async def test_uncertain_zone_uh_huh_is_backchannel(self, strategy):
        """Uncertain zone: 'uh huh' (pure) → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript="uh huh",
            agent_response_text="Should I continue?",
            duration_ms=650.0,
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL


# =============================================================================
# Question detection edge cases
# =============================================================================


class TestQuestionDetectionEdgeCases:
    """Test edge cases for _agent_asked_question detection."""

    @pytest.fixture
    def strategy(self):
        return BackchannelAwareInterruption(language="pt")

    def test_question_mark_at_end(self, strategy):
        """Standard question with '?' at the end."""
        assert strategy._agent_asked_question("Quer continuar?") is True

    def test_no_question_mark(self, strategy):
        """Statement without '?' → not a question."""
        assert strategy._agent_asked_question("Vou continuar.") is False

    def test_question_mark_with_trailing_whitespace(self, strategy):
        """Question mark with trailing spaces."""
        assert strategy._agent_asked_question("Quer continuar?  ") is True

    def test_empty_string(self, strategy):
        """Empty string → not a question."""
        assert strategy._agent_asked_question("") is False

    def test_only_whitespace(self, strategy):
        """Whitespace-only string → not a question."""
        assert strategy._agent_asked_question("   ") is False

    def test_exclamation_mark(self, strategy):
        """Exclamation mark → not a question."""
        assert strategy._agent_asked_question("Que legal!") is False

    def test_period_at_end(self, strategy):
        """Period at end → not a question."""
        assert strategy._agent_asked_question("O prazo é 3 dias.") is False

    def test_multi_sentence_last_is_question(self, strategy):
        """Multiple sentences, last ends with '?'."""
        assert strategy._agent_asked_question(
            "Encontrei 3 resultados. Quer ver todos?"
        ) is True

    def test_multi_sentence_last_is_statement(self, strategy):
        """Multiple sentences, last is a statement even if earlier has '?'."""
        assert strategy._agent_asked_question(
            "Quer ver todos? Vou mostrar agora."
        ) is False

    def test_question_in_middle_not_at_end(self, strategy):
        """'?' in the middle but not at the very end of the text."""
        assert strategy._agent_asked_question(
            "Como vai? Tudo bem, vou ajudar"
        ) is False


# =============================================================================
# Internal method tests
# =============================================================================


class TestBackchannelTextClassification:
    """Test _is_backchannel_text and _is_context_response methods directly."""

    @pytest.fixture
    def strategy_pt(self):
        return BackchannelAwareInterruption(language="pt")

    @pytest.fixture
    def strategy_en(self):
        return BackchannelAwareInterruption(language="en")

    # --- Pure backchannels (always True regardless of context) ---

    def test_pure_backchannel_uhum_no_context(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("uhum") is True

    def test_pure_backchannel_uhum_with_question_context(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("uhum", "Quer continuar?") is True

    def test_pure_backchannel_aham_no_context(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("aham") is True

    def test_pure_backchannel_aham_with_question_context(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("aham", "Ficou claro?") is True

    # --- Context-dependent words: backchannel only without question ---

    def test_context_dependent_sim_no_question(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("sim", "Vou explicar.") is True

    def test_context_dependent_sim_with_question(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("sim", "Quer confirmar?") is False

    def test_context_dependent_ok_no_question(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("ok", "Processando agora.") is True

    def test_context_dependent_ok_with_question(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("ok", "Posso continuar?") is False

    def test_context_dependent_nao_no_question(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("nao", "Isso é assim.") is True

    def test_context_dependent_nao_with_question(self, strategy_pt):
        assert strategy_pt._is_backchannel_text("nao", "Deseja continuar?") is False

    # --- _is_context_response (True only for context-dep word + question) ---

    def test_is_context_response_sim_with_question(self, strategy_pt):
        assert strategy_pt._is_context_response("sim", "Quer confirmar?") is True

    def test_is_context_response_sim_without_question(self, strategy_pt):
        assert strategy_pt._is_context_response("sim", "Vou explicar.") is False

    def test_is_context_response_uhum_with_question(self, strategy_pt):
        """Pure backchannel 'uhum' is NOT in _context_dependent set."""
        assert strategy_pt._is_context_response("uhum", "Quer continuar?") is False

    def test_is_context_response_empty_text(self, strategy_pt):
        assert strategy_pt._is_context_response("", "Quer continuar?") is False

    def test_is_context_response_empty_agent_text(self, strategy_pt):
        assert strategy_pt._is_context_response("sim", "") is False

    # --- English context-dependent ---

    def test_en_context_dependent_yes_no_question(self, strategy_en):
        assert strategy_en._is_backchannel_text("yes", "I will explain.") is True

    def test_en_context_dependent_yes_with_question(self, strategy_en):
        assert strategy_en._is_backchannel_text("yes", "Do you agree?") is False

    def test_en_pure_backchannel_mhm_with_question(self, strategy_en):
        assert strategy_en._is_backchannel_text("mhm", "Is that clear?") is True


# =============================================================================
# Counter tracking with context awareness
# =============================================================================


class TestCounterTrackingWithContext:
    """Verify that backchannel/interruption counters update correctly
    based on context-aware decisions."""

    @pytest.fixture
    def strategy(self):
        return BackchannelAwareInterruption(language="pt")

    @pytest.mark.asyncio
    async def test_answer_to_question_increments_interruption_count(self, strategy):
        """'sim' answering a question → interruption_count increments."""
        assert strategy.interruption_count == 0
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="Quer confirmar?",
        )
        await strategy.decide(ctx)
        assert strategy.interruption_count == 1
        assert strategy.backchannel_count == 0

    @pytest.mark.asyncio
    async def test_backchannel_after_statement_increments_backchannel_count(self, strategy):
        """'sim' after statement → backchannel_count increments."""
        assert strategy.backchannel_count == 0
        ctx = _ctx(
            partial_transcript="sim",
            agent_response_text="Vou explicar agora.",
        )
        await strategy.decide(ctx)
        assert strategy.backchannel_count == 1
        assert strategy.interruption_count == 0

    @pytest.mark.asyncio
    async def test_mixed_sequence_counter_accuracy(self, strategy):
        """Multiple decisions should accumulate counters correctly."""
        # 1. Statement + "sim" → backchannel
        await strategy.decide(_ctx(
            partial_transcript="sim",
            agent_response_text="Explicando agora.",
        ))
        # 2. Question + "sim" → interrupt
        await strategy.decide(_ctx(
            partial_transcript="sim",
            agent_response_text="Quer confirmar?",
        ))
        # 3. Statement + "uhum" → backchannel (pure)
        await strategy.decide(_ctx(
            partial_transcript="uhum",
            agent_response_text="Continuando a explicação.",
        ))
        # 4. Question + "nao" → interrupt
        await strategy.decide(_ctx(
            partial_transcript="nao",
            agent_response_text="Deseja cancelar?",
        ))

        assert strategy.backchannel_count == 2
        assert strategy.interruption_count == 2

    @pytest.mark.asyncio
    async def test_reset_clears_all_counters(self, strategy):
        """reset() should clear both counters."""
        await strategy.decide(_ctx(
            partial_transcript="sim",
            agent_response_text="Quer?",
        ))
        await strategy.decide(_ctx(
            partial_transcript="uhum",
            agent_response_text="Explicando.",
        ))
        assert strategy.interruption_count == 1
        assert strategy.backchannel_count == 1

        strategy.reset()
        assert strategy.interruption_count == 0
        assert strategy.backchannel_count == 0


# =============================================================================
# All context-dependent words — comprehensive coverage (PT)
# =============================================================================


class TestAllContextDependentWordsPT:
    """Test every word in _CONTEXT_DEPENDENT_PT against question/statement."""

    @pytest.fixture
    def strategy(self):
        return BackchannelAwareInterruption(language="pt")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", [
        "sim", "nao", "não", "ok", "tá", "certo", "entendi", "sei",
        "é", "pois", "isso", "exato", "verdade", "claro",
    ])
    async def test_context_word_after_question_is_interrupt(self, strategy, word):
        """Every context-dependent word after a question → INTERRUPT."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="Você confirma?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE, (
            f"Expected INTERRUPT_IMMEDIATE for '{word}' after question, got {decision}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", [
        "sim", "nao", "não", "ok", "tá", "certo", "entendi", "sei",
        "é", "pois", "isso", "exato", "verdade", "claro",
    ])
    async def test_context_word_after_statement_is_backchannel(self, strategy, word):
        """Every context-dependent word after a statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="Vou processar o seu pedido agora.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL, (
            f"Expected BACKCHANNEL for '{word}' after statement, got {decision}"
        )


# =============================================================================
# All context-dependent words — comprehensive coverage (EN)
# =============================================================================


class TestAllContextDependentWordsEN:
    """Test every word in _CONTEXT_DEPENDENT_EN against question/statement."""

    @pytest.fixture
    def strategy(self):
        return BackchannelAwareInterruption(language="en")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", [
        "yeah", "yep", "yes", "ok", "okay", "right", "sure",
        "exactly", "true", "got it", "i see",
    ])
    async def test_context_word_after_question_is_interrupt(self, strategy, word):
        """Every EN context-dependent word after a question → INTERRUPT."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="Do you want to proceed?",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.INTERRUPT_IMMEDIATE, (
            f"Expected INTERRUPT_IMMEDIATE for '{word}' after question, got {decision}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", [
        "yeah", "yep", "yes", "ok", "okay", "right", "sure",
        "exactly", "true", "got it", "i see",
    ])
    async def test_context_word_after_statement_is_backchannel(self, strategy, word):
        """Every EN context-dependent word after a statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="I will now explain the process.",
        )
        decision = await strategy.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL, (
            f"Expected BACKCHANNEL for '{word}' after statement, got {decision}"
        )


# =============================================================================
# All pure backchannel words — always BACKCHANNEL regardless of context
# =============================================================================


class TestAllPureBackchannelWords:
    """Verify pure backchannel words are ALWAYS classified as BACKCHANNEL."""

    @pytest.fixture
    def strategy_pt(self):
        return BackchannelAwareInterruption(language="pt")

    @pytest.fixture
    def strategy_en(self):
        return BackchannelAwareInterruption(language="en")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", ["uhum", "aham", "hum", "hm", "ahan"])
    async def test_pure_pt_after_question(self, strategy_pt, word):
        """PT pure backchannel after question → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="Quer continuar?",
        )
        decision = await strategy_pt.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL, (
            f"Expected BACKCHANNEL for pure PT '{word}' after question, got {decision}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", ["uhum", "aham", "hum", "hm", "ahan"])
    async def test_pure_pt_after_statement(self, strategy_pt, word):
        """PT pure backchannel after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="Vou explicar agora.",
        )
        decision = await strategy_pt.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL, (
            f"Expected BACKCHANNEL for pure PT '{word}' after statement, got {decision}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", ["uh huh", "uh-huh", "uhum", "mhm", "hmm", "hm"])
    async def test_pure_en_after_question(self, strategy_en, word):
        """EN pure backchannel after question → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="Do you understand?",
        )
        decision = await strategy_en.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL, (
            f"Expected BACKCHANNEL for pure EN '{word}' after question, got {decision}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", ["uh huh", "uh-huh", "uhum", "mhm", "hmm", "hm"])
    async def test_pure_en_after_statement(self, strategy_en, word):
        """EN pure backchannel after statement → BACKCHANNEL."""
        ctx = _ctx(
            partial_transcript=word,
            agent_response_text="I will explain now.",
        )
        decision = await strategy_en.decide(ctx)
        assert decision == InterruptionDecision.BACKCHANNEL, (
            f"Expected BACKCHANNEL for pure EN '{word}' after statement, got {decision}"
        )

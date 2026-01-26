"""Tests for session inactivity timeout configuration and event types."""

import pytest

from voice_pipeline.core.config import PipelineConfig
from voice_pipeline.core.events import PipelineEventType


# ---------------------------------------------------------------------------
# PipelineConfig: inactivity fields exist with correct defaults
# ---------------------------------------------------------------------------


class TestInactivityConfigDefaults:
    """Verify that PipelineConfig has the inactivity fields with expected defaults."""

    def test_inactivity_timeout_ms_default(self):
        config = PipelineConfig()
        assert config.inactivity_timeout_ms == 15000

    def test_inactivity_action_default(self):
        config = PipelineConfig()
        assert config.inactivity_action == "reprompt"

    def test_reprompt_text_default_is_none(self):
        config = PipelineConfig()
        assert config.reprompt_text is None

    def test_max_reprompt_count_default(self):
        config = PipelineConfig()
        assert config.max_reprompt_count == 2


# ---------------------------------------------------------------------------
# PipelineConfig: field types
# ---------------------------------------------------------------------------


class TestInactivityConfigFieldTypes:
    """Verify that the inactivity-related fields have the correct types."""

    def test_inactivity_timeout_ms_is_int(self):
        config = PipelineConfig()
        assert isinstance(config.inactivity_timeout_ms, int)

    def test_inactivity_action_is_str(self):
        config = PipelineConfig()
        assert isinstance(config.inactivity_action, str)

    def test_reprompt_text_is_none_or_str(self):
        config = PipelineConfig()
        assert config.reprompt_text is None or isinstance(config.reprompt_text, str)

    def test_max_reprompt_count_is_int(self):
        config = PipelineConfig()
        assert isinstance(config.max_reprompt_count, int)


# ---------------------------------------------------------------------------
# PipelineConfig: custom values
# ---------------------------------------------------------------------------


class TestInactivityConfigCustomValues:
    """Ensure custom values can be set on the inactivity config fields."""

    def test_custom_inactivity_timeout_ms(self):
        config = PipelineConfig(inactivity_timeout_ms=30000)
        assert config.inactivity_timeout_ms == 30000

    def test_custom_inactivity_action_disconnect(self):
        config = PipelineConfig(inactivity_action="disconnect")
        assert config.inactivity_action == "disconnect"

    def test_custom_inactivity_action_event_only(self):
        config = PipelineConfig(inactivity_action="event_only")
        assert config.inactivity_action == "event_only"

    def test_custom_reprompt_text(self):
        config = PipelineConfig(reprompt_text="Are you still there?")
        assert config.reprompt_text == "Are you still there?"

    def test_custom_max_reprompt_count(self):
        config = PipelineConfig(max_reprompt_count=5)
        assert config.max_reprompt_count == 5

    def test_custom_reprompt_text_portuguese(self):
        config = PipelineConfig(reprompt_text="Voce ainda esta ai?")
        assert config.reprompt_text == "Voce ainda esta ai?"

    def test_zero_timeout_disables_inactivity(self):
        config = PipelineConfig(inactivity_timeout_ms=0)
        assert config.inactivity_timeout_ms == 0

    def test_zero_max_reprompt_goes_straight_to_disconnect(self):
        config = PipelineConfig(max_reprompt_count=0)
        assert config.max_reprompt_count == 0


# ---------------------------------------------------------------------------
# PipelineEventType: inactivity events exist
# ---------------------------------------------------------------------------


class TestInactivityEventTypes:
    """Verify that PipelineEventType includes the inactivity events."""

    def test_inactivity_detected_exists(self):
        assert hasattr(PipelineEventType, "INACTIVITY_DETECTED")

    def test_inactivity_reprompt_exists(self):
        assert hasattr(PipelineEventType, "INACTIVITY_REPROMPT")

    def test_inactivity_disconnect_exists(self):
        assert hasattr(PipelineEventType, "INACTIVITY_DISCONNECT")

    def test_inactivity_detected_value(self):
        assert PipelineEventType.INACTIVITY_DETECTED.value == "inactivity_detected"

    def test_inactivity_reprompt_value(self):
        assert PipelineEventType.INACTIVITY_REPROMPT.value == "inactivity_reprompt"

    def test_inactivity_disconnect_value(self):
        assert PipelineEventType.INACTIVITY_DISCONNECT.value == "inactivity_disconnect"

    def test_inactivity_events_are_enum_members(self):
        assert isinstance(PipelineEventType.INACTIVITY_DETECTED, PipelineEventType)
        assert isinstance(PipelineEventType.INACTIVITY_REPROMPT, PipelineEventType)
        assert isinstance(PipelineEventType.INACTIVITY_DISCONNECT, PipelineEventType)

    def test_inactivity_events_are_unique(self):
        values = {
            PipelineEventType.INACTIVITY_DETECTED.value,
            PipelineEventType.INACTIVITY_REPROMPT.value,
            PipelineEventType.INACTIVITY_DISCONNECT.value,
        }
        assert len(values) == 3, "Inactivity event values must be unique"

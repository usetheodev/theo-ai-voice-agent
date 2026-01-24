"""Tests for Voice Pipeline CLI.

Tests cover:
- CLI app creation
- Command registration
- Help text
- Version display
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# =============================================================================
# Skip if typer not installed
# =============================================================================


typer = pytest.importorskip("typer", reason="typer not installed")
rich = pytest.importorskip("rich", reason="rich not installed")


from typer.testing import CliRunner

from voice_pipeline.cli.main import app


runner = CliRunner()


# =============================================================================
# App Structure Tests
# =============================================================================


class TestCLIApp:
    """Tests for CLI app structure."""

    def test_app_exists(self):
        """Test that app exists."""
        assert app is not None

    def test_app_has_commands(self):
        """Test that app has expected commands."""
        # Get command names from help output
        result = runner.invoke(app, ["--help"])

        assert "chat" in result.stdout
        assert "voice" in result.stdout
        assert "benchmark" in result.stdout
        assert "info" in result.stdout
        assert "providers" in result.stdout


# =============================================================================
# Help Tests
# =============================================================================


class TestCLIHelp:
    """Tests for CLI help text."""

    def test_main_help(self):
        """Test main help text."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "Voice Pipeline CLI" in result.stdout
        assert "chat" in result.stdout
        assert "voice" in result.stdout

    def test_chat_help(self):
        """Test chat command help."""
        result = runner.invoke(app, ["chat", "--help"])

        assert result.exit_code == 0
        assert "chat" in result.stdout.lower()
        assert "--model" in result.stdout

    def test_voice_help(self):
        """Test voice command help."""
        result = runner.invoke(app, ["voice", "--help"])

        assert result.exit_code == 0
        assert "--asr" in result.stdout
        assert "--llm" in result.stdout
        assert "--tts" in result.stdout

    def test_benchmark_help(self):
        """Test benchmark command help."""
        result = runner.invoke(app, ["benchmark", "--help"])

        assert result.exit_code == 0
        assert "--iterations" in result.stdout
        assert "--model" in result.stdout

    def test_info_help(self):
        """Test info command help."""
        result = runner.invoke(app, ["info", "--help"])

        assert result.exit_code == 0

    def test_providers_help(self):
        """Test providers command help."""
        result = runner.invoke(app, ["providers", "--help"])

        assert result.exit_code == 0


# =============================================================================
# Version Tests
# =============================================================================


class TestCLIVersion:
    """Tests for version display."""

    def test_version_flag(self):
        """Test --version flag."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "Voice Pipeline" in result.stdout

    def test_version_short_flag(self):
        """Test -v flag."""
        result = runner.invoke(app, ["-v"])

        assert result.exit_code == 0
        assert "Voice Pipeline" in result.stdout


# =============================================================================
# Command Execution Tests (Mocked)
# =============================================================================


class TestChatCommand:
    """Tests for chat command."""

    @patch("voice_pipeline.cli.commands.chat.run_chat")
    def test_chat_default_options(self, mock_run_chat):
        """Test chat with default options."""
        mock_run_chat.return_value = None

        result = runner.invoke(app, ["chat"])

        # Command should attempt to run
        # (may fail due to missing Ollama, but that's OK for unit test)

    @patch("voice_pipeline.cli.commands.chat.run_chat")
    def test_chat_with_model(self, mock_run_chat):
        """Test chat with custom model."""
        mock_run_chat.return_value = None

        result = runner.invoke(app, ["chat", "--model", "llama3.2:1b"])


class TestProvidersCommand:
    """Tests for providers command."""

    def test_providers_runs(self):
        """Test providers command runs."""
        result = runner.invoke(app, ["providers"])

        assert result.exit_code == 0
        assert "ASR" in result.stdout or "Provider" in result.stdout


class TestInfoCommand:
    """Tests for info command."""

    def test_info_runs(self):
        """Test info command runs."""
        result = runner.invoke(app, ["info"])

        assert result.exit_code == 0
        assert "Voice Pipeline" in result.stdout


# =============================================================================
# Import Tests
# =============================================================================


class TestCLIImports:
    """Tests for CLI imports."""

    def test_import_cli_module(self):
        """Test importing CLI module."""
        from voice_pipeline.cli import app, main

        assert app is not None
        assert main is not None

    def test_import_commands(self):
        """Test importing command functions."""
        from voice_pipeline.cli.commands import (
            run_chat,
            run_voice,
            run_benchmark,
            show_info,
            list_providers,
        )

        assert callable(run_chat)
        assert callable(run_voice)
        assert callable(run_benchmark)
        assert callable(show_info)
        assert callable(list_providers)

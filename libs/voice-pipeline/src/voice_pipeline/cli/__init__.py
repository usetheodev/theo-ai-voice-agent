"""Voice Pipeline CLI.

Command-line interface for testing and developing voice agents.

Usage:
    voice-pipeline chat          # Text-based chat
    voice-pipeline voice         # Voice conversation (microphone)
    voice-pipeline benchmark     # Measure latency metrics
    voice-pipeline info          # Show system info
"""

from voice_pipeline.cli.main import app, main

__all__ = ["app", "main"]

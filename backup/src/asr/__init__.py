"""
Automatic Speech Recognition (ASR) package

Modules:
- whisper: Whisper.cpp integration for speech-to-text
"""

from .whisper import WhisperASR

__all__ = ['WhisperASR']

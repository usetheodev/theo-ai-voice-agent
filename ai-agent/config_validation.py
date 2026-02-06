"""
Validação de configuração com Pydantic.

Valida todas as configurações no startup e falha com mensagem clara
se alguma configuração for inválida.
"""

import logging
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger("ai-agent.config-validation")


class AudioSettings(BaseModel):
    """Validação de configurações de áudio."""
    sample_rate: int
    channels: int
    sample_width: int
    frame_duration_ms: int
    vad_aggressiveness: int
    silence_threshold_ms: int
    min_speech_ms: int
    energy_threshold: int
    max_buffer_seconds: int
    chunk_size_bytes: int
    max_pending_audio_ms: int

    @field_validator('sample_rate')
    @classmethod
    def validate_sample_rate(cls, v):
        valid_rates = [8000, 16000, 24000, 48000]
        if v not in valid_rates:
            raise ValueError(f"sample_rate deve ser um de {valid_rates}, recebeu: {v}")
        return v

    @field_validator('vad_aggressiveness')
    @classmethod
    def validate_vad_aggressiveness(cls, v):
        if v < 0 or v > 3:
            raise ValueError(f"vad_aggressiveness deve ser entre 0 e 3, recebeu: {v}")
        return v

    @field_validator('silence_threshold_ms')
    @classmethod
    def validate_silence_threshold(cls, v):
        if v < 100 or v > 5000:
            raise ValueError(f"silence_threshold_ms deve ser entre 100 e 5000, recebeu: {v}")
        return v

    @field_validator('frame_duration_ms')
    @classmethod
    def validate_frame_duration(cls, v):
        valid_durations = [10, 20, 30]
        if v not in valid_durations:
            raise ValueError(f"frame_duration_ms deve ser um de {valid_durations}, recebeu: {v}")
        return v


class STTSettings(BaseModel):
    """Validação de configurações STT."""
    provider: str
    model: str
    language: str
    beam_size: int
    fallback_provider: str = ""

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v):
        valid = ['faster-whisper', 'whisper', 'openai', 'qwen3-asr']
        if v not in valid:
            raise ValueError(f"STT provider deve ser um de {valid}, recebeu: '{v}'")
        return v

    @field_validator('fallback_provider')
    @classmethod
    def validate_fallback(cls, v):
        if v:
            valid = ['faster-whisper', 'whisper', 'openai', 'qwen3-asr']
            if v not in valid:
                raise ValueError(f"STT fallback_provider deve ser um de {valid} ou '', recebeu: '{v}'")
        return v


class LLMSettings(BaseModel):
    """Validação de configurações LLM."""
    provider: str
    max_tokens: int
    temperature: float
    timeout: float
    max_history_turns: int

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v):
        valid = ['anthropic', 'openai', 'local', 'mock']
        if v not in valid:
            raise ValueError(f"LLM provider deve ser um de {valid}, recebeu: '{v}'")
        return v

    @field_validator('temperature')
    @classmethod
    def validate_temperature(cls, v):
        if v < 0.0 or v > 2.0:
            raise ValueError(f"LLM temperature deve ser entre 0.0 e 2.0, recebeu: {v}")
        return v

    @field_validator('max_tokens')
    @classmethod
    def validate_max_tokens(cls, v):
        if v < 1 or v > 100000:
            raise ValueError(f"LLM max_tokens deve ser entre 1 e 100000, recebeu: {v}")
        return v


class TTSSettings(BaseModel):
    """Validação de configurações TTS."""
    provider: str
    speed: float
    fallback_provider: str = ""

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v):
        valid = ['kokoro', 'gtts', 'openai', 'mock']
        if v not in valid:
            raise ValueError(f"TTS provider deve ser um de {valid}, recebeu: '{v}'")
        return v

    @field_validator('speed')
    @classmethod
    def validate_speed(cls, v):
        if v < 0.5 or v > 2.0:
            raise ValueError(f"TTS speed deve ser entre 0.5 e 2.0, recebeu: {v}")
        return v

    @field_validator('fallback_provider')
    @classmethod
    def validate_fallback(cls, v):
        if v:
            valid = ['kokoro', 'gtts', 'openai', 'mock']
            if v not in valid:
                raise ValueError(f"TTS fallback_provider deve ser um de {valid} ou '', recebeu: '{v}'")
        return v


class PipelineSettings(BaseModel):
    """Validação de configurações do pipeline."""
    sentence_queue_size: int
    stt_timeout: float
    tts_timeout: float
    sentence_timeout: float

    @field_validator('sentence_queue_size')
    @classmethod
    def validate_queue_size(cls, v):
        if v < 1 or v > 100:
            raise ValueError(f"sentence_queue_size deve ser entre 1 e 100, recebeu: {v}")
        return v


class EscalationSettings(BaseModel):
    """Validação de configurações de escalação."""
    max_unresolved_interactions: int
    default_transfer_target: str

    @field_validator('max_unresolved_interactions')
    @classmethod
    def validate_max_interactions(cls, v):
        if v < 0:
            raise ValueError(f"max_unresolved_interactions deve ser >= 0, recebeu: {v}")
        return v


def validate_config():
    """Valida todas as configurações no startup.

    Falha com mensagem clara se alguma configuração for inválida.
    Retorna True se todas as validações passaram.
    """
    from config import (
        AUDIO_CONFIG, STT_CONFIG, LLM_CONFIG, TTS_CONFIG,
        PIPELINE_CONFIG, ESCALATION_CONFIG,
    )

    errors = []

    try:
        AudioSettings(
            sample_rate=AUDIO_CONFIG["sample_rate"],
            channels=AUDIO_CONFIG["channels"],
            sample_width=AUDIO_CONFIG["sample_width"],
            frame_duration_ms=AUDIO_CONFIG["frame_duration_ms"],
            vad_aggressiveness=AUDIO_CONFIG["vad_aggressiveness"],
            silence_threshold_ms=AUDIO_CONFIG["silence_threshold_ms"],
            min_speech_ms=AUDIO_CONFIG["min_speech_ms"],
            energy_threshold=AUDIO_CONFIG["energy_threshold"],
            max_buffer_seconds=AUDIO_CONFIG["max_buffer_seconds"],
            chunk_size_bytes=AUDIO_CONFIG["chunk_size_bytes"],
            max_pending_audio_ms=AUDIO_CONFIG["max_pending_audio_ms"],
        )
    except (ValidationError, KeyError) as e:
        errors.append(f"[Audio] {e}")

    try:
        STTSettings(
            provider=STT_CONFIG["provider"],
            model=STT_CONFIG["model"],
            language=STT_CONFIG["language"],
            beam_size=STT_CONFIG["beam_size"],
            fallback_provider=STT_CONFIG.get("fallback_provider", ""),
        )
    except (ValidationError, KeyError) as e:
        errors.append(f"[STT] {e}")

    try:
        LLMSettings(
            provider=LLM_CONFIG["provider"],
            max_tokens=LLM_CONFIG["max_tokens"],
            temperature=LLM_CONFIG["temperature"],
            timeout=LLM_CONFIG["timeout"],
            max_history_turns=LLM_CONFIG["max_history_turns"],
        )
    except (ValidationError, KeyError) as e:
        errors.append(f"[LLM] {e}")

    try:
        TTSSettings(
            provider=TTS_CONFIG["provider"],
            speed=TTS_CONFIG["speed"],
            fallback_provider=TTS_CONFIG.get("fallback_provider", ""),
        )
    except (ValidationError, KeyError) as e:
        errors.append(f"[TTS] {e}")

    try:
        PipelineSettings(
            sentence_queue_size=PIPELINE_CONFIG["sentence_queue_size"],
            stt_timeout=PIPELINE_CONFIG["stt_timeout"],
            tts_timeout=PIPELINE_CONFIG["tts_timeout"],
            sentence_timeout=PIPELINE_CONFIG["sentence_timeout"],
        )
    except (ValidationError, KeyError) as e:
        errors.append(f"[Pipeline] {e}")

    try:
        EscalationSettings(
            max_unresolved_interactions=ESCALATION_CONFIG["max_unresolved_interactions"],
            default_transfer_target=ESCALATION_CONFIG["default_transfer_target"],
        )
    except (ValidationError, KeyError) as e:
        errors.append(f"[Escalation] {e}")

    if errors:
        msg = "Erros de configuração encontrados:\n" + "\n".join(f"  {e}" for e in errors)
        logger.error(msg)
        raise ValueError(msg)

    logger.info("Todas as configurações validadas com sucesso")
    return True

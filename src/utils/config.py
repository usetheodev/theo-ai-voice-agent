"""
Configuration management for AI Voice Agent
"""

import os
from pathlib import Path
from typing import Dict, Any


def load_config() -> Dict[str, Any]:
    """
    Load configuration from environment variables

    Returns:
        Dictionary with configuration values
    """

    config = {
        # Application
        'app_env': os.getenv('APP_ENV', 'development'),
        'log_level': os.getenv('LOG_LEVEL', 'INFO'),

        # RTP
        'rtp_host': os.getenv('RTP_HOST', '0.0.0.0'),
        'rtp_port': int(os.getenv('RTP_PORT', '5080')),
        'rtp_buffer_size': int(os.getenv('RTP_BUFFER_SIZE', '4194304')),  # 4MB

        # Models
        'whisper_model': os.getenv('WHISPER_MODEL', 'base'),
        'llm_model': os.getenv('LLM_MODEL', 'phi-3-mini'),
        'tts_voice': os.getenv('TTS_VOICE', 'pt_BR-faber-medium'),

        # Paths
        'models_dir': Path('/app/models'),
        'logs_dir': Path('/app/logs'),
    }

    return config

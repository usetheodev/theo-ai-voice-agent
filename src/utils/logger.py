"""
Logging configuration for AI Voice Agent
"""

import logging
import os
import sys
from pathlib import Path


def setup_logger(name: str = "ai-voice-agent") -> logging.Logger:
    """
    Setup structured logger with appropriate handlers

    Args:
        name: Logger name

    Returns:
        Configured logger instance
    """

    # Get log level from environment
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Format
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    return logger

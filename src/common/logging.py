"""
Structured Logging

Uses structlog for structured logging with context
"""

import sys
import logging
import structlog


def configure_logging(level: str = "INFO"):
    """
    Configure structured logging

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    # Map string level to logging constant
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """
    Get a logger instance

    Args:
        name: Logger name (usually module name)

    Returns:
        Logger instance
    """
    return structlog.get_logger(name)

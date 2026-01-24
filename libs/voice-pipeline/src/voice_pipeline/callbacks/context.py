"""
Context management for Voice Pipeline callbacks.

This module provides request-scoped callback management using
Python's contextvars, allowing callbacks to be automatically
propagated through async call chains without explicit passing.
"""

import contextvars
from contextlib import asynccontextmanager
from typing import Any, Optional

from voice_pipeline.callbacks.base import (
    CallbackManager,
    RunContext,
    VoiceCallbackHandler,
)

# Context variable for the current callback manager
_callback_manager_var: contextvars.ContextVar[Optional[CallbackManager]] = (
    contextvars.ContextVar("callback_manager", default=None)
)

# Context variable for the current run context
_run_context_var: contextvars.ContextVar[Optional[RunContext]] = (
    contextvars.ContextVar("run_context", default=None)
)


def get_callback_manager() -> Optional[CallbackManager]:
    """
    Get the current callback manager from context.

    Returns:
        The current CallbackManager or None if not set.
    """
    return _callback_manager_var.get()


def get_run_context() -> Optional[RunContext]:
    """
    Get the current run context from context.

    Returns:
        The current RunContext or None if not set.
    """
    return _run_context_var.get()


def set_callback_manager(manager: Optional[CallbackManager]) -> None:
    """
    Set the callback manager in the current context.

    Args:
        manager: The CallbackManager to set, or None to clear.
    """
    _callback_manager_var.set(manager)


def set_run_context(ctx: Optional[RunContext]) -> None:
    """
    Set the run context in the current context.

    Args:
        ctx: The RunContext to set, or None to clear.
    """
    _run_context_var.set(ctx)


@asynccontextmanager
async def run_with_callbacks(
    handlers: list[VoiceCallbackHandler],
    run_name: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
    parent_run_id: Optional[str] = None,
    run_in_background: bool = True,
):
    """
    Context manager for running with callbacks.

    This sets up a CallbackManager and RunContext that are
    automatically available throughout the async call chain.

    Usage:
        async with run_with_callbacks([MetricsHandler(), LoggingHandler()]) as ctx:
            result = await chain.ainvoke(audio)
            # ctx.run_id contains the unique run ID
            # Metrics and logs are automatically collected

    Args:
        handlers: List of callback handlers to use.
        run_name: Human-readable name for this run.
        metadata: Additional metadata to attach.
        tags: Tags for categorization.
        parent_run_id: Parent run ID for nested runs.
        run_in_background: If True, callbacks run in background tasks.

    Yields:
        RunContext for this execution.
    """
    # Check for existing parent context
    existing_ctx = get_run_context()
    if existing_ctx and parent_run_id is None:
        parent_run_id = existing_ctx.run_id

    # Create manager and context
    manager = CallbackManager(handlers, run_in_background=run_in_background)
    ctx = manager.create_context(
        run_name=run_name,
        metadata=metadata,
        tags=tags,
        parent_run_id=parent_run_id,
    )

    # Store old values
    old_manager = _callback_manager_var.get()
    old_context = _run_context_var.get()

    # Set new values
    _callback_manager_var.set(manager)
    _run_context_var.set(ctx)

    error: Optional[Exception] = None

    try:
        # Notify start
        await manager.on_pipeline_start(ctx)

        yield ctx

    except Exception as e:
        error = e
        await manager.on_pipeline_error(ctx, e)
        raise

    finally:
        if error is None:
            await manager.on_pipeline_end(ctx)

        # Wait for background callbacks to complete
        await manager.wait_for_callbacks()

        # Restore old values
        _callback_manager_var.set(old_manager)
        _run_context_var.set(old_context)


@asynccontextmanager
async def run_with_context(
    ctx: RunContext,
    manager: Optional[CallbackManager] = None,
):
    """
    Context manager for running with an existing context.

    Useful when you want to share a context across multiple operations.

    Args:
        ctx: The RunContext to use.
        manager: Optional CallbackManager (uses existing if not provided).

    Yields:
        The same RunContext.
    """
    # Use existing manager if not provided
    if manager is None:
        manager = get_callback_manager()

    # Store old values
    old_manager = _callback_manager_var.get()
    old_context = _run_context_var.get()

    # Set new values
    if manager is not None:
        _callback_manager_var.set(manager)
    _run_context_var.set(ctx)

    try:
        yield ctx
    finally:
        # Restore old values
        _callback_manager_var.set(old_manager)
        _run_context_var.set(old_context)


@asynccontextmanager
async def child_run(
    run_name: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
):
    """
    Create a child run within the current context.

    This is useful for tracking nested operations within a pipeline.

    Usage:
        async with run_with_callbacks([handler]) as parent:
            async with child_run("asr-processing") as child:
                # child.parent_run_id == parent.run_id
                result = await asr.ainvoke(audio)

    Args:
        run_name: Name for the child run.
        metadata: Additional metadata.
        tags: Tags for the child run.

    Yields:
        New RunContext for the child run.
    """
    manager = get_callback_manager()
    parent_ctx = get_run_context()

    if manager is None:
        # No callback manager set, just create a context
        ctx = RunContext(
            run_name=run_name,
            metadata=metadata or {},
            tags=tags or [],
            parent_run_id=parent_ctx.run_id if parent_ctx else None,
        )
        yield ctx
        return

    # Create child context
    ctx = manager.create_context(
        run_name=run_name,
        metadata=metadata,
        tags=tags,
        parent_run_id=parent_ctx.run_id if parent_ctx else None,
    )

    # Store old context
    old_context = _run_context_var.get()
    _run_context_var.set(ctx)

    try:
        yield ctx
    finally:
        _run_context_var.set(old_context)


# ==================== Helper Functions ====================


async def emit_asr_start(input: bytes) -> None:
    """Emit ASR start event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_asr_start(ctx, input)


async def emit_asr_end(result: Any) -> None:
    """Emit ASR end event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_asr_end(ctx, result)


async def emit_llm_start(messages: list[dict[str, str]]) -> None:
    """Emit LLM start event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_llm_start(ctx, messages)


async def emit_llm_token(token: str) -> None:
    """Emit LLM token event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_llm_token(ctx, token)


async def emit_llm_end(response: str) -> None:
    """Emit LLM end event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_llm_end(ctx, response)


async def emit_tts_start(text: str) -> None:
    """Emit TTS start event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_tts_start(ctx, text)


async def emit_tts_chunk(chunk: Any) -> None:
    """Emit TTS chunk event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_tts_chunk(ctx, chunk)


async def emit_tts_end() -> None:
    """Emit TTS end event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_tts_end(ctx)


async def emit_custom_event(event_name: str, data: Any = None) -> None:
    """Emit custom event using current context."""
    manager = get_callback_manager()
    ctx = get_run_context()
    if manager and ctx:
        await manager.on_custom_event(ctx, event_name, data)

"""
StdOut callback handler for Voice Pipeline.

Simple handler that prints events to stdout for debugging.
"""

import sys
from typing import Any, Optional, TextIO

from voice_pipeline.callbacks.base import RunContext, VoiceCallbackHandler
from voice_pipeline.interfaces import (
    AudioChunk,
    LLMChunk,
    TranscriptionResult,
    VADEvent,
)


class StdOutHandler(VoiceCallbackHandler):
    """
    Callback handler that prints events to stdout.

    Useful for debugging and development.

    Example:
        handler = StdOutHandler(
            show_timestamps=True,
            show_tokens=True,
        )

        async with run_with_callbacks([handler]):
            result = await chain.ainvoke(audio)

        # Output:
        # [0.00ms] PIPELINE_START
        # [123.45ms] ASR_START (1024 bytes)
        # [456.78ms] ASR_END: "Hello world"
        # ...
    """

    # ANSI color codes
    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
    }

    EVENT_COLORS = {
        "PIPELINE": "bold",
        "ASR": "cyan",
        "LLM": "green",
        "TTS": "magenta",
        "VAD": "blue",
        "BARGE": "red",
        "TURN": "yellow",
        "ERROR": "red",
        "AGENT": "green",
    }

    def __init__(
        self,
        output: Optional[TextIO] = None,
        show_timestamps: bool = True,
        show_run_id: bool = False,
        show_tokens: bool = False,
        show_audio_chunks: bool = False,
        use_colors: bool = True,
        prefix: str = "",
    ):
        """
        Initialize the stdout handler.

        Args:
            output: Output stream (defaults to sys.stdout).
            show_timestamps: Show elapsed time for each event.
            show_run_id: Show run ID in output.
            show_tokens: Print individual LLM tokens.
            show_audio_chunks: Print audio chunk events.
            use_colors: Use ANSI colors in output.
            prefix: Prefix for all output lines.
        """
        self.output = output or sys.stdout
        self.show_timestamps = show_timestamps
        self.show_run_id = show_run_id
        self.show_tokens = show_tokens
        self.show_audio_chunks = show_audio_chunks
        self.use_colors = use_colors and self._supports_colors()
        self.prefix = prefix

        # Track LLM response for inline printing
        self._llm_buffer: dict[str, str] = {}

    def _supports_colors(self) -> bool:
        """Check if output supports colors."""
        if hasattr(self.output, "isatty"):
            return self.output.isatty()
        return False

    def _color(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled."""
        if not self.use_colors:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"

    def _print(
        self,
        ctx: RunContext,
        event: str,
        message: str = "",
        color: Optional[str] = None,
        newline: bool = True,
    ) -> None:
        """Print an event message."""
        parts = [self.prefix]

        # Timestamp
        if self.show_timestamps:
            ts = f"[{ctx.elapsed_ms:>8.2f}ms]"
            parts.append(self._color(ts, "dim"))

        # Run ID
        if self.show_run_id:
            run_id = ctx.run_id[:8]
            parts.append(self._color(f"({run_id})", "dim"))

        # Event name with color
        if color is None:
            for key, col in self.EVENT_COLORS.items():
                if event.startswith(key):
                    color = col
                    break

        event_str = self._color(event, color or "bold")
        parts.append(event_str)

        # Message
        if message:
            parts.append(message)

        line = " ".join(parts)

        if newline:
            print(line, file=self.output)
        else:
            print(line, end="", file=self.output, flush=True)

    # ==================== Pipeline Lifecycle ====================

    async def on_pipeline_start(self, ctx: RunContext) -> None:
        name = f" ({ctx.run_name})" if ctx.run_name else ""
        self._print(ctx, "PIPELINE_START", f"Pipeline started{name}")

    async def on_pipeline_end(self, ctx: RunContext, output: Any = None) -> None:
        self._print(ctx, "PIPELINE_END", f"Completed in {ctx.elapsed_ms:.1f}ms")

    async def on_pipeline_error(self, ctx: RunContext, error: Exception) -> None:
        self._print(
            ctx,
            "PIPELINE_ERROR",
            f"{type(error).__name__}: {error}",
            color="red",
        )

    # ==================== VAD Events ====================

    async def on_vad_speech_start(self, ctx: RunContext, event: VADEvent) -> None:
        self._print(
            ctx,
            "VAD_SPEECH_START",
            f"Speech detected (conf: {event.confidence:.2f})",
        )

    async def on_vad_speech_end(self, ctx: RunContext, event: VADEvent) -> None:
        self._print(ctx, "VAD_SPEECH_END", "Speech ended")

    # ==================== ASR Events ====================

    async def on_asr_start(self, ctx: RunContext, input: bytes) -> None:
        self._print(ctx, "ASR_START", f"({len(input)} bytes)")

    async def on_asr_partial(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        preview = result.text[:40] + "..." if len(result.text) > 40 else result.text
        conf_str = f"{result.confidence:.2f}" if result.confidence is not None else "N/A"
        self._print(
            ctx,
            "ASR_PARTIAL",
            f'"{preview}" (conf: {conf_str})',
        )

    async def on_asr_end(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        conf_str = f"{result.confidence:.2f}" if result.confidence is not None else "N/A"
        self._print(
            ctx,
            "ASR_END",
            f'"{result.text}" (conf: {conf_str})',
        )

    async def on_asr_error(self, ctx: RunContext, error: Exception) -> None:
        self._print(ctx, "ASR_ERROR", str(error), color="red")

    # ==================== LLM Events ====================

    async def on_llm_start(
        self, ctx: RunContext, messages: list[dict[str, str]]
    ) -> None:
        last = messages[-1]["content"][:50] if messages else ""
        self._print(
            ctx,
            "LLM_START",
            f'({len(messages)} msgs, last: "{last}...")',
        )
        self._llm_buffer[ctx.run_id] = ""

    async def on_llm_token(self, ctx: RunContext, token: str) -> None:
        self._llm_buffer[ctx.run_id] = self._llm_buffer.get(ctx.run_id, "") + token

        if self.show_tokens:
            # Print token inline without timestamp
            print(token, end="", file=self.output, flush=True)

    async def on_llm_end(self, ctx: RunContext, response: str) -> None:
        if self.show_tokens:
            # Add newline after inline tokens
            print(file=self.output)

        preview = response[:80] + "..." if len(response) > 80 else response
        self._print(ctx, "LLM_END", f'"{preview}"')
        self._llm_buffer.pop(ctx.run_id, None)

    async def on_llm_error(self, ctx: RunContext, error: Exception) -> None:
        if self.show_tokens:
            print(file=self.output)
        self._print(ctx, "LLM_ERROR", str(error), color="red")
        self._llm_buffer.pop(ctx.run_id, None)

    # ==================== TTS Events ====================

    async def on_tts_start(self, ctx: RunContext, text: str) -> None:
        preview = text[:50] + "..." if len(text) > 50 else text
        self._print(ctx, "TTS_START", f'"{preview}"')

    async def on_tts_chunk(self, ctx: RunContext, chunk: AudioChunk) -> None:
        if self.show_audio_chunks:
            duration = f" ({chunk.duration_ms:.0f}ms)" if chunk.duration_ms else ""
            self._print(ctx, "TTS_CHUNK", f"{len(chunk.data)} bytes{duration}")

    async def on_tts_end(self, ctx: RunContext) -> None:
        self._print(ctx, "TTS_END", "Synthesis complete")

    async def on_tts_error(self, ctx: RunContext, error: Exception) -> None:
        self._print(ctx, "TTS_ERROR", str(error), color="red")

    # ==================== Special Events ====================

    async def on_barge_in(self, ctx: RunContext) -> None:
        self._print(ctx, "BARGE_IN", "User interrupted!", color="red")

    async def on_turn_start(self, ctx: RunContext) -> None:
        self._print(ctx, "TURN_START", "New turn")

    async def on_turn_end(self, ctx: RunContext) -> None:
        self._print(ctx, "TURN_END", f"Turn completed in {ctx.elapsed_ms:.1f}ms")

    async def on_custom_event(
        self, ctx: RunContext, event_name: str, data: Any = None
    ) -> None:
        data_str = f": {data}" if data is not None else ""
        self._print(ctx, f"CUSTOM:{event_name}", data_str)

    # ==================== Agent Events ====================

    async def on_agent_start(
        self, ctx: RunContext, input: str, tools: list[str]
    ) -> None:
        preview = input[:40] + "..." if len(input) > 40 else input
        tools_str = f" with {len(tools)} tools" if tools else ""
        self._print(
            ctx,
            "AGENT_START",
            f'"{preview}"{tools_str}',
            color="green",
        )

    async def on_agent_iteration(
        self, ctx: RunContext, iteration: int, max_iterations: int
    ) -> None:
        self._print(
            ctx,
            "AGENT_ITERATION",
            f"[{iteration}/{max_iterations}]",
            color="dim",
        )

    async def on_agent_thinking(self, ctx: RunContext) -> None:
        self._print(ctx, "AGENT_THINKING", "🤔", color="yellow")

    async def on_agent_tool_start(
        self, ctx: RunContext, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        args_preview = str(arguments)[:30] + "..." if len(str(arguments)) > 30 else str(arguments)
        self._print(
            ctx,
            "AGENT_TOOL_START",
            f"🔧 {tool_name}({args_preview})",
            color="cyan",
        )

    async def on_agent_tool_end(
        self,
        ctx: RunContext,
        tool_name: str,
        result: Any,
        success: bool,
        duration_ms: float,
    ) -> None:
        status = "✅" if success else "❌"
        self._print(
            ctx,
            "AGENT_TOOL_END",
            f"{status} {tool_name} ({duration_ms:.1f}ms)",
            color="green" if success else "red",
        )

    async def on_agent_tool_error(
        self, ctx: RunContext, tool_name: str, error: Exception
    ) -> None:
        self._print(
            ctx,
            "AGENT_TOOL_ERROR",
            f"❌ {tool_name}: {error}",
            color="red",
        )

    async def on_agent_response(self, ctx: RunContext, response: str) -> None:
        preview = response[:60] + "..." if len(response) > 60 else response
        self._print(
            ctx,
            "AGENT_RESPONSE",
            f'"{preview}"',
            color="green",
        )

    async def on_agent_end(
        self, ctx: RunContext, response: str, iterations: int, duration_ms: float
    ) -> None:
        self._print(
            ctx,
            "AGENT_END",
            f"✅ Completed ({iterations} iters, {duration_ms:.1f}ms)",
            color="green",
        )

    async def on_agent_error(self, ctx: RunContext, error: Exception) -> None:
        self._print(
            ctx,
            "AGENT_ERROR",
            f"❌ {type(error).__name__}: {error}",
            color="red",
        )

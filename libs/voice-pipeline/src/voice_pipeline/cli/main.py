"""Main CLI entry point for Voice Pipeline.

Provides commands for testing and developing voice agents:
- chat: Text-based conversation
- voice: Voice conversation with microphone
- benchmark: Measure latency metrics
- info: Show system information

Example:
    $ voice-pipeline chat --model qwen2.5:0.5b
    $ voice-pipeline voice --asr whisper --tts kokoro
    $ voice-pipeline benchmark --iterations 10
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

try:
    import typer
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import print as rprint
except ImportError:
    print("CLI dependencies not installed. Install with:")
    print("  pip install voice-pipeline[cli]")
    sys.exit(1)

app = typer.Typer(
    name="voice-pipeline",
    help="Voice Pipeline CLI - Build and test voice agents easily.",
    add_completion=True,
)
console = Console()


def version_callback(value: bool):
    """Show version and exit."""
    if value:
        from voice_pipeline import __version__
        console.print(f"[bold blue]Voice Pipeline[/bold blue] v{__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
):
    """Voice Pipeline CLI - Build and test voice agents easily."""
    pass


@app.command()
def chat(
    model: str = typer.Option(
        "qwen2.5:0.5b",
        "--model",
        "-m",
        help="LLM model to use (Ollama).",
    ),
    system_prompt: Optional[str] = typer.Option(
        None,
        "--system",
        "-s",
        help="System prompt for the agent.",
    ),
    temperature: float = typer.Option(
        0.7,
        "--temperature",
        "-t",
        help="LLM temperature (0.0-1.0).",
    ),
):
    """Start a text-based chat session with the agent.

    Example:
        $ voice-pipeline chat
        $ voice-pipeline chat --model llama3.2:1b
        $ voice-pipeline chat --system "You are a helpful assistant"
    """
    from voice_pipeline.cli.commands.chat import run_chat
    asyncio.run(run_chat(model, system_prompt, temperature))


@app.command()
def voice(
    asr: str = typer.Option(
        "whisper",
        "--asr",
        help="ASR provider (whisper, openai, deepgram).",
    ),
    llm: str = typer.Option(
        "ollama",
        "--llm",
        help="LLM provider (ollama, openai).",
    ),
    model: str = typer.Option(
        "qwen2.5:0.5b",
        "--model",
        "-m",
        help="LLM model to use.",
    ),
    tts: str = typer.Option(
        "kokoro",
        "--tts",
        help="TTS provider (kokoro, openai).",
    ),
    voice_name: str = typer.Option(
        "pf_dora",
        "--voice",
        "-V",
        help="TTS voice name.",
    ),
    language: str = typer.Option(
        "pt",
        "--language",
        "-l",
        help="Language code (pt, en, es, etc.).",
    ),
    streaming: bool = typer.Option(
        True,
        "--streaming/--no-streaming",
        help="Enable sentence-level streaming (low latency).",
    ),
):
    """Start a voice conversation with microphone input.

    Requires a microphone and speaker.

    Example:
        $ voice-pipeline voice
        $ voice-pipeline voice --asr deepgram --language en
        $ voice-pipeline voice --tts openai --voice alloy
    """
    from voice_pipeline.cli.commands.voice import run_voice
    asyncio.run(run_voice(
        asr=asr,
        llm=llm,
        model=model,
        tts=tts,
        voice_name=voice_name,
        language=language,
        streaming=streaming,
    ))


@app.command()
def benchmark(
    iterations: int = typer.Option(
        5,
        "--iterations",
        "-n",
        help="Number of iterations to run.",
    ),
    model: str = typer.Option(
        "qwen2.5:0.5b",
        "--model",
        "-m",
        help="LLM model to use.",
    ),
    streaming: bool = typer.Option(
        True,
        "--streaming/--no-streaming",
        help="Enable streaming mode.",
    ),
    warmup: bool = typer.Option(
        True,
        "--warmup/--no-warmup",
        help="Enable TTS warmup.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for results (JSON).",
    ),
):
    """Benchmark voice pipeline latency metrics.

    Measures:
    - TTFT: Time to First Token (LLM)
    - TTFA: Time to First Audio (end-to-end)
    - RTF: Real-Time Factor

    Example:
        $ voice-pipeline benchmark
        $ voice-pipeline benchmark --iterations 10
        $ voice-pipeline benchmark --output results.json
    """
    from voice_pipeline.cli.commands.benchmark import run_benchmark
    asyncio.run(run_benchmark(
        iterations=iterations,
        model=model,
        streaming=streaming,
        warmup=warmup,
        output=output,
    ))


@app.command()
def info():
    """Show system information and available providers.

    Displays:
    - Python version
    - Voice Pipeline version
    - Available ASR providers
    - Available LLM providers
    - Available TTS providers
    - Hardware info
    """
    from voice_pipeline.cli.commands.info import show_info
    show_info()


@app.command()
def providers():
    """List all available providers.

    Shows registered ASR, LLM, TTS, and VAD providers
    with their capabilities.
    """
    from voice_pipeline.cli.commands.providers import list_providers
    list_providers()


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()

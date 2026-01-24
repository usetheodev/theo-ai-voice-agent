"""Providers command - List available providers."""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def list_providers():
    """Display all available providers and their capabilities."""
    from voice_pipeline.providers import get_registry

    registry = get_registry()
    providers = registry.list_providers()

    # ASR Providers
    asr_table = Table(title="ASR Providers (Speech-to-Text)", show_header=True)
    asr_table.add_column("Name", style="cyan")
    asr_table.add_column("Streaming", justify="center")
    asr_table.add_column("Real-time", justify="center")
    asr_table.add_column("Languages")

    asr_providers = [
        ("whisper", False, False, "multi (100+)"),
        ("openai", False, False, "multi (57)"),
        ("deepgram", True, True, "en, pt, es, fr, de, ..."),
    ]

    for name, streaming, realtime, languages in asr_providers:
        streaming_icon = "[green]✓[/green]" if streaming else "[dim]✗[/dim]"
        realtime_icon = "[green]✓[/green]" if realtime else "[dim]✗[/dim]"
        asr_table.add_row(name, streaming_icon, realtime_icon, languages)

    console.print(asr_table)

    # LLM Providers
    llm_table = Table(title="LLM Providers", show_header=True)
    llm_table.add_column("Name", style="cyan")
    llm_table.add_column("Streaming", justify="center")
    llm_table.add_column("Local", justify="center")
    llm_table.add_column("Default Model")

    llm_providers = [
        ("ollama", True, True, "qwen2.5:0.5b"),
        ("openai", True, False, "gpt-4o-mini"),
    ]

    for name, streaming, local, default_model in llm_providers:
        streaming_icon = "[green]✓[/green]" if streaming else "[dim]✗[/dim]"
        local_icon = "[green]✓[/green]" if local else "[dim]✗[/dim]"
        llm_table.add_row(name, streaming_icon, local_icon, default_model)

    console.print(llm_table)

    # TTS Providers
    tts_table = Table(title="TTS Providers (Text-to-Speech)", show_header=True)
    tts_table.add_column("Name", style="cyan")
    tts_table.add_column("Streaming", justify="center")
    tts_table.add_column("Local", justify="center")
    tts_table.add_column("Default Voice")

    tts_providers = [
        ("kokoro", True, True, "pf_dora"),
        ("openai", True, False, "alloy"),
    ]

    for name, streaming, local, default_voice in tts_providers:
        streaming_icon = "[green]✓[/green]" if streaming else "[dim]✗[/dim]"
        local_icon = "[green]✓[/green]" if local else "[dim]✗[/dim]"
        tts_table.add_row(name, streaming_icon, local_icon, default_voice)

    console.print(tts_table)

    # VAD Providers
    vad_table = Table(title="VAD Providers (Voice Activity Detection)", show_header=True)
    vad_table.add_column("Name", style="cyan")
    vad_table.add_column("Type", justify="center")
    vad_table.add_column("Notes")

    vad_providers = [
        ("silero", "Neural", "High accuracy, slightly higher latency"),
        ("webrtc", "Heuristic", "Low latency, good for barge-in"),
    ]

    for name, vad_type, notes in vad_providers:
        vad_table.add_row(name, vad_type, notes)

    console.print(vad_table)

    # Vector Store Providers (for RAG)
    rag_table = Table(title="RAG Providers", show_header=True)
    rag_table.add_column("Component", style="cyan")
    rag_table.add_column("Provider")
    rag_table.add_column("Notes")

    rag_table.add_row("Embedding", "sentence-transformers", "all-MiniLM-L6-v2 (384-dim)")
    rag_table.add_row("Vector Store", "faiss", "Local, supports flat/ivf/hnsw")

    console.print(rag_table)

    # Usage examples
    console.print(Panel(
        "[bold]Usage Examples:[/bold]\n\n"
        "[cyan]# Local setup (no API keys needed)[/cyan]\n"
        "voice-pipeline chat --model qwen2.5:0.5b\n\n"
        "[cyan]# With streaming ASR (needs Deepgram API key)[/cyan]\n"
        "voice-pipeline voice --asr deepgram --language en\n\n"
        "[cyan]# With OpenAI[/cyan]\n"
        "voice-pipeline chat --llm openai --model gpt-4o-mini",
        title="Examples",
    ))


if __name__ == "__main__":
    list_providers()

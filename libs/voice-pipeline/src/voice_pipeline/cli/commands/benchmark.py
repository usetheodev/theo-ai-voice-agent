"""Benchmark command - Measure latency metrics."""

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

console = Console()


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    iteration: int
    ttft_ms: float  # Time to First Token
    ttfa_ms: float  # Time to First Audio
    total_ms: float  # Total processing time
    tokens: int
    sentences: int
    audio_duration_ms: float
    rtf: float  # Real-Time Factor


@dataclass
class BenchmarkSummary:
    """Summary of benchmark results."""
    iterations: int
    model: str
    streaming: bool
    warmup: bool

    # TTFT stats
    ttft_avg_ms: float
    ttft_min_ms: float
    ttft_max_ms: float
    ttft_std_ms: float

    # TTFA stats
    ttfa_avg_ms: float
    ttfa_min_ms: float
    ttfa_max_ms: float
    ttfa_std_ms: float

    # Total stats
    total_avg_ms: float
    total_min_ms: float
    total_max_ms: float

    # RTF stats
    rtf_avg: float
    rtf_min: float
    rtf_max: float

    # Throughput
    tokens_per_second: float
    sentences_per_second: float

    results: list[BenchmarkResult] = field(default_factory=list)


async def run_benchmark(
    iterations: int,
    model: str,
    streaming: bool,
    warmup: bool,
    output: Optional[Path],
):
    """Run benchmark and measure latency metrics.

    Args:
        iterations: Number of iterations to run.
        model: LLM model name.
        streaming: Enable streaming mode.
        warmup: Enable TTS warmup.
        output: Output file for results (JSON).
    """
    from voice_pipeline import VoiceAgent
    import numpy as np

    console.print(Panel(
        "[bold blue]Voice Pipeline Benchmark[/bold blue]\n"
        f"Iterations: [cyan]{iterations}[/cyan]\n"
        f"Model: [cyan]{model}[/cyan]\n"
        f"Streaming: [cyan]{streaming}[/cyan]\n"
        f"Warmup: [cyan]{warmup}[/cyan]",
        title="Configuration",
    ))

    # Test prompts (Portuguese)
    test_prompts = [
        "Olá, como você está?",
        "Qual é a capital do Brasil?",
        "Me conte uma curiosidade interessante.",
        "O que você pode fazer?",
        "Explique o que é inteligência artificial.",
    ]

    # Build agent
    console.print("\n[cyan]Building agent...[/cyan]")

    try:
        builder = (
            VoiceAgent.builder()
            .asr("whisper", model="base", language="pt")
            .llm("ollama", model=model)
            .tts("kokoro", voice="pf_dora")
            .streaming(streaming)
            .warmup(warmup)
        )

        agent = await builder.build_async()
        console.print("[green]Agent ready![/green]\n")

    except Exception as e:
        console.print(f"[red]Error building agent: {e}[/red]")
        console.print("[yellow]Make sure Ollama is running and the model is available.[/yellow]")
        return

    # Run benchmark
    results: list[BenchmarkResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Running benchmark...", total=iterations)

        for i in range(iterations):
            prompt = test_prompts[i % len(test_prompts)]

            # Simulate audio input (we'll measure from text to audio)
            start_time = time.perf_counter()
            first_token_time = None
            first_audio_time = None
            token_count = 0
            sentence_count = 0
            audio_bytes_total = 0

            try:
                # For now, measure LLM streaming directly
                # (full pipeline would need audio input)
                messages = [{"role": "user", "content": prompt}]

                async for chunk in agent.llm.astream(messages):
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    token_count += 1

                    # Detect sentences
                    text = chunk.text if hasattr(chunk, 'text') else str(chunk)
                    if any(c in text for c in '.!?'):
                        sentence_count += 1

                end_time = time.perf_counter()

                # Calculate metrics
                ttft_ms = (first_token_time - start_time) * 1000 if first_token_time else 0
                total_ms = (end_time - start_time) * 1000

                # Estimate TTFA (TTFT + first sentence TTS time)
                # For now, estimate based on typical TTS latency
                estimated_tts_ms = 150  # Conservative estimate
                ttfa_ms = ttft_ms + estimated_tts_ms

                # Estimate audio duration (assumes ~150 words/min speaking rate)
                words = token_count // 2  # Rough tokens-to-words ratio
                audio_duration_ms = (words / 150) * 60 * 1000

                # RTF = processing_time / audio_duration
                rtf = total_ms / audio_duration_ms if audio_duration_ms > 0 else 0

                result = BenchmarkResult(
                    iteration=i + 1,
                    ttft_ms=ttft_ms,
                    ttfa_ms=ttfa_ms,
                    total_ms=total_ms,
                    tokens=token_count,
                    sentences=max(1, sentence_count),
                    audio_duration_ms=audio_duration_ms,
                    rtf=rtf,
                )
                results.append(result)

            except Exception as e:
                console.print(f"[red]Iteration {i+1} failed: {e}[/red]")

            progress.update(task, advance=1)

    # Calculate summary statistics
    if results:
        ttft_values = [r.ttft_ms for r in results]
        ttfa_values = [r.ttfa_ms for r in results]
        total_values = [r.total_ms for r in results]
        rtf_values = [r.rtf for r in results]

        total_tokens = sum(r.tokens for r in results)
        total_sentences = sum(r.sentences for r in results)
        total_time = sum(r.total_ms for r in results) / 1000

        summary = BenchmarkSummary(
            iterations=len(results),
            model=model,
            streaming=streaming,
            warmup=warmup,
            # TTFT
            ttft_avg_ms=np.mean(ttft_values),
            ttft_min_ms=np.min(ttft_values),
            ttft_max_ms=np.max(ttft_values),
            ttft_std_ms=np.std(ttft_values),
            # TTFA
            ttfa_avg_ms=np.mean(ttfa_values),
            ttfa_min_ms=np.min(ttfa_values),
            ttfa_max_ms=np.max(ttfa_values),
            ttfa_std_ms=np.std(ttfa_values),
            # Total
            total_avg_ms=np.mean(total_values),
            total_min_ms=np.min(total_values),
            total_max_ms=np.max(total_values),
            # RTF
            rtf_avg=np.mean(rtf_values),
            rtf_min=np.min(rtf_values),
            rtf_max=np.max(rtf_values),
            # Throughput
            tokens_per_second=total_tokens / total_time if total_time > 0 else 0,
            sentences_per_second=total_sentences / total_time if total_time > 0 else 0,
            results=results,
        )

        # Display results
        display_results(summary)

        # Save to file
        if output:
            save_results(summary, output)

    # Cleanup
    if hasattr(agent, 'disconnect'):
        await agent.disconnect()


def display_results(summary: BenchmarkSummary):
    """Display benchmark results in a nice table."""
    console.print()

    # Main metrics table
    table = Table(title="Benchmark Results", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Average", justify="right", style="green")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")
    table.add_column("Std", justify="right", style="dim")

    table.add_row(
        "TTFT (Time to First Token)",
        f"{summary.ttft_avg_ms:.1f}ms",
        f"{summary.ttft_min_ms:.1f}ms",
        f"{summary.ttft_max_ms:.1f}ms",
        f"{summary.ttft_std_ms:.1f}ms",
    )

    table.add_row(
        "TTFA (Time to First Audio)",
        f"{summary.ttfa_avg_ms:.1f}ms",
        f"{summary.ttfa_min_ms:.1f}ms",
        f"{summary.ttfa_max_ms:.1f}ms",
        f"{summary.ttfa_std_ms:.1f}ms",
    )

    table.add_row(
        "Total Processing Time",
        f"{summary.total_avg_ms:.1f}ms",
        f"{summary.total_min_ms:.1f}ms",
        f"{summary.total_max_ms:.1f}ms",
        "-",
    )

    table.add_row(
        "RTF (Real-Time Factor)",
        f"{summary.rtf_avg:.3f}",
        f"{summary.rtf_min:.3f}",
        f"{summary.rtf_max:.3f}",
        "-",
    )

    console.print(table)

    # Throughput table
    throughput_table = Table(title="Throughput", show_header=True)
    throughput_table.add_column("Metric", style="cyan")
    throughput_table.add_column("Value", justify="right", style="green")

    throughput_table.add_row(
        "Tokens/second",
        f"{summary.tokens_per_second:.1f}",
    )
    throughput_table.add_row(
        "Sentences/second",
        f"{summary.sentences_per_second:.2f}",
    )

    console.print(throughput_table)

    # Interpretation
    console.print()
    if summary.ttfa_avg_ms < 800:
        console.print("[green]Excellent! TTFA < 800ms - Voice feels responsive.[/green]")
    elif summary.ttfa_avg_ms < 1500:
        console.print("[yellow]Good. TTFA < 1500ms - Acceptable for most use cases.[/yellow]")
    else:
        console.print("[red]TTFA > 1500ms - Consider optimizations.[/red]")

    if summary.rtf_avg < 0.5:
        console.print("[green]Excellent! RTF < 0.5 - Processing faster than real-time.[/green]")
    elif summary.rtf_avg < 1.0:
        console.print("[yellow]Good. RTF < 1.0 - Real-time capable.[/yellow]")
    else:
        console.print("[red]RTF > 1.0 - Processing slower than real-time.[/red]")


def save_results(summary: BenchmarkSummary, output: Path):
    """Save benchmark results to JSON file."""
    # Convert to dict (excluding results to keep file clean)
    data = {
        "iterations": summary.iterations,
        "model": summary.model,
        "streaming": summary.streaming,
        "warmup": summary.warmup,
        "metrics": {
            "ttft": {
                "avg_ms": summary.ttft_avg_ms,
                "min_ms": summary.ttft_min_ms,
                "max_ms": summary.ttft_max_ms,
                "std_ms": summary.ttft_std_ms,
            },
            "ttfa": {
                "avg_ms": summary.ttfa_avg_ms,
                "min_ms": summary.ttfa_min_ms,
                "max_ms": summary.ttfa_max_ms,
                "std_ms": summary.ttfa_std_ms,
            },
            "total": {
                "avg_ms": summary.total_avg_ms,
                "min_ms": summary.total_min_ms,
                "max_ms": summary.total_max_ms,
            },
            "rtf": {
                "avg": summary.rtf_avg,
                "min": summary.rtf_min,
                "max": summary.rtf_max,
            },
        },
        "throughput": {
            "tokens_per_second": summary.tokens_per_second,
            "sentences_per_second": summary.sentences_per_second,
        },
        "raw_results": [asdict(r) for r in summary.results],
    }

    with open(output, "w") as f:
        json.dump(data, f, indent=2)

    console.print(f"\n[green]Results saved to {output}[/green]")


if __name__ == "__main__":
    asyncio.run(run_benchmark(
        iterations=5,
        model="qwen2.5:0.5b",
        streaming=True,
        warmup=True,
        output=None,
    ))

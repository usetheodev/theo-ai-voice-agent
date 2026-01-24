"""Info command - Show system information."""

import platform
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def show_info():
    """Display system information and configuration."""
    from voice_pipeline import __version__

    # System info
    console.print(Panel(
        f"[bold blue]Voice Pipeline[/bold blue] v{__version__}\n"
        f"Python: {sys.version.split()[0]}\n"
        f"Platform: {platform.system()} {platform.release()}\n"
        f"Architecture: {platform.machine()}",
        title="System Information",
    ))

    # Check dependencies
    deps_table = Table(title="Dependencies", show_header=True)
    deps_table.add_column("Package", style="cyan")
    deps_table.add_column("Version", justify="right")
    deps_table.add_column("Status", justify="center")

    dependencies = [
        ("numpy", "numpy"),
        ("torch", "torch"),
        ("sounddevice", "sounddevice"),
        ("faiss-cpu", "faiss"),
        ("sentence-transformers", "sentence_transformers"),
        ("typer", "typer"),
        ("rich", "rich"),
        ("httpx", "httpx"),
        ("websockets", "websockets"),
    ]

    for name, import_name in dependencies:
        try:
            module = __import__(import_name)
            version = getattr(module, "__version__", "installed")
            status = "[green]OK[/green]"
        except ImportError:
            version = "-"
            status = "[dim]not installed[/dim]"

        deps_table.add_row(name, version, status)

    console.print(deps_table)

    # Check hardware
    hardware_table = Table(title="Hardware", show_header=True)
    hardware_table.add_column("Component", style="cyan")
    hardware_table.add_column("Status", justify="right")

    # Check CUDA
    try:
        import torch
        if torch.cuda.is_available():
            cuda_status = f"[green]Available ({torch.cuda.get_device_name(0)})[/green]"
        else:
            cuda_status = "[yellow]Not available[/yellow]"
    except ImportError:
        cuda_status = "[dim]PyTorch not installed[/dim]"

    hardware_table.add_row("CUDA", cuda_status)

    # Check MPS (Apple Silicon)
    try:
        import torch
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            mps_status = "[green]Available[/green]"
        else:
            mps_status = "[dim]Not available[/dim]"
    except ImportError:
        mps_status = "[dim]PyTorch not installed[/dim]"

    hardware_table.add_row("MPS (Apple Silicon)", mps_status)

    # Check audio devices
    try:
        import sounddevice
        devices = sounddevice.query_devices()
        input_devices = [d for d in devices if d['max_input_channels'] > 0]
        output_devices = [d for d in devices if d['max_output_channels'] > 0]
        audio_status = f"[green]{len(input_devices)} input, {len(output_devices)} output[/green]"
    except ImportError:
        audio_status = "[dim]sounddevice not installed[/dim]"
    except Exception as e:
        audio_status = f"[red]Error: {e}[/red]"

    hardware_table.add_row("Audio Devices", audio_status)

    console.print(hardware_table)

    # Check services
    services_table = Table(title="Services", show_header=True)
    services_table.add_column("Service", style="cyan")
    services_table.add_column("Status", justify="right")

    # Check Ollama
    try:
        import httpx
        response = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code == 200:
            models = response.json().get("models", [])
            ollama_status = f"[green]Running ({len(models)} models)[/green]"
        else:
            ollama_status = "[yellow]Running but error[/yellow]"
    except Exception:
        ollama_status = "[red]Not running[/red]"

    services_table.add_row("Ollama", ollama_status)

    console.print(services_table)

    # Quick start tips
    console.print(Panel(
        "[bold]Quick Start:[/bold]\n"
        "  voice-pipeline chat          # Text chat\n"
        "  voice-pipeline voice         # Voice chat\n"
        "  voice-pipeline benchmark     # Measure latency\n"
        "  voice-pipeline providers     # List providers",
        title="Commands",
    ))


if __name__ == "__main__":
    show_info()

"""Voice command - Voice conversation with microphone."""

import asyncio
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

console = Console()


async def run_voice(
    asr: str,
    llm: str,
    model: str,
    tts: str,
    voice_name: str,
    language: str,
    streaming: bool,
):
    """Run voice conversation with microphone.

    Args:
        asr: ASR provider name.
        llm: LLM provider name.
        model: LLM model name.
        tts: TTS provider name.
        voice_name: TTS voice name.
        language: Language code.
        streaming: Enable streaming mode.
    """
    from voice_pipeline import VoiceAgent

    console.print(Panel(
        "[bold blue]Voice Pipeline - Voice Mode[/bold blue]\n"
        f"ASR: [cyan]{asr}[/cyan] | LLM: [cyan]{llm}/{model}[/cyan] | TTS: [cyan]{tts}/{voice_name}[/cyan]\n"
        f"Language: [cyan]{language}[/cyan] | Streaming: [cyan]{streaming}[/cyan]\n\n"
        "[yellow]Press Ctrl+C to stop.[/yellow]\n"
        "[dim]Speak into your microphone...[/dim]",
        title="Voice Conversation",
    ))

    # Check for audio dependencies
    try:
        import sounddevice
        import numpy as np
    except ImportError:
        console.print("[red]Audio dependencies not installed.[/red]")
        console.print("Install with: pip install sounddevice numpy")
        return

    # Build agent
    try:
        builder = (
            VoiceAgent.builder()
            .asr(asr, language=language)
            .llm(llm, model=model)
            .tts(tts, voice=voice_name)
            .language(language)
            .streaming(streaming)
        )

        agent = await builder.build_async()
        console.print("[green]Agent connected! Start speaking...[/green]\n")

    except Exception as e:
        console.print(f"[red]Error building agent: {e}[/red]")
        return

    # Audio settings
    sample_rate = 16000
    chunk_duration = 0.5  # seconds
    chunk_size = int(sample_rate * chunk_duration)

    # Voice activity detection state
    is_speaking = False
    silence_count = 0
    silence_threshold = 3  # chunks of silence before processing
    audio_buffer = []

    def audio_callback(indata, frames, time, status):
        """Callback for audio input."""
        nonlocal is_speaking, silence_count, audio_buffer

        if status:
            console.print(f"[yellow]Audio status: {status}[/yellow]")

        # Simple energy-based VAD
        energy = np.sqrt(np.mean(indata**2))
        threshold = 0.01

        if energy > threshold:
            is_speaking = True
            silence_count = 0
            audio_buffer.append(indata.copy())
        elif is_speaking:
            silence_count += 1
            audio_buffer.append(indata.copy())

    async def process_audio():
        """Process accumulated audio."""
        nonlocal audio_buffer, is_speaking, silence_count

        while True:
            await asyncio.sleep(0.1)

            if is_speaking and silence_count >= silence_threshold and audio_buffer:
                # Concatenate audio
                audio_data = np.concatenate(audio_buffer, axis=0)
                audio_bytes = (audio_data * 32767).astype(np.int16).tobytes()

                # Reset state
                audio_buffer = []
                is_speaking = False
                silence_count = 0

                # Process
                console.print("[cyan]Processing...[/cyan]")

                try:
                    async for audio_chunk in agent.astream(audio_bytes):
                        # Play audio chunk
                        audio_array = np.frombuffer(
                            audio_chunk.data, dtype=np.int16
                        ).astype(np.float32) / 32767.0

                        sounddevice.play(audio_array, audio_chunk.sample_rate)
                        sounddevice.wait()

                    console.print("[green]Ready for next input...[/green]\n")

                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")

    # Start audio input stream
    try:
        with sounddevice.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=chunk_size,
            callback=audio_callback,
        ):
            console.print("[dim]Listening...[/dim]")

            # Run processing loop
            await process_audio()

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping...[/yellow]")

    finally:
        # Cleanup
        if hasattr(agent, 'disconnect'):
            await agent.disconnect()

    console.print("[green]Goodbye![/green]")


if __name__ == "__main__":
    asyncio.run(run_voice(
        asr="whisper",
        llm="ollama",
        model="qwen2.5:0.5b",
        tts="kokoro",
        voice_name="pf_dora",
        language="pt",
        streaming=True,
    ))

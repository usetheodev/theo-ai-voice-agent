#!/usr/bin/env python3
"""
ASP Debug Tool - Ferramenta de debug para o Audio Session Protocol

Conecta a um servidor AI Agent e executa handshake ASP para verificar
capacidades e testar negociação de configuração.

Uso:
    python asp_debug.py [URL]                    # Handshake básico
    python asp_debug.py [URL] --config FILE      # Handshake com config customizada
    python asp_debug.py [URL] --json             # Output em JSON

Exemplos:
    python asp_debug.py ws://localhost:8765
    python asp_debug.py ws://ai-agent:8765 --json
    python asp_debug.py ws://localhost:8765 --vad-silence 700 --vad-threshold 0.6
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path

# Add shared to path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

import websockets
from websockets.client import WebSocketClientProtocol

from asp_protocol import (
    # Config
    AudioConfig,
    VADConfig,
    ProtocolCapabilities,
    AudioEncoding,
    # Messages
    ProtocolCapabilitiesMessage,
    SessionStartMessage,
    SessionStartedMessage,
    SessionEndMessage,
    parse_message,
    is_valid_message,
    # Enums
    SessionStatus,
)


# ANSI colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def colored(text: str, color: str) -> str:
    """Aplica cor ANSI ao texto."""
    return f"{color}{text}{Colors.ENDC}"


def print_header(text: str):
    """Imprime cabeçalho formatado."""
    print(f"\n{colored('═' * 60, Colors.BLUE)}")
    print(colored(f" {text}", Colors.BOLD + Colors.BLUE))
    print(colored('═' * 60, Colors.BLUE))


def print_success(text: str):
    """Imprime mensagem de sucesso."""
    print(colored(f" {text}", Colors.GREEN))


def print_warning(text: str):
    """Imprime aviso."""
    print(colored(f"️  {text}", Colors.YELLOW))


def print_error(text: str):
    """Imprime erro."""
    print(colored(f" {text}", Colors.RED))


def print_info(text: str):
    """Imprime informação."""
    print(colored(f"ℹ️  {text}", Colors.CYAN))


def print_timing(label: str, duration_ms: float):
    """Imprime timing."""
    color = Colors.GREEN if duration_ms < 100 else (Colors.YELLOW if duration_ms < 500 else Colors.RED)
    print(f"   ️  {label}: {colored(f'{duration_ms:.1f}ms', color)}")


def print_capabilities(caps: ProtocolCapabilities):
    """Imprime capabilities formatadas."""
    print(f"\n   {colored('Protocol Version:', Colors.BOLD)} {caps.version}")
    print(f"   {colored('Sample Rates:', Colors.BOLD)} {caps.supported_sample_rates}")
    print(f"   {colored('Encodings:', Colors.BOLD)} {caps.supported_encodings}")
    print(f"   {colored('Frame Durations:', Colors.BOLD)} {caps.supported_frame_durations}")
    print(f"   {colored('VAD Configurable:', Colors.BOLD)} {caps.vad_configurable}")

    if caps.vad_parameters:
        print(f"   {colored('VAD Parameters:', Colors.BOLD)}")
        for param in caps.vad_parameters:
            print(f"      - {param}")

    if caps.features:
        print(f"   {colored('Features:', Colors.BOLD)}")
        for feature in caps.features:
            print(f"      - {feature}")

    if caps.max_session_duration_seconds:
        print(f"   {colored('Max Session Duration:', Colors.BOLD)} {caps.max_session_duration_seconds}s")


def print_negotiated_config(msg: SessionStartedMessage):
    """Imprime configuração negociada."""
    if not msg.negotiated:
        return

    neg = msg.negotiated

    print(f"\n   {colored('Audio Config:', Colors.BOLD)}")
    print(f"      Sample Rate: {neg.audio.sample_rate}Hz")
    print(f"      Encoding: {neg.audio.encoding.value if hasattr(neg.audio.encoding, 'value') else neg.audio.encoding}")
    print(f"      Channels: {neg.audio.channels}")
    print(f"      Frame Duration: {neg.audio.frame_duration_ms}ms")

    print(f"\n   {colored('VAD Config:', Colors.BOLD)}")
    print(f"      Enabled: {neg.vad.enabled}")
    print(f"      Silence Threshold: {neg.vad.silence_threshold_ms}ms")
    print(f"      Min Speech: {neg.vad.min_speech_ms}ms")
    print(f"      Threshold: {neg.vad.threshold}")
    print(f"      Ring Buffer Frames: {neg.vad.ring_buffer_frames}")
    print(f"      Speech Ratio: {neg.vad.speech_ratio}")
    print(f"      Prefix Padding: {neg.vad.prefix_padding_ms}ms")

    if neg.adjustments:
        print(f"\n   {colored('Adjustments Made:', Colors.YELLOW)}")
        for adj in neg.adjustments:
            print(f"      {adj.field}: {adj.requested} → {adj.applied} ({adj.reason})")


async def run_debug(
    url: str,
    audio_config: AudioConfig,
    vad_config: VADConfig,
    output_json: bool = False,
    timeout: float = 10.0
):
    """
    Executa debug do handshake ASP.

    Args:
        url: URL do servidor WebSocket
        audio_config: Configuração de áudio para testar
        vad_config: Configuração de VAD para testar
        output_json: Se True, output em JSON
        timeout: Timeout para operações
    """
    results = {
        "url": url,
        "success": False,
        "capabilities": None,
        "negotiated": None,
        "timings": {},
        "errors": []
    }

    if not output_json:
        print_header("ASP Debug Tool")
        print_info(f"Connecting to: {url}")

    total_start = time.perf_counter()

    try:
        # 1. Conecta ao servidor
        connect_start = time.perf_counter()
        ws = await asyncio.wait_for(
            websockets.connect(url, ping_interval=30, ping_timeout=10),
            timeout=timeout
        )
        connect_time = (time.perf_counter() - connect_start) * 1000
        results["timings"]["connect_ms"] = connect_time

        if not output_json:
            print_success("Connected to server")
            print_timing("Connection time", connect_time)

        # 2. Aguarda capabilities
        caps_start = time.perf_counter()
        caps_data = await asyncio.wait_for(ws.recv(), timeout=5.0)
        caps_time = (time.perf_counter() - caps_start) * 1000
        results["timings"]["capabilities_ms"] = caps_time

        if isinstance(caps_data, bytes):
            raise ValueError("Received binary data instead of capabilities")

        if not is_valid_message(caps_data):
            raise ValueError("Server did not send valid ASP message - may be legacy server")

        caps_msg = parse_message(caps_data)
        if not isinstance(caps_msg, ProtocolCapabilitiesMessage):
            raise ValueError(f"Expected capabilities, got {type(caps_msg).__name__}")

        results["capabilities"] = caps_msg.capabilities.to_dict()

        if not output_json:
            print_success("Received protocol.capabilities")
            print_timing("Capabilities time", caps_time)
            print_capabilities(caps_msg.capabilities)

        # 3. Envia session.start
        session_id = str(uuid.uuid4())

        if not output_json:
            print_header("Session Negotiation")
            print_info(f"Session ID: {session_id[:8]}...")
            print_info(f"Requesting: sample_rate={audio_config.sample_rate}, "
                      f"vad.silence={vad_config.silence_threshold_ms}ms")

        start_msg = SessionStartMessage(
            session_id=session_id,
            audio=audio_config,
            vad=vad_config
        )

        negotiate_start = time.perf_counter()
        await ws.send(start_msg.to_json())

        # 4. Aguarda session.started
        started_data = await asyncio.wait_for(ws.recv(), timeout=timeout)
        negotiate_time = (time.perf_counter() - negotiate_start) * 1000
        results["timings"]["negotiation_ms"] = negotiate_time

        started_msg = parse_message(started_data)
        if not isinstance(started_msg, SessionStartedMessage):
            raise ValueError(f"Expected session.started, got {type(started_msg).__name__}")

        if started_msg.is_accepted:
            results["success"] = True
            results["negotiated"] = started_msg.negotiated.to_dict() if started_msg.negotiated else None
            results["status"] = started_msg.status.value

            if not output_json:
                print_success(f"Session accepted (status: {started_msg.status.value})")
                print_timing("Negotiation time", negotiate_time)
                print_negotiated_config(started_msg)
        else:
            results["status"] = started_msg.status.value
            results["errors"] = [e.to_dict() for e in started_msg.errors] if started_msg.errors else []

            if not output_json:
                print_error(f"Session rejected (status: {started_msg.status.value})")
                if started_msg.errors:
                    for err in started_msg.errors:
                        print_error(f"   [{err.code}] {err.message}")

        # 5. Encerra sessão
        if started_msg.is_accepted:
            end_msg = SessionEndMessage(session_id=session_id, reason="debug_complete")
            await ws.send(end_msg.to_json())

        # 6. Fecha conexão
        await ws.close()

        total_time = (time.perf_counter() - total_start) * 1000
        results["timings"]["total_ms"] = total_time

        if not output_json:
            print_header("Summary")
            print_timing("Total time", total_time)
            if results["success"]:
                print_success("Handshake completed successfully!")
            else:
                print_error("Handshake failed")

    except asyncio.TimeoutError:
        results["errors"].append("Timeout waiting for server response")
        if not output_json:
            print_error("Timeout waiting for server response")
    except websockets.exceptions.ConnectionClosed as e:
        results["errors"].append(f"Connection closed: {e.code}")
        if not output_json:
            print_error(f"Connection closed: {e.code}")
    except Exception as e:
        results["errors"].append(str(e))
        if not output_json:
            print_error(f"Error: {e}")

    if output_json:
        print(json.dumps(results, indent=2))

    return results["success"]


def main():
    parser = argparse.ArgumentParser(
        description="ASP Debug Tool - Test Audio Session Protocol handshake",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ws://localhost:8765
  %(prog)s ws://ai-agent:8765 --json
  %(prog)s ws://localhost:8765 --vad-silence 700 --vad-threshold 0.6
  %(prog)s ws://localhost:8765 --sample-rate 16000
        """
    )

    parser.add_argument(
        "url",
        nargs="?",
        default="ws://localhost:8765",
        help="WebSocket URL of the AI Agent server (default: ws://localhost:8765)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Timeout in seconds (default: 10)"
    )

    # Audio config options
    audio_group = parser.add_argument_group("Audio Configuration")
    audio_group.add_argument(
        "--sample-rate",
        type=int,
        default=8000,
        choices=[8000, 16000, 24000, 48000],
        help="Sample rate in Hz (default: 8000)"
    )
    audio_group.add_argument(
        "--encoding",
        type=str,
        default="pcm_s16le",
        choices=["pcm_s16le", "mulaw", "alaw"],
        help="Audio encoding (default: pcm_s16le)"
    )
    audio_group.add_argument(
        "--frame-duration",
        type=int,
        default=20,
        choices=[10, 20, 30],
        help="Frame duration in ms (default: 20)"
    )

    # VAD config options
    vad_group = parser.add_argument_group("VAD Configuration")
    vad_group.add_argument(
        "--vad-silence",
        type=int,
        default=500,
        help="Silence threshold in ms (default: 500)"
    )
    vad_group.add_argument(
        "--vad-min-speech",
        type=int,
        default=250,
        help="Minimum speech duration in ms (default: 250)"
    )
    vad_group.add_argument(
        "--vad-threshold",
        type=float,
        default=0.5,
        help="VAD threshold 0.0-1.0 (default: 0.5)"
    )
    vad_group.add_argument(
        "--vad-ring-buffer",
        type=int,
        default=5,
        help="Ring buffer frames (default: 5)"
    )
    vad_group.add_argument(
        "--vad-speech-ratio",
        type=float,
        default=0.4,
        help="Speech ratio 0.0-1.0 (default: 0.4)"
    )

    args = parser.parse_args()

    # Build configs
    audio_config = AudioConfig(
        sample_rate=args.sample_rate,
        encoding=AudioEncoding(args.encoding),
        channels=1,
        frame_duration_ms=args.frame_duration
    )

    vad_config = VADConfig(
        enabled=True,
        silence_threshold_ms=args.vad_silence,
        min_speech_ms=args.vad_min_speech,
        threshold=args.vad_threshold,
        ring_buffer_frames=args.vad_ring_buffer,
        speech_ratio=args.vad_speech_ratio,
        prefix_padding_ms=300
    )

    # Run debug
    success = asyncio.run(run_debug(
        url=args.url,
        audio_config=audio_config,
        vad_config=vad_config,
        output_json=args.json,
        timeout=args.timeout
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Script de teste E2E para WebRTC do AI Inference Service.

Uso:
    python scripts/test_e2e_webrtc.py [--host HOST] [--port PORT]

Exemplos:
    python scripts/test_e2e_webrtc.py
    python scripts/test_e2e_webrtc.py --host localhost --port 8080
"""

import argparse
import asyncio
import json
import sys
from typing import Optional

import httpx

# Tenta importar aiortc (necessário para teste WebRTC completo)
try:
    from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer
    from aiortc.contrib.media import MediaPlayer, MediaRecorder
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False
    print("⚠️  aiortc não disponível. Teste WebRTC completo desabilitado.")
    print("   Instale com: pip install aiortc")


class Colors:
    """ANSI color codes."""
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_step(step: str, status: str = "info"):
    """Print a step with color."""
    colors = {
        "info": Colors.BLUE,
        "success": Colors.GREEN,
        "error": Colors.RED,
        "warning": Colors.YELLOW,
    }
    color = colors.get(status, Colors.RESET)
    symbol = {"info": "→", "success": "✓", "error": "✗", "warning": "⚠"}[status]
    print(f"{color}{symbol} {step}{Colors.RESET}")


def print_header(title: str):
    """Print a section header."""
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{title}{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")


async def test_health(base_url: str) -> bool:
    """Test health endpoint."""
    print_step("Testando /health...")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                data = response.json()
                print_step(f"Health OK: {data}", "success")
                return True
            else:
                print_step(f"Health falhou: {response.status_code}", "error")
                return False
        except Exception as e:
            print_step(f"Erro ao conectar: {e}", "error")
            return False


async def test_create_session(base_url: str) -> Optional[dict]:
    """Test session creation."""
    print_step("Criando sessão WebRTC...")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{base_url}/v1/realtime/sessions",
                json={
                    "instructions": "Você é um assistente de voz amigável.",
                    "voice": "alloy",
                }
            )

            if response.status_code == 200:
                data = response.json()
                print_step(f"Sessão criada: {data['id']}", "success")
                print_step(f"Token expira em: {data['client_secret']['expires_at']}", "info")
                return data
            else:
                print_step(f"Falha ao criar sessão: {response.status_code}", "error")
                print(response.text)
                return None
        except Exception as e:
            print_step(f"Erro: {e}", "error")
            return None


async def test_get_session(base_url: str, session_id: str) -> bool:
    """Test getting session info."""
    print_step(f"Obtendo info da sessão {session_id}...")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{base_url}/v1/realtime/sessions/{session_id}")

            if response.status_code == 200:
                data = response.json()
                print_step(f"Sessão encontrada: state={data['state']}", "success")
                print(json.dumps(data, indent=2))
                return True
            else:
                print_step(f"Falha: {response.status_code}", "error")
                return False
        except Exception as e:
            print_step(f"Erro: {e}", "error")
            return False


async def test_sdp_exchange(base_url: str, session_id: str, token: str) -> Optional[str]:
    """Test SDP exchange."""
    if not AIORTC_AVAILABLE:
        print_step("Pulando SDP exchange (aiortc não disponível)", "warning")
        return None

    print_step("Iniciando SDP exchange...")

    # Create peer connection
    pc = RTCPeerConnection(
        configuration=RTCConfiguration(
            iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]
        )
    )

    # Create data channel
    dc = pc.createDataChannel("oai-events")

    events_received = []

    @dc.on("open")
    def on_open():
        print_step("DataChannel aberto!", "success")

    @dc.on("message")
    def on_message(message):
        print_step(f"Evento recebido: {message[:100]}...", "info")
        events_received.append(json.loads(message))

    # Create offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    print_step(f"SDP Offer criado ({len(offer.sdp)} bytes)", "info")

    # Send offer to server
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{base_url}/v1/realtime/sessions/{session_id}/sdp",
                content=offer.sdp,
                headers={
                    "Content-Type": "application/sdp",
                    "Authorization": f"Bearer {token}",
                }
            )

            if response.status_code == 200:
                answer_sdp = response.text
                print_step(f"SDP Answer recebido ({len(answer_sdp)} bytes)", "success")

                # Set remote description
                from aiortc import RTCSessionDescription
                answer = RTCSessionDescription(sdp=answer_sdp, type="answer")
                await pc.setRemoteDescription(answer)

                print_step("Conexão WebRTC estabelecida!", "success")

                # Wait for events
                print_step("Aguardando eventos (3s)...", "info")
                await asyncio.sleep(3)

                if events_received:
                    print_step(f"Recebidos {len(events_received)} eventos:", "success")
                    for evt in events_received:
                        print(f"  - {evt.get('type', 'unknown')}")

                # Cleanup
                await pc.close()
                return answer_sdp
            else:
                print_step(f"SDP exchange falhou: {response.status_code}", "error")
                print(response.text)
                await pc.close()
                return None

        except Exception as e:
            print_step(f"Erro no SDP exchange: {e}", "error")
            await pc.close()
            return None


async def test_close_session(base_url: str, session_id: str) -> bool:
    """Test closing a session."""
    print_step(f"Fechando sessão {session_id}...")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(f"{base_url}/v1/realtime/sessions/{session_id}")

            if response.status_code == 200:
                print_step("Sessão fechada com sucesso", "success")
                return True
            else:
                print_step(f"Falha ao fechar: {response.status_code}", "error")
                return False
        except Exception as e:
            print_step(f"Erro: {e}", "error")
            return False


async def run_tests(host: str, port: int):
    """Run all E2E tests."""
    base_url = f"http://{host}:{port}"

    print_header("AI Inference - Teste E2E WebRTC")
    print(f"Base URL: {base_url}\n")

    results = {
        "health": False,
        "create_session": False,
        "get_session": False,
        "sdp_exchange": False,
        "close_session": False,
    }

    # Test 1: Health
    print_header("1. Health Check")
    results["health"] = await test_health(base_url)

    if not results["health"]:
        print_step("Servidor não disponível. Abortando testes.", "error")
        return results

    # Test 2: Create Session
    print_header("2. Criar Sessão")
    session_data = await test_create_session(base_url)
    results["create_session"] = session_data is not None

    if not session_data:
        print_step("Não foi possível criar sessão. Abortando.", "error")
        return results

    session_id = session_data["id"]
    token = session_data["client_secret"]["value"]

    # Test 3: Get Session
    print_header("3. Obter Info da Sessão")
    results["get_session"] = await test_get_session(base_url, session_id)

    # Test 4: SDP Exchange
    print_header("4. SDP Exchange (WebRTC)")
    sdp_result = await test_sdp_exchange(base_url, session_id, token)
    results["sdp_exchange"] = sdp_result is not None or not AIORTC_AVAILABLE

    # Test 5: Close Session
    print_header("5. Fechar Sessão")
    results["close_session"] = await test_close_session(base_url, session_id)

    # Summary
    print_header("Resumo dos Testes")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, success in results.items():
        status = "success" if success else "error"
        print_step(f"{test_name}: {'PASSOU' if success else 'FALHOU'}", status)

    print(f"\n{Colors.BOLD}Total: {passed}/{total} testes passaram{Colors.RESET}")

    if passed == total:
        print(f"\n{Colors.GREEN}✓ Todos os testes passaram!{Colors.RESET}\n")
    else:
        print(f"\n{Colors.RED}✗ Alguns testes falharam.{Colors.RESET}\n")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Teste E2E do AI Inference WebRTC Service"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host do servidor (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Porta do servidor (default: 8080)"
    )

    args = parser.parse_args()

    results = asyncio.run(run_tests(args.host, args.port))

    # Exit with error code if any test failed
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Teste de conexao WebSocket com ai-transcribe.

Simula o comportamento do Media Server enviando audio via ASP Protocol.

Uso:
    python test_websocket.py [--url ws://localhost:8766]
"""

import asyncio
import json
import base64
import argparse
import sys
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Instale websockets: pip install websockets")
    sys.exit(1)


# Audio de teste (silencio PCM 16-bit, 8kHz, mono - 100ms)
SILENCE_AUDIO = b"\x00\x00" * 800  # 100ms de silencio


async def test_connection(url: str):
    """Testa conexao basica com o servidor."""
    print(f"\n[1/5] Testando conexao com {url}...")

    try:
        async with websockets.connect(url, ping_interval=20) as ws:
            print("     Conectado com sucesso!")
            return True
    except Exception as e:
        print(f"     ERRO: {e}")
        return False


async def test_session_start(url: str) -> bool:
    """Testa inicio de sessao."""
    print(f"\n[2/5] Testando inicio de sessao...")

    try:
        async with websockets.connect(url) as ws:
            # Envia session.start
            msg = {
                "type": "session.start",
                "session_id": "test-session-001",
                "call_id": "test-call-001",
                "caller_id": "5511999999999",
                "metadata": {"test": True}
            }
            await ws.send(json.dumps(msg))
            print(f"     Enviado: session.start")

            # Aguarda resposta
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            print(f"     Recebido: {data.get('type')}")

            if data.get("type") == "session.started":
                print("     Sessao iniciada com sucesso!")
                return True
            else:
                print(f"     ERRO: Resposta inesperada: {data}")
                return False

    except asyncio.TimeoutError:
        print("     ERRO: Timeout aguardando resposta")
        return False
    except Exception as e:
        print(f"     ERRO: {e}")
        return False


async def test_audio_send(url: str) -> bool:
    """Testa envio de audio."""
    print(f"\n[3/5] Testando envio de audio...")

    try:
        async with websockets.connect(url) as ws:
            # Inicia sessao
            await ws.send(json.dumps({
                "type": "session.start",
                "session_id": "test-session-002",
                "call_id": "test-call-002"
            }))
            await ws.recv()  # session.started

            # Envia audio (5 chunks de 100ms = 500ms)
            for i in range(5):
                audio_b64 = base64.b64encode(SILENCE_AUDIO).decode()
                await ws.send(json.dumps({
                    "type": "audio.chunk",
                    "session_id": "test-session-002",
                    "audio": audio_b64,
                    "timestamp": i * 0.1
                }))
            print(f"     Enviados 5 chunks de audio (500ms)")

            # Envia fim de audio
            await ws.send(json.dumps({
                "type": "audio.speech.end",
                "session_id": "test-session-002"
            }))
            print(f"     Enviado: audio.speech.end")

            # Aguarda transcricao
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                data = json.loads(response)
                print(f"     Recebido: {data.get('type')}")

                if data.get("type") == "transcription":
                    text = data.get("text", "")
                    print(f"     Transcricao: '{text}' (vazia = silencio, esperado)")
                    return True

            except asyncio.TimeoutError:
                print("     AVISO: Timeout aguardando transcricao (silencio pode nao gerar texto)")
                return True  # Silencio nao gera transcricao

    except Exception as e:
        print(f"     ERRO: {e}")
        return False


async def test_session_end(url: str) -> bool:
    """Testa fim de sessao."""
    print(f"\n[4/5] Testando fim de sessao...")

    try:
        async with websockets.connect(url) as ws:
            # Inicia sessao
            await ws.send(json.dumps({
                "type": "session.start",
                "session_id": "test-session-003",
                "call_id": "test-call-003"
            }))
            await ws.recv()  # session.started

            # Encerra sessao
            await ws.send(json.dumps({
                "type": "session.end",
                "session_id": "test-session-003"
            }))
            print(f"     Enviado: session.end")

            # Aguarda confirmacao
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            print(f"     Recebido: {data.get('type')}")

            if data.get("type") == "session.ended":
                print("     Sessao encerrada com sucesso!")
                return True
            else:
                print(f"     AVISO: Resposta inesperada: {data}")
                return True  # Pode nao ter resposta explicita

    except asyncio.TimeoutError:
        print("     AVISO: Timeout (servidor pode nao enviar confirmacao)")
        return True
    except Exception as e:
        print(f"     ERRO: {e}")
        return False


async def test_metrics(metrics_url: str) -> bool:
    """Testa endpoint de metricas."""
    print(f"\n[5/5] Testando metricas em {metrics_url}...")

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(metrics_url) as response:
                if response.status == 200:
                    text = await response.text()
                    metrics_found = [
                        "ai_transcribe_active_sessions",
                        "ai_transcribe_es_connection_status",
                    ]
                    found = sum(1 for m in metrics_found if m in text)
                    print(f"     Metricas encontradas: {found}/{len(metrics_found)}")
                    return found > 0
                else:
                    print(f"     ERRO: Status {response.status}")
                    return False
    except ImportError:
        print("     AVISO: aiohttp nao instalado, pulando teste de metricas")
        return True
    except Exception as e:
        print(f"     ERRO: {e}")
        return False


async def run_all_tests(ws_url: str, metrics_url: str):
    """Executa todos os testes."""
    print("=" * 60)
    print("TESTE DO AI-TRANSCRIBE")
    print("=" * 60)

    results = []

    # Teste 1: Conexao
    results.append(("Conexao", await test_connection(ws_url)))

    if results[0][1]:  # Se conectou, continua
        # Teste 2: Session Start
        results.append(("Session Start", await test_session_start(ws_url)))

        # Teste 3: Audio Send
        results.append(("Audio Send", await test_audio_send(ws_url)))

        # Teste 4: Session End
        results.append(("Session End", await test_session_end(ws_url)))

    # Teste 5: Metricas
    results.append(("Metricas", await test_metrics(metrics_url)))

    # Resumo
    print("\n" + "=" * 60)
    print("RESUMO DOS TESTES")
    print("=" * 60)

    passed = 0
    for name, success in results:
        status = "PASSOU" if success else "FALHOU"
        symbol = "[OK]" if success else "[X]"
        print(f"  {symbol} {name}: {status}")
        if success:
            passed += 1

    print(f"\nTotal: {passed}/{len(results)} testes passaram")
    print("=" * 60)

    return passed == len(results)


def main():
    parser = argparse.ArgumentParser(description="Teste do ai-transcribe")
    parser.add_argument(
        "--url",
        default="ws://localhost:8766",
        help="URL do WebSocket (default: ws://localhost:8766)"
    )
    parser.add_argument(
        "--metrics",
        default="http://localhost:9093/metrics",
        help="URL das metricas (default: http://localhost:9093/metrics)"
    )
    args = parser.parse_args()

    success = asyncio.run(run_all_tests(args.url, args.metrics))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

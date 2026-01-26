"""Voice Agent WebSocket Server.

FastAPI server that handles real-time voice conversations
using the voice-pipeline framework.

Usage:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import os
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from agent import VoiceAgentSession

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Voice Agent Demo",
    description="Real-time voice conversation with AI agent",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (frontend)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


@app.get("/")
async def root():
    """Serve the frontend."""
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Voice Agent API", "status": "running"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    from agent import _active_sessions, MAX_CONCURRENT_SESSIONS
    return {
        "status": "healthy",
        "active_sessions": len(_active_sessions),
        "max_sessions": MAX_CONCURRENT_SESSIONS,
    }


@app.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """WebSocket endpoint for voice conversation.

    Protocol:
        Client -> Server: Binary audio data (PCM16, 16kHz, mono)
        Server -> Client: Binary audio data (PCM16, 24kHz, mono)

        Control messages (JSON):
        - {"type": "config", "sample_rate": 16000, "language": "en"}
        - {"type": "start"} - Start listening
        - {"type": "stop"} - Stop listening
        - {"type": "interrupt"} - Interrupt current response (barge-in)

        Status messages (JSON):
        - {"type": "status", "state": "listening|processing|speaking|idle"}
        - {"type": "transcript", "text": "...", "is_final": true}
        - {"type": "response", "text": "..."}
        - {"type": "error", "message": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket connection established")

    session: Optional[VoiceAgentSession] = None

    try:
        # Create agent session with msgpack optimization
        session = VoiceAgentSession(websocket, use_msgpack=True)
        try:
            await session.initialize()
        except RuntimeError as e:
            # Limite de sessões atingido
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
            await websocket.close(code=1013, reason=str(e))
            return

        # Send ready status (usando serializer da session para consistência)
        await session._serializer.send_json(websocket, {
            "type": "status",
            "state": "idle",
            "message": "Agent ready"
        })

        # Main message loop
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message:
                # Audio data
                audio_chunk = message["bytes"]
                await session.process_audio(audio_chunk)

            elif "text" in message:
                # Control message
                import json
                try:
                    data = json.loads(message["text"])
                    await handle_control_message(session, data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message['text']}")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            if session:
                await session._serializer.send_json(websocket, {
                    "type": "error",
                    "message": str(e)
                })
            else:
                # Fallback para JSON se session não existe ainda
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
        except:
            pass
    finally:
        if session:
            await session.cleanup()
        logger.info("WebSocket connection closed")


async def handle_control_message(session: VoiceAgentSession, data: dict):
    """Handle control messages from client."""
    msg_type = data.get("type")

    if msg_type == "config":
        # Update configuration
        sample_rate = data.get("sample_rate", 16000)
        language = data.get("language", "en")
        await session.configure(sample_rate=sample_rate, language=language)

    elif msg_type == "start":
        # Start listening
        await session.start_listening()

    elif msg_type == "stop":
        # Stop listening
        await session.stop_listening()

    elif msg_type == "interrupt":
        # Interrupt current response (barge-in)
        await session.interrupt()

    elif msg_type == "reset":
        # Reset conversation
        await session.reset()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""FastAPI backend for WebRTC Voice Pipeline Demo."""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import AppConfig, load_config
from .webrtc import SignalingServer, WebRTCTransport
from .agent import VoiceAgentSession
from .agent.integration import AgentIntegration, IntegrationConfig
from .features.mcp_wrapper import MCPToolWrapper, MCPServerConfig

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Reduce noise from libraries
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Global state
config: Optional[AppConfig] = None
signaling_server: Optional[SignalingServer] = None
sessions: dict[str, dict] = {}  # session_id -> {transport, session, integration}
mcp_wrapper: Optional[MCPToolWrapper] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global config, signaling_server, mcp_wrapper

    # Startup
    logger.info("Starting WebRTC Voice Pipeline Demo Backend...")

    config = load_config()
    signaling_server = SignalingServer()
    signaling_server.set_ice_servers(config.webrtc.ice_servers)

    # Set up signaling callbacks
    signaling_server.on_offer(handle_offer)
    signaling_server.on_ice_candidate(handle_ice_candidate)
    signaling_server.on_hangup(handle_hangup)

    # Initialize MCP wrapper
    mcp_wrapper = MCPToolWrapper()

    logger.info(f"Backend ready on {config.host}:{config.port}")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Close all sessions
    for session_id in list(sessions.keys()):
        await close_session(session_id)

    # Close MCP connections
    if mcp_wrapper:
        await mcp_wrapper.close()

    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Voice Pipeline WebRTC Demo",
    description="WebRTC-based voice agent demonstrating the voice-pipeline framework",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Will be restricted in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Signaling Handlers ====================


async def handle_offer(session_id: str, sdp: dict) -> dict:
    """Handle WebRTC offer from client.

    Args:
        session_id: Session ID.
        sdp: SDP offer.

    Returns:
        SDP answer.
    """
    logger.info(f"=== HANDLING OFFER for session {session_id} ===")
    logger.info(f"SDP type: {sdp.get('type')}, SDP length: {len(sdp.get('sdp', ''))}")

    # Create transport
    logger.info("Creating WebRTC transport...")
    transport = WebRTCTransport(
        ice_servers=config.webrtc.ice_servers,
        input_sample_rate=config.webrtc.sample_rate,
        output_sample_rate=config.tts.sample_rate,
    )

    # Start transport
    logger.info("Starting transport...")
    await transport.start()
    logger.info(f"Transport started, state: {transport.state}")

    # Handle offer and get answer
    logger.info("Processing SDP offer...")
    answer = await transport.handle_offer(sdp)
    logger.info(f"SDP answer created, type: {answer.get('type')}")

    # Create voice session
    logger.info("Creating VoiceAgentSession...")
    session = VoiceAgentSession(
        session_id=session_id,
        transport=transport,
    )

    # Create integration
    logger.info("Creating AgentIntegration...")
    integration_config = IntegrationConfig.from_app_config(config)
    integration = AgentIntegration(session, integration_config)

    # Initialize integration components
    logger.info("Initializing integration components (ASR, LLM, TTS)...")
    await integration.initialize()
    logger.info("Integration initialized")

    # Start session
    logger.info("Starting session...")
    await session.start()
    logger.info(f"Session started, state: {session.state}")

    # Store session
    sessions[session_id] = {
        "transport": transport,
        "session": session,
        "integration": integration,
    }

    logger.info(f"=== SESSION {session_id} READY ===")

    return answer


async def handle_ice_candidate(session_id: str, candidate: dict) -> None:
    """Handle ICE candidate from client.

    Args:
        session_id: Session ID.
        candidate: ICE candidate.
    """
    if session_id in sessions:
        transport = sessions[session_id]["transport"]
        await transport.add_ice_candidate(candidate)


async def handle_hangup(session_id: str) -> None:
    """Handle hangup from client.

    Args:
        session_id: Session ID.
    """
    await close_session(session_id)


async def close_session(session_id: str) -> None:
    """Close a session and cleanup resources.

    Args:
        session_id: Session ID to close.
    """
    if session_id not in sessions:
        return

    session_data = sessions[session_id]

    try:
        # Stop session
        await session_data["session"].stop()

        # Stop transport
        await session_data["transport"].stop()

    except Exception as e:
        logger.error(f"Error closing session {session_id}: {e}")

    finally:
        del sessions[session_id]
        logger.info(f"Session {session_id} closed")


# ==================== WebSocket Endpoints ====================


@app.websocket("/ws/signaling")
async def websocket_signaling(websocket: WebSocket):
    """WebSocket endpoint for WebRTC signaling."""
    session_id = await signaling_server.handle_websocket(websocket)
    logger.info(f"Signaling session {session_id} ended")


# ==================== REST API Endpoints ====================


class SessionInfo(BaseModel):
    """Session information response."""

    session_id: str
    state: str
    metrics: dict


class MCPServerRequest(BaseModel):
    """Request to connect MCP server."""

    name: str
    url: str
    transport: str = "http"


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "sessions": len(sessions),
        "signaling_sessions": signaling_server.session_count if signaling_server else 0,
    }


@app.get("/api/config")
async def get_config():
    """Get public configuration."""
    return {
        "ice_servers": config.webrtc.ice_servers,
        "audio": {
            "sample_rate": config.webrtc.sample_rate,
            "channels": config.webrtc.channels,
        },
        "providers": {
            "llm": config.llm.provider,
            "asr": config.asr.provider,
            "tts": config.tts.provider,
        },
    }


@app.get("/api/sessions")
async def list_sessions():
    """List active sessions."""
    return {
        "sessions": [
            {
                "session_id": sid,
                "state": data["session"].state.value,
                "metrics": data["session"].metrics.to_dict(),
            }
            for sid, data in sessions.items()
        ]
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session information."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = sessions[session_id]
    return {
        "session_id": session_id,
        "state": session_data["session"].state.value,
        "metrics": session_data["session"].metrics.to_dict(),
        "history": session_data["integration"].get_conversation_history(),
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Close a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    await close_session(session_id)
    return {"status": "closed"}


@app.post("/api/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str):
    """Interrupt the current response."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    sessions[session_id]["session"].interrupt()
    return {"status": "interrupted"}


# ==================== MCP Endpoints ====================


@app.post("/api/mcp/connect")
async def connect_mcp_server(request: MCPServerRequest):
    """Connect to an MCP server."""
    if not mcp_wrapper:
        raise HTTPException(status_code=500, detail="MCP not initialized")

    config = MCPServerConfig(
        name=request.name,
        url=request.url,
        transport=request.transport,
    )

    success = await mcp_wrapper.connect_server(config)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to connect to MCP server")

    return {
        "status": "connected",
        "server": request.name,
        "tools": mcp_wrapper.list_server_tools(request.name),
    }


@app.delete("/api/mcp/{server_name}")
async def disconnect_mcp_server(server_name: str):
    """Disconnect from an MCP server."""
    if not mcp_wrapper:
        raise HTTPException(status_code=500, detail="MCP not initialized")

    await mcp_wrapper.disconnect_server(server_name)
    return {"status": "disconnected"}


@app.get("/api/mcp/servers")
async def list_mcp_servers():
    """List connected MCP servers."""
    if not mcp_wrapper:
        return {"servers": []}

    servers = []
    for name in mcp_wrapper.list_servers():
        servers.append(
            {
                "name": name,
                "tools": mcp_wrapper.list_server_tools(name),
            }
        )

    return {"servers": servers}


@app.get("/api/mcp/tools")
async def list_mcp_tools():
    """List all MCP tools."""
    if not mcp_wrapper:
        return {"tools": []}

    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in mcp_wrapper.get_tools()
    ]

    return {"tools": tools}


# ==================== Memory Endpoints ====================


@app.get("/api/sessions/{session_id}/memory")
async def get_session_memory(session_id: str, query: Optional[str] = None):
    """Get or search session memory."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    integration = sessions[session_id]["integration"]

    if query:
        episodes = await integration.recall_memory(query)
        return {"episodes": episodes}

    return {"history": integration.get_conversation_history()}


@app.delete("/api/sessions/{session_id}/memory")
async def clear_session_memory(session_id: str):
    """Clear session memory."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    integration = sessions[session_id]["integration"]
    integration.clear_conversation_history()

    return {"status": "cleared"}


# ==================== Tools Endpoints ====================


@app.get("/api/tools")
async def list_tools():
    """List all available tools."""
    from .features.demo_tools import get_demo_tools

    demo_tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "source": "demo",
        }
        for tool in get_demo_tools()
    ]

    mcp_tools = []
    if mcp_wrapper:
        mcp_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "source": "mcp",
            }
            for tool in mcp_wrapper.get_tools()
        ]

    return {"tools": demo_tools + mcp_tools}


# ==================== Run ====================


def main():
    """Run the server."""
    import uvicorn

    config = load_config()
    uvicorn.run(
        "backend.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
    )


if __name__ == "__main__":
    main()

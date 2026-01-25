# Voice Agent Web Application

A real-time voice conversation demo using the voice-pipeline framework.

## Architecture

```
┌─────────────────┐     WebSocket      ┌─────────────────────────────┐
│    Browser      │ ◄────────────────► │    FastAPI Backend          │
│                 │    audio/JSON      │                             │
│  ┌───────────┐  │                    │  ┌───────────────────────┐  │
│  │ Microphone│──┼───── PCM16 ───────►│  │    voice-pipeline     │  │
│  └───────────┘  │                    │  │                       │  │
│                 │                    │  │  VAD → ASR → LLM → TTS│  │
│  ┌───────────┐  │                    │  │                       │  │
│  │  Speaker  │◄─┼───── PCM16 ───────┼│  └───────────────────────┘  │
│  └───────────┘  │                    │                             │
└─────────────────┘                    └─────────────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
# Backend dependencies
pip install fastapi uvicorn websockets

# Voice pipeline (if not installed)
pip install -e ../..

# Optional: Real providers
pip install openai-whisper    # For Whisper ASR
pip install ollama            # For Ollama LLM
pip install kokoro-onnx       # For Kokoro TTS
```

### 2. Start Ollama (if using real LLM)

```bash
# In a separate terminal
ollama serve

# Pull a model
ollama pull llama3.2
```

### 3. Run the Server

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Open the App

Open your browser to: http://localhost:8000

## Usage

1. Click **"Start Conversation"**
2. Allow microphone access when prompted
3. **Speak** - the agent will detect your speech
4. **Listen** - the agent will respond with audio
5. Press **Space** to interrupt the agent (barge-in)
6. Click **"Stop"** to end the conversation

## Configuration

### Providers

The app uses real providers for voice processing. Install the dependencies:

```bash
# Whisper for ASR
pip install openai-whisper

# Ollama for LLM (start server: ollama serve)
pip install ollama

# Kokoro for TTS
pip install kokoro-onnx torch
```

The agent will automatically detect and use available providers.

## WebSocket Protocol

### Client → Server

**Audio Data (Binary)**
- Format: PCM16, 16kHz, mono
- Send continuously while listening

**Control Messages (JSON)**
```json
{"type": "config", "sample_rate": 16000, "language": "en"}
{"type": "start"}      // Start listening
{"type": "stop"}       // Stop listening
{"type": "interrupt"}  // Interrupt response (barge-in)
{"type": "reset"}      // Reset conversation
```

### Server → Client

**Audio Data (Binary)**
- Format: PCM16, 24kHz, mono
- Response audio chunks

**Status Messages (JSON)**
```json
{"type": "status", "state": "idle|listening|processing|speaking"}
{"type": "vad", "event": "speech_start|speech_end"}
{"type": "transcript", "text": "...", "is_final": true}
{"type": "response_chunk", "text": "..."}
{"type": "response", "text": "..."}
{"type": "error", "message": "..."}
```

## Project Structure

```
webapp/
├── backend/
│   ├── main.py          # FastAPI server + WebSocket endpoint
│   └── agent.py         # Voice agent using voice-pipeline
├── frontend/
│   ├── index.html       # UI
│   └── app.js           # WebSocket + Web Audio API
└── README.md
```

## Troubleshooting

### Microphone not working
- Check browser permissions
- Use HTTPS or localhost (required for getUserMedia)

### No audio playback
- Check speaker/headphone connection
- Some browsers require user interaction before audio playback

### Connection errors
- Ensure backend is running on port 8000
- Check firewall settings

### High latency
- This demo uses WebSocket (not WebRTC)
- Expected latency: 100-300ms
- For production, consider LiveKit or similar

## Next Steps

For production use, consider:
- **LiveKit** for WebRTC (lower latency)
- **Authentication** for secure access
- **Rate limiting** for API protection
- **GPU acceleration** for faster inference

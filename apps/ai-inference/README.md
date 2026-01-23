# AI Inference Service

OpenAI Realtime API compatible inference service for voice AI applications.

## Features

- WebSocket-based Realtime API at `/v1/realtime`
- Session management with configurable limits
- Input audio buffering and streaming
- REST endpoints for health checks and monitoring

## Quick Start

### Installation

```bash
cd apps/ai-inference
pip install -e ".[dev]"
```

### Running the Server

```bash
# Development mode
uvicorn src.main:app --reload --port 8080

# Or using the CLI
python -m src.main
```

### Running Tests

```bash
pytest tests/ -v
```

## API Endpoints

### WebSocket

- `ws://localhost:8080/v1/realtime` - Realtime API endpoint

### REST

- `GET /health` - Health check
- `GET /metrics` - Service metrics
- `GET /sessions` - List active sessions
- `GET /sessions/{id}` - Get session details
- `DELETE /sessions/{id}` - Delete session

## WebSocket Protocol

The service implements the OpenAI Realtime API protocol.

### Client Events

| Event | Description |
|-------|-------------|
| `session.update` | Update session configuration |
| `input_audio_buffer.append` | Append audio to buffer |
| `input_audio_buffer.commit` | Commit audio buffer |
| `input_audio_buffer.clear` | Clear audio buffer |
| `conversation.item.create` | Create conversation item |
| `conversation.item.truncate` | Truncate conversation |
| `conversation.item.delete` | Delete conversation item |
| `response.create` | Request model response |
| `response.cancel` | Cancel active response |

### Server Events

| Event | Description |
|-------|-------------|
| `session.created` | Session was created |
| `session.updated` | Session was updated |
| `conversation.created` | Conversation was created |
| `input_audio_buffer.committed` | Audio was committed |
| `input_audio_buffer.cleared` | Audio was cleared |
| `response.created` | Response started |
| `response.done` | Response completed |
| `error` | Error occurred |

## Configuration

Environment variables (prefix: `AI_INFERENCE_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | 0.0.0.0 | Server host |
| `PORT` | 8080 | Server port |
| `MAX_SESSIONS` | 100 | Max concurrent sessions |
| `SESSION_TIMEOUT_SECONDS` | 3600 | Session timeout |
| `LOG_LEVEL` | INFO | Logging level |

## Example Usage

```python
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("ws://localhost:8080/v1/realtime") as ws:
        # Receive session.created
        msg = await ws.recv()
        print(json.loads(msg))

        # Update session
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "instructions": "You are a helpful assistant"
            }
        }))

        # Receive session.updated
        msg = await ws.recv()
        print(json.loads(msg))

asyncio.run(main())
```

## Docker

```bash
# Build
docker build -t ai-inference .

# Run
docker run -p 8080:8080 ai-inference
```

## License

MIT

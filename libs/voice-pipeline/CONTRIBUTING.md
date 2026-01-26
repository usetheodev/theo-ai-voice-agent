# Contributing to Voice Pipeline

Thank you for your interest in contributing to Voice Pipeline! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
# Clone the repository
git clone https://github.com/example/voice-pipeline.git
cd voice-pipeline

# Install dev dependencies
pip install -e ".[dev]"

# Or with uv
uv pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -q

# Run without network-dependent tests
python -m pytest tests/ -q -k "not ollama and not integration"

# Run with coverage
python -m pytest tests/ --cov=src/voice_pipeline --cov-report=term-missing
```

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and [Black](https://black.readthedocs.io/) for formatting.

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type checking
mypy src/voice_pipeline/
```

### Guidelines

- **Type hints** are required for all public functions and methods.
- **Docstrings** follow Google style and must be in **English**.
- All user-facing strings (error messages, logs, docstrings) must be in **English**.
- Examples may include localized variants via environment variables.

## Adding a Provider

Voice Pipeline uses a decorator-based registry for providers. Here's how to add a new one:

### 1. Create the provider file

```python
# src/voice_pipeline/providers/tts/my_tts.py

from dataclasses import dataclass
from typing import Optional

from voice_pipeline.interfaces.tts import AudioChunk, TTSInterface
from voice_pipeline.providers.base import BaseProvider, ProviderConfig
from voice_pipeline.providers.registry import register_tts
from voice_pipeline.providers.types import TTSCapabilities


@dataclass
class MyTTSConfig(ProviderConfig):
    """Configuration for MyTTS provider."""
    voice: str = "default"
    sample_rate: int = 24000


@register_tts(
    name="my-tts",
    capabilities=TTSCapabilities(
        streaming=True,
        languages=["en", "es"],
        voices=["default", "voice_a", "voice_b"],
    ),
    description="My custom TTS provider.",
)
class MyTTSProvider(BaseProvider, TTSInterface):
    """My TTS provider implementation."""

    provider_name: str = "my-tts"
    name: str = "MyTTS"

    def __init__(self, config: Optional[MyTTSConfig] = None, **kwargs):
        config = config or MyTTSConfig()
        super().__init__(config=config, **kwargs)
        self._tts_config = config

    async def connect(self) -> None:
        await super().connect()
        # Initialize your TTS engine here

    async def disconnect(self) -> None:
        # Clean up resources
        await super().disconnect()

    async def synthesize(self, text: str, **kwargs) -> bytes:
        # Implement synthesis
        ...

    async def synthesize_stream(self, text_stream, **kwargs):
        # Implement streaming synthesis
        async for text in text_stream:
            audio = await self.synthesize(text, **kwargs)
            yield AudioChunk(
                data=audio,
                sample_rate=self._tts_config.sample_rate,
            )
```

### 2. Register in `__init__.py`

Add your provider to `src/voice_pipeline/providers/tts/__init__.py`.

### 3. Write tests

Follow the pattern in `tests/test_provider_tts_kokoro.py`.

## Testing

### Test Structure

- `tests/test_*.py` — Unit tests (no external dependencies)
- Integration tests are marked with `@pytest.mark.integration`

### Mocking Providers

```python
from unittest.mock import AsyncMock, MagicMock

# Mock a TTS provider
mock_tts = AsyncMock()
mock_tts.synthesize.return_value = b"\x00" * 1000
mock_tts.sample_rate = 24000
```

## PR Process

1. **Branch naming**: `feature/description`, `fix/description`, `docs/description`
2. **Commit style**: Use conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
3. **Tests**: All new code must have tests. All tests must pass.
4. **Documentation**: Update docstrings for any changed public API.
5. **No PT-BR in core**: All code in `src/` must be in English.

## Architecture Overview

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed architecture documentation.

## Questions?

Open an issue on GitHub for questions, feature requests, or bug reports.

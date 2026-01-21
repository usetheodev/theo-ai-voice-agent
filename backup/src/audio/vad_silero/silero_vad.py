"""
Silero VAD - ML-based Voice Activity Detection

ONNX-based VAD using Silero pre-trained model from Silero Team.
Provides 90%+ accuracy on speech detection.

Features:
- ONNX model (~3MB) with CPU inference
- Supports 8kHz and 16kHz sample rates
- State management with periodic resets
- Frame-level voice confidence (0.0-1.0)

Technical Details:
- Model: Silero VAD v5 (ONNX format)
- Input: 256 samples @ 8kHz OR 512 samples @ 16kHz
- Output: Voice probability (0.0-1.0)
- Latency: <1ms per frame on modern CPU

Pattern: Pipecat AI SileroVADAnalyzer (vad/silero.py)
Model: https://github.com/snakers4/silero-vad
License: MIT
"""

import logging
import time
from enum import Enum
from typing import Optional, Callable
import numpy as np

# ONNX Runtime (optional dependency - graceful fallback)
try:
    import onnxruntime
    ONNX_AVAILABLE = True
except ImportError:
    onnxruntime = None
    ONNX_AVAILABLE = False


# Model reset interval (prevents memory growth)
MODEL_RESET_INTERVAL = 5.0  # seconds


class VADState(Enum):
    """Voice Activity Detection states"""
    SILENCE = "silence"
    SPEECH = "speech"
    PENDING_END = "pending_end"


class SileroOnnxModel:
    """
    ONNX runtime wrapper for Silero VAD model.

    Handles model inference with state management.
    """

    def __init__(self, model_path: str, force_cpu: bool = True):
        """
        Initialize Silero ONNX model.

        Args:
            model_path: Path to silero_vad.onnx file
            force_cpu: Force CPU execution provider (recommended for latency)
        """
        if not ONNX_AVAILABLE:
            raise ImportError(
                "onnxruntime not available. Install: pip install onnxruntime"
            )

        # ONNX session options (single-threaded for low latency)
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1

        # Create inference session
        if force_cpu and "CPUExecutionProvider" in onnxruntime.get_available_providers():
            self.session = onnxruntime.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
                sess_options=opts
            )
        else:
            self.session = onnxruntime.InferenceSession(model_path, sess_options=opts)

        self.reset_states()
        self.supported_sample_rates = [8000, 16000]

    def reset_states(self, batch_size: int = 1):
        """
        Reset internal model states.

        Args:
            batch_size: Batch size for state initialization
        """
        self._state = np.zeros((2, batch_size, 128), dtype=np.float32)
        self._context = np.zeros((batch_size, 0), dtype=np.float32)
        self._last_sr = 0
        self._last_batch_size = 0

    def _validate_input(self, audio: np.ndarray, sample_rate: int):
        """Validate and preprocess input audio."""
        # Ensure 2D array (batch, samples)
        if audio.ndim == 1:
            audio = np.expand_dims(audio, 0)
        if audio.ndim > 2:
            raise ValueError(f"Too many dimensions for input audio: {audio.ndim}")

        # Validate sample rate
        if sample_rate not in self.supported_sample_rates:
            raise ValueError(
                f"Unsupported sample rate: {sample_rate}. "
                f"Supported: {self.supported_sample_rates}"
            )

        # Validate audio length
        if sample_rate / audio.shape[1] > 31.25:
            raise ValueError("Input audio chunk is too short")

        return audio, sample_rate

    def __call__(self, audio: np.ndarray, sample_rate: int) -> float:
        """
        Process audio and return voice probability.

        Args:
            audio: Audio samples (float32, normalized to [-1, 1])
            sample_rate: Sample rate (8000 or 16000)

        Returns:
            Voice probability (0.0-1.0)
        """
        audio, sample_rate = self._validate_input(audio, sample_rate)

        # Required number of samples
        num_samples = 512 if sample_rate == 16000 else 256

        if audio.shape[-1] != num_samples:
            raise ValueError(
                f"Expected {num_samples} samples for {sample_rate} Hz, "
                f"got {audio.shape[-1]}"
            )

        batch_size = audio.shape[0]
        context_size = 64 if sample_rate == 16000 else 32

        # Reset states if needed
        if not self._last_batch_size:
            self.reset_states(batch_size)
        if self._last_sr and self._last_sr != sample_rate:
            self.reset_states(batch_size)
        if self._last_batch_size and self._last_batch_size != batch_size:
            self.reset_states(batch_size)

        # Initialize context if empty
        if self._context.shape[1] == 0:
            self._context = np.zeros((batch_size, context_size), dtype=np.float32)

        # Concatenate context with input
        audio_with_context = np.concatenate((self._context, audio), axis=1)

        # Run inference
        ort_inputs = {
            "input": audio_with_context,
            "state": self._state,
            "sr": np.array(sample_rate, dtype=np.int64)
        }
        ort_outputs = self.session.run(None, ort_inputs)
        out, state = ort_outputs

        # Update state and context
        self._state = state
        self._context = audio_with_context[..., -context_size:]
        self._last_sr = sample_rate
        self._last_batch_size = batch_size

        return float(out[0])


class SileroVAD:
    """
    Silero VAD - ML-based Voice Activity Detection

    High-accuracy VAD using pre-trained ONNX model.

    Usage:
        vad = SileroVAD(
            sample_rate=8000,
            confidence_threshold=0.5,
            on_speech_start=lambda: print("Speech started"),
            on_speech_end=lambda: print("Speech ended")
        )

        # Process audio frames (256 samples @ 8kHz OR 512 samples @ 16kHz)
        is_speech = vad.process_frame(pcm_data)

    Note: Silero VAD requires specific frame sizes:
        - 8kHz: 256 samples (32ms frames)
        - 16kHz: 512 samples (32ms frames)
    """

    def __init__(self,
                 sample_rate: int = 8000,
                 confidence_threshold: float = 0.5,
                 start_frames: int = 3,
                 stop_frames: int = 10,
                 min_speech_frames: int = 5,
                 model_path: Optional[str] = None,
                 on_speech_start: Optional[Callable] = None,
                 on_speech_end: Optional[Callable] = None):
        """
        Initialize Silero VAD.

        Args:
            sample_rate: Audio sample rate (8000 or 16000 Hz)
            confidence_threshold: Voice confidence threshold (0.0-1.0)
            start_frames: Frames to confirm speech start
            stop_frames: Frames to confirm speech end
            min_speech_frames: Minimum frames to consider valid speech
            model_path: Path to silero_vad.onnx (auto-download if None)
            on_speech_start: Callback when speech starts
            on_speech_end: Callback when speech ends
        """
        self.logger = logging.getLogger("ai-voice-agent.audio.vad_silero")

        if sample_rate not in [8000, 16000]:
            raise ValueError(f"Sample rate must be 8000 or 16000 Hz, got {sample_rate}")

        self.sample_rate = sample_rate
        self.confidence_threshold = confidence_threshold
        self.start_frames = start_frames
        self.stop_frames = stop_frames
        self.min_speech_frames = min_speech_frames

        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end

        # Frame size for Silero VAD
        self.frame_size = 512 if sample_rate == 16000 else 256

        # Load model
        if model_path is None:
            model_path = self._get_default_model_path()

        if not ONNX_AVAILABLE:
            self.logger.error(
                "ONNX Runtime not available (pip install onnxruntime). "
                "Silero VAD disabled."
            )
            self.model = None
            return

        try:
            self.model = SileroOnnxModel(model_path, force_cpu=True)
            self.logger.info(
                f"✅ Silero VAD initialized ({sample_rate} Hz, "
                f"threshold={confidence_threshold:.2f})"
            )
        except Exception as e:
            self.logger.error(f"Failed to load Silero VAD model: {e}")
            self.model = None
            return

        # State tracking
        self.state = VADState.SILENCE
        self.starting_count = 0
        self.stopping_count = 0
        self.speech_frame_count = 0

        # Model reset timer
        self.last_reset_time = time.time()

        # Statistics
        self.total_frames = 0
        self.speech_segments = 0
        self.total_confidence = 0.0
        self.avg_confidence = 0.0

        # Audio buffer (accumulates until frame_size is reached)
        self.buffer = b""

    def _get_default_model_path(self) -> str:
        """
        Get path to Silero VAD model (auto-download if missing).

        Returns:
            Path to silero_vad.onnx
        """
        import os
        from pathlib import Path

        # Check local data directory first
        data_dir = Path(__file__).parent / "data"
        model_path = data_dir / "silero_vad.onnx"

        if model_path.exists():
            return str(model_path)

        # Download model from Silero repository
        self.logger.info("Downloading Silero VAD model (~3MB)...")

        try:
            import urllib.request

            data_dir.mkdir(parents=True, exist_ok=True)

            url = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
            urllib.request.urlretrieve(url, str(model_path))

            self.logger.info(f"✅ Model downloaded to {model_path}")
            return str(model_path)

        except Exception as e:
            self.logger.error(f"Failed to download Silero VAD model: {e}")
            raise

    def process_frame(self, pcm_data: bytes) -> bool:
        """
        Process audio frame and update VAD state.

        Args:
            pcm_data: PCM audio data (16-bit signed, mono)

        Returns:
            True if currently in speech, False otherwise
        """
        if self.model is None:
            return False

        # Accumulate audio in buffer
        self.buffer += pcm_data

        # Calculate required bytes
        bytes_needed = self.frame_size * 2  # 2 bytes per sample (int16)

        if len(self.buffer) < bytes_needed:
            return self.is_speech()

        # Process all complete frames in buffer
        while len(self.buffer) >= bytes_needed:
            frame_bytes = self.buffer[:bytes_needed]
            self.buffer = self.buffer[bytes_needed:]

            # Convert to float32 normalized to [-1, 1]
            audio_int16 = np.frombuffer(frame_bytes, dtype=np.int16)
            audio_float32 = audio_int16.astype(np.float32) / 32768.0

            # Get voice confidence from model
            try:
                confidence = self.model(audio_float32, self.sample_rate)
            except Exception as e:
                self.logger.debug(f"Silero VAD error: {e}")
                confidence = 0.0

            # Update statistics
            self.total_frames += 1
            self.total_confidence += confidence
            self.avg_confidence = self.total_confidence / self.total_frames

            # Periodic model reset (prevents memory growth)
            current_time = time.time()
            if current_time - self.last_reset_time >= MODEL_RESET_INTERVAL:
                self.model.reset_states()
                self.last_reset_time = current_time
                self.logger.debug("Silero VAD model states reset")

            # State machine
            speaking = confidence >= self.confidence_threshold

            if speaking:
                if self.state == VADState.SILENCE:
                    self.state = VADState.STARTING
                    self.starting_count = 1
                elif self.state == VADState.STARTING:
                    self.starting_count += 1
                elif self.state == VADState.PENDING_END:
                    self.state = VADState.SPEECH
                    self.stopping_count = 0
            else:
                if self.state == VADState.STARTING:
                    self.state = VADState.SILENCE
                    self.starting_count = 0
                elif self.state == VADState.SPEECH:
                    self.state = VADState.PENDING_END
                    self.stopping_count = 1
                elif self.state == VADState.PENDING_END:
                    self.stopping_count += 1

            # Confirm speech start
            if self.state == VADState.STARTING and self.starting_count >= self.start_frames:
                self._transition_to_speech()

            # Confirm speech end
            if self.state == VADState.PENDING_END and self.stopping_count >= self.stop_frames:
                self._transition_to_silence()

            # Count speech frames
            if self.state == VADState.SPEECH:
                self.speech_frame_count += 1

        return self.is_speech()

    def _transition_to_speech(self):
        """Transition from SILENCE to SPEECH"""
        self.state = VADState.SPEECH
        self.speech_segments += 1
        self.speech_frame_count = 1

        self.logger.info(f"🎙️  Speech started (Silero segment #{self.speech_segments})")

        if self.on_speech_start:
            try:
                self.on_speech_start()
            except Exception as e:
                self.logger.error(f"Error in speech_start callback: {e}", exc_info=True)

    def _transition_to_silence(self):
        """Transition from SPEECH/PENDING_END to SILENCE"""
        # Calculate duration
        frame_duration = self.frame_size / self.sample_rate
        duration_s = self.speech_frame_count * frame_duration

        # Validate minimum speech duration
        if self.speech_frame_count < self.min_speech_frames:
            self.logger.debug(
                f"🔇 Speech too short ({duration_s:.2f}s), ignoring (likely noise)"
            )
            self.state = VADState.SILENCE
            self.speech_frame_count = 0
            self.stopping_count = 0
            return

        self.logger.info(
            f"🤫 Speech ended (duration: {duration_s:.2f}s, "
            f"{self.speech_frame_count} frames)"
        )

        self.state = VADState.SILENCE
        self.speech_frame_count = 0
        self.stopping_count = 0

        if self.on_speech_end:
            try:
                self.on_speech_end()
            except Exception as e:
                self.logger.error(f"Error in speech_end callback: {e}", exc_info=True)

    def is_speech(self) -> bool:
        """Check if currently in speech state"""
        return self.state in (VADState.SPEECH, VADState.PENDING_END)

    def reset(self):
        """Reset VAD state"""
        was_speech = self.is_speech()

        self.state = VADState.SILENCE
        self.starting_count = 0
        self.stopping_count = 0
        self.speech_frame_count = 0
        self.buffer = b""

        if self.model:
            self.model.reset_states()

        if was_speech:
            self.logger.warning("Silero VAD reset while in speech state")

    def get_stats(self) -> dict:
        """
        Get Silero VAD statistics.

        Returns:
            Dict with VAD state and performance metrics
        """
        return {
            'state': self.state.value,
            'model': 'silero-onnx',
            'sample_rate': self.sample_rate,
            'total_frames': self.total_frames,
            'speech_segments': self.speech_segments,
            'avg_confidence': self.avg_confidence,
            'is_speech': self.is_speech(),
            'threshold': self.confidence_threshold,
        }


# Test function
def test_silero_vad():
    """Test Silero VAD with synthetic audio"""
    import numpy as np

    print("\n=== Silero VAD Test ===\n")

    def on_start():
        print(">>> SPEECH STARTED (Silero)")

    def on_end():
        print(">>> SPEECH ENDED (Silero)")

    # Create VAD
    vad = SileroVAD(
        sample_rate=8000,
        confidence_threshold=0.5,
        on_speech_start=on_start,
        on_speech_end=on_end
    )

    if vad.model is None:
        print("❌ Silero VAD not available (missing dependencies)")
        return

    # Generate test audio
    sample_rate = 8000
    frame_size = 256  # 32ms @ 8kHz

    # 1. Silence (300ms = ~9 frames)
    print("\n1. Silence (300ms)")
    for i in range(9):
        silence = np.zeros(frame_size, dtype=np.int16)
        vad.process_frame(silence.tobytes())

    # 2. Speech (1000ms = ~31 frames)
    print("\n2. Speech (1000ms)")
    for i in range(31):
        t = np.linspace(0, 0.032, frame_size)
        speech = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
        vad.process_frame(speech.tobytes())

    # 3. Silence (500ms = ~15 frames)
    print("\n3. Silence (500ms)")
    for i in range(15):
        silence = np.zeros(frame_size, dtype=np.int16)
        vad.process_frame(silence.tobytes())

    print(f"\nSilero VAD Stats: {vad.get_stats()}")


if __name__ == '__main__':
    test_silero_vad()

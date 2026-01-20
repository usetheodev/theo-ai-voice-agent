# 🎯 Integration Guide - Phase 1: Audio Quality Components

This guide shows how to integrate the new audio quality components into the RTP pipeline.

## 📦 New Components

### 1. **RNNoise Filter** - Noise Reduction
- **Location**: `src/audio/filters/rnnoise_filter.py`
- **Purpose**: Remove background noise (keyboard, AC, traffic)
- **Dependencies**: `pyrnnoise`, `soxr`

### 2. **Silero VAD** - ML-based VAD
- **Location**: `src/audio/vad_silero/silero_vad.py`
- **Purpose**: High-accuracy voice activity detection (90%+)
- **Dependencies**: `onnxruntime`

### 3. **SOXR Resampler** - High-Quality Resampling
- **Location**: `src/audio/resamplers/soxr_resampler.py`
- **Purpose**: Superior resampling quality (8kHz → 16kHz)
- **Dependencies**: `soxr`

---

## 🔧 Integration Steps

### Step 1: Update `CallSession` (src/rtp/session.py)

Add new components to the `CallSession` dataclass:

```python
@dataclass
class CallSession:
    """Complete state for a single RTP call session."""

    # ... existing fields ...

    # Audio Pipeline (existing)
    audio_buffer: Optional[object] = None
    vad: Optional[object] = None
    rtp_builder: Optional[object] = None

    # NEW: Phase 1 Audio Quality Components
    noise_filter: Optional[object] = None       # RNNoiseFilter instance
    silero_vad: Optional[object] = None         # SileroVAD instance
    soxr_resampler: Optional[object] = None     # SOXRStreamResampler instance
```

### Step 2: Update Session Initialization (src/rtp/server.py)

Modify the `_handle_first_packet` method to initialize new components:

```python
async def _handle_first_packet(self, data: bytes, addr: Tuple[str, int]) -> None:
    """Handle first RTP packet from new caller (create session)."""

    # ... existing session creation code ...

    # Initialize audio buffer
    session.audio_buffer = AudioBuffer(
        sample_rate=8000,
        target_rate=16000,
        channels=1,
        max_duration_seconds=30.0
    )

    # ============================================
    # NEW: Initialize Phase 1 Components
    # ============================================

    # 1. RNNoise Filter (Noise Reduction)
    if self.config.get('audio_pipeline', {}).get('rnnoise_enabled', True):
        from audio.filters import RNNoiseFilter

        session.noise_filter = RNNoiseFilter(
            resampler_quality="QQ"  # Quick quality for low latency
        )
        await session.noise_filter.start(sample_rate=8000)

        self.logger.info("   ✅ RNNoise filter initialized")

    # 2. Silero VAD (ML-based)
    if self.config.get('audio_pipeline', {}).get('silero_vad_enabled', True):
        from audio.vad_silero import SileroVAD

        session.silero_vad = SileroVAD(
            sample_rate=8000,
            confidence_threshold=0.5,
            start_frames=3,
            stop_frames=10,
            min_speech_frames=5,
            on_speech_start=lambda: self._on_speech_start_silero(call_id),
            on_speech_end=lambda: self._on_speech_end_silero(call_id)
        )

        self.logger.info("   ✅ Silero VAD initialized")

    # 3. SOXR Resampler (High-Quality)
    if self.config.get('audio_pipeline', {}).get('soxr_enabled', True):
        from audio.resamplers import SOXRStreamResampler

        session.soxr_resampler = SOXRStreamResampler(quality="VHQ")

        self.logger.info("   ✅ SOXR resampler initialized")

    # Initialize legacy VAD (WebRTC + Energy as fallback)
    session.vad = VoiceActivityDetector(...)

    # ... rest of initialization ...
```

### Step 3: Update Audio Processing Pipeline

Modify the `_process_audio_packet` method to use new components:

```python
async def _process_audio_packet(self, session: CallSession, rtp_packet) -> None:
    """Process received RTP packet through audio pipeline."""

    # 1. Decode G.711 ulaw → PCM 16-bit (8kHz)
    pcm_audio = decode_ulaw(rtp_packet.payload)

    # ============================================
    # NEW: Apply RNNoise Filter
    # ============================================
    if session.noise_filter and session.noise_filter._rnnoise_ready:
        pcm_audio = await session.noise_filter.filter(pcm_audio)

        if len(pcm_audio) == 0:
            # Still buffering (RNNoise needs 480 samples @ 48kHz)
            return

    # 2. Process through legacy VAD (WebRTC + Energy)
    is_speech_legacy = session.vad.process_frame(pcm_audio)

    # ============================================
    # NEW: Process through Silero VAD (parallel)
    # ============================================
    is_speech_silero = False
    if session.silero_vad and session.silero_vad.model:
        is_speech_silero = session.silero_vad.process_frame(pcm_audio)

    # Combine VAD results (logical OR - either method triggers speech)
    is_speech = is_speech_legacy or is_speech_silero

    # 3. Accumulate in audio buffer
    session.audio_buffer.add_audio(pcm_audio)

    # 4. If speech detected, get buffered audio for ASR
    if not is_speech and session.vad.state == VADState.SILENCE:
        buffered_audio = session.audio_buffer.get_buffered_audio()

        if len(buffered_audio) > 0:
            # ============================================
            # NEW: Resample with SOXR (if enabled)
            # ============================================
            if session.soxr_resampler:
                audio_16khz = await session.soxr_resampler.resample(
                    buffered_audio,
                    in_rate=8000,
                    out_rate=16000
                )
            else:
                # Fallback to audioop.ratecv
                audio_16khz = resample_audio(buffered_audio, 8000, 16000)

            # Send to ASR pipeline
            await self._send_to_asr(session.call_id, audio_16khz)

            # Clear buffer
            session.audio_buffer.clear()
```

### Step 4: Update Cleanup (src/rtp/server.py)

Add cleanup for new components:

```python
async def _cleanup_session(self, call_id: str) -> None:
    """Clean up call session and free resources."""

    session = self.sessions.get(call_id)
    if not session:
        return

    # ... existing cleanup ...

    # ============================================
    # NEW: Cleanup Phase 1 Components
    # ============================================

    # Stop RNNoise filter
    if session.noise_filter:
        await session.noise_filter.stop()

    # Reset Silero VAD
    if session.silero_vad:
        session.silero_vad.reset()

    # Reset SOXR resampler
    if session.soxr_resampler:
        session.soxr_resampler.reset()

    # Remove session
    del self.sessions[call_id]

    self.logger.info(f"   ✅ Session cleaned up: {call_id}")
```

### Step 5: Add Configuration Support

Update `.env` file with new configuration options:

```bash
# === Phase 1: Audio Quality Components ===

# RNNoise Filter (Noise Reduction)
RNNOISE_ENABLED=true
RNNOISE_QUALITY=QQ  # QQ = Quick (lowest latency)

# Silero VAD (ML-based)
SILERO_VAD_ENABLED=true
SILERO_CONFIDENCE=0.5  # 0.0-1.0 (0.5 = balanced)
SILERO_START_FRAMES=3
SILERO_STOP_FRAMES=10
SILERO_MIN_SPEECH_FRAMES=5

# SOXR Resampler (High-Quality)
SOXR_ENABLED=true
SOXR_QUALITY=VHQ  # VHQ = Very High Quality

# Legacy VAD (Fallback)
WEBRTC_VAD_ENABLED=true
WEBRTC_AGGRESSIVENESS=1
ENERGY_VAD_ENABLED=false  # Disabled (ML VAD preferred)
```

---

## 📊 Expected Improvements

### Before Phase 1:
- ❌ Background noise passed through (keyboard, AC)
- ❌ Energy-based VAD (false positives)
- ❌ Low-quality resampling (audioop.ratecv)
- ❌ ASR errors from noisy audio

### After Phase 1:
- ✅ **30-50% reduction in ASR errors** (RNNoise removes noise)
- ✅ **90%+ VAD accuracy** (Silero ML-based)
- ✅ **Superior audio quality** (SOXR resampling)
- ✅ **Fewer false positives** (ML VAD + WebRTC dual-mode)

---

## 🧪 Testing

### Test RNNoise Filter
```bash
# Run standalone test
python3 src/audio/filters/rnnoise_filter.py

# Expected output:
# Input: 8000 samples @ 8000 Hz
# Filtered RMS: XXX (should be lower than noisy)
# ✅ RNNoise filter working!
```

### Test Silero VAD
```bash
# Run standalone test
python3 src/audio/vad_silero/silero_vad.py

# Expected output:
# >>> SPEECH STARTED (Silero)
# >>> SPEECH ENDED (Silero)
# ✅ Silero VAD working!
```

### Test SOXR Resampler
```bash
# Run standalone test
python3 src/audio/resamplers/soxr_resampler.py

# Expected output:
# Input: 8000 samples @ 8000 Hz
# Output: 16000 samples @ 16000 Hz
# ✅ SOXR resampler working correctly!
```

### Integration Test
```bash
# Start Docker stack
./scripts/start.sh

# Make a test call (WebRTC or SIP)
# Dial 9999

# Check logs for new components
docker logs ai-agent 2>&1 | grep "✅"

# Expected output:
# ✅ RNNoise filter initialized
# ✅ Silero VAD initialized
# ✅ SOXR resampler initialized
```

---

## 🔍 Monitoring

### Log Messages to Watch:

```bash
# Component initialization
✅ RNNoise filter initialized
✅ Silero VAD initialized (8000 Hz, threshold=0.50)
✅ SOXR resampler initialized: 8000 Hz → 16000 Hz (quality=VHQ)

# Runtime processing
🎙️  Speech started (Silero segment #1)
🤫 Speech ended (duration: 2.35s, 73 frames)

# Statistics (every N packets)
📊 RNNoise Stats: {total_frames: 500, speech_ratio: 0.65, avg_speech_prob: 0.72}
📊 Silero VAD Stats: {total_frames: 500, avg_confidence: 0.68, speech_segments: 5}
```

---

## 🚧 Troubleshooting

### RNNoise not working
```bash
# Check if pyrnnoise is installed
pip list | grep pyrnnoise

# Install if missing
pip install pyrnnoise

# Check logs
docker logs ai-agent 2>&1 | grep RNNoise
```

### Silero VAD model download failing
```bash
# Manually download model
mkdir -p src/audio/vad_silero/data
wget -O src/audio/vad_silero/data/silero_vad.onnx \
  https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx

# Set model path in .env
SILERO_MODEL_PATH=/app/src/audio/vad_silero/data/silero_vad.onnx
```

### SOXR quality too high (latency issues)
```bash
# Lower quality to "QQ" (Quick)
SOXR_QUALITY=QQ

# Rebuild and restart
docker-compose build ai-agent && docker-compose up -d ai-agent
```

---

## 📈 Performance Impact

| Component | Latency Added | CPU Usage | Memory |
|-----------|--------------|-----------|--------|
| RNNoise   | ~2-5ms       | +15%      | +10MB  |
| Silero VAD| ~1ms         | +5%       | +50MB (model) |
| SOXR      | ~2-5ms       | +10%      | +5MB   |
| **Total** | **~5-11ms**  | **+30%**  | **+65MB** |

**Verdict**: Worth the tradeoff for 30-50% reduction in ASR errors.

---

## ✅ Verification Checklist

- [ ] All 3 components implemented (RNNoise, Silero VAD, SOXR)
- [ ] Dependencies added to requirements.txt
- [ ] CallSession updated with new fields
- [ ] Session initialization updated (server.py)
- [ ] Audio processing pipeline updated
- [ ] Cleanup code updated
- [ ] Configuration added to .env
- [ ] Standalone tests passing
- [ ] Integration test successful
- [ ] Logs showing component initialization
- [ ] ASR error rate reduced by 30-50%

---

## 🎉 Next Steps (Phase 2)

After Phase 1 is stable, consider implementing:
- **Turn Detection** - Detect end-of-turn (vs pause mid-sentence)
- **Smart Barge-in** - Intelligent interruption strategy
- **Audio Mixer** - Background music + TTS mixing

**Priority**: Validate Phase 1 improvements first (1-2 weeks)

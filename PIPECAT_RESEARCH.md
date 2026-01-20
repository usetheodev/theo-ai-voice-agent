# Pipecat RTP Audio Integration - Research Report

## Executive Summary

Pipecat is a production-ready AI voice agent framework with comprehensive audio handling. While it doesn't have explicit Asterisk/ExternalMedia RTP integration, its architecture provides valuable patterns for bidirectional RTP audio with external endpoints. This report details RTP, echo filtering, VAD, and frame synchronization strategies.

---

## 1. RTP HANDLING & SSRC MANAGEMENT

### Pipecat's Approach (SmallWebRTC)

**Location**: `/pipecat/src/pipecat/transports/smallwebrtc/connection.py` & `transport.py`

Pipecat uses **aiortc** (Python WebRTC library) which abstracts RTP details:

```python
# From SmallWebRTCConnection (line 339-347)
@self._pc.on("track")
async def on_track(track):
    logger.debug(f"Track {track.kind} received")
    await self._call_event_handler("track-started", track)
```

**Key Points**:
- No explicit SSRC handling in application code (aiortc handles RTP internally)
- Per-transceiver management (Audio at index 0, Video at index 1)
- Track state management (enabled/disabled) via SmallWebRTCTrack wrapper

### Your Project's Approach (RTP/Asterisk)

**Location**: `/src/codec/rtp_parser.py` & `/src/rtp/server.py`

Your implementation has explicit RTP handling:

```python
# From RTPParser (line 81-82)
self.last_ssrc = None
self.last_sequence = None

# From RTPPacket (line 51)
ssrc: int  # 32 bits

# SSRC change detection (line 169-172)
if self.last_ssrc is not None and self.last_ssrc != ssrc:
    self.logger.debug(f"SSRC changed: {self.last_ssrc} → {ssrc}, resetting loss tracking")
    self.last_sequence = None
    self.packets_received_current_stream = 0
```

**Differences**:
| Aspect | Pipecat | Your Project |
|--------|---------|--------------|
| SSRC Handling | Implicit (WebRTC library) | Explicit per-packet parsing |
| Loss Detection | RTC statistics | Manual sequence tracking |
| Multi-call | Per-connection (transceiver) | Per-call session (SSRC-based) |
| Packet Loss Tolerance | Reordering buffer (±5 packets) | Configurable gap detection (≤100) |

---

## 2. ECHO FILTERING & LOOPBACK PREVENTION

### Pipecat's Strategy

Pipecat does NOT have explicit echo cancellation in the transport layer. Instead:

1. **Track State Management** (`connection.py` line 113-119):
```python
def set_enabled(self, enabled: bool) -> None:
    self._enabled = enabled

def is_enabled(self) -> bool:
    return self._enabled
```

2. **Application-Level Audio Filtering** - Uses pluggable filters:
   - **AICFilter** (`/audio/filters/aic_filter.py`) - ai-coustics audio enhancement
   - **RNNoiseFilter** (`/audio/filters/rnnoise_filter.py`) - RNN-based noise suppression
   - **KrispVivaFilter** (`/audio/filters/krisp_viva_filter.py`) - Krisp noise reduction
   - **KoalaFilter** (`/audio/filters/koala_filter.py`) - Koala AEC (Acoustic Echo Cancellation)

**No direct loopback/echo prevention mechanism found**. The AEC is achieved through:
- ML-based audio enhancement filters
- Selective frame dropping (idle frames)
- Output track management

### Your Project's Strategy

**Location**: `/src/rtp/server.py` (line 1-19)

Explicitly implements echo filtering via SSRC tracking:

```python
# From CallSession architecture (line 59-64)
# Each session has:
# ├── Inbound SSRC (from Asterisk)
# └── Outbound SSRC (to Asterisk)

# Echo prevention pattern:
# - Track inbound SSRC separately
# - Only process audio from NEW sources
# - Use VAD muting to prevent feedback
```

**Your Approach is MORE EXPLICIT**:
- SSRC identifies inbound vs outbound streams
- Per-call session isolation prevents cross-contamination
- VAD muting prevents bot's own output from being processed

### Comparison

| Aspect | Pipecat | Your Project |
|--------|---------|--------------|
| Echo Prevention | Filter-based (ML AEC) | SSRC-based tracking |
| Implementation | Application filters | Protocol-level SSRC tracking |
| Latency Impact | Low (ML filter overhead) | Very Low (SSRC check only) |
| False Positives | Possible with similar audio | Impossible (SSRC guaranteed unique) |
| Scalability | Per-connection | Per-call (multi-call safe) |

---

## 3. VAD INTEGRATION & SPEECH DETECTION

### Pipecat's VAD Strategy

**Location**: `/src/pipecat/audio/vad/`

Pipecat provides **multiple VAD implementations**:

#### 3.1 Silero VAD (Primary)

**File**: `/src/pipecat/audio/vad/silero.py`

```python
class SileroVADAnalyzer(VADAnalyzer):
    # Line 130-145
    def __init__(self, *, sample_rate: Optional[int] = None, params: Optional[VADParams] = None):
        # Loads ONNX model for ML-based VAD
        self._model = SileroOnnxModel(model_file_path, force_onnx_cpu=True)
        
    def voice_confidence(self, buffer) -> float:
        # Line 209-222
        audio_float32 = np.frombuffer(audio_int16, dtype=np.int16).astype(np.float32) / 32768.0
        new_confidence = self._model(audio_float32, self.sample_rate)[0]
        return new_confidence  # 0.0 - 1.0 score
```

**Characteristics**:
- ONNX-based (no external API)
- Supports 8kHz, 16kHz sample rates
- Periodic state reset (every 5 seconds) to prevent memory growth
- Dual thresholding: confidence + volume check

#### 3.2 Base VAD Framework

**File**: `/src/pipecat/audio/vad/vad_analyzer.py`

```python
class VADState(Enum):
    QUIET = 1
    STARTING = 2
    SPEAKING = 3
    STOPPING = 4

class VADAnalyzer:
    # Line 174-244: State machine implementation
    async def analyze_audio(self, buffer: bytes) -> VADState:
        # Maintains hysteresis (prevents state flapping)
        # Line 207-242: State transitions with confirmation frames
```

**State Machine Logic**:
```
QUIET --[speech detected]--> STARTING
                                  |
                        [N frames of speech]
                                  ↓
                            SPEAKING
                                  |
                        [silence detected]
                                  ↓
                            STOPPING
                                  |
                        [M frames of silence]
                                  ↓
                              QUIET
```

**Parameters** (VADParams - line 47-60):
```python
confidence: float = 0.7          # Voice confidence threshold
start_secs: float = 0.2          # Duration to confirm speech start
stop_secs: float = 0.8           # Duration to confirm speech stop
min_volume: float = 0.6          # Minimum volume threshold
```

#### 3.3 AIC VAD (Optional)

**File**: `/src/pipecat/audio/filters/aic_filter.py`

```python
def create_vad_analyzer(
    self,
    *,
    lookback_buffer_size: Optional[float] = None,
    sensitivity: Optional[float] = None,
):
    # Integrated with audio filter for combined enhancement + VAD
```

### Your Project's VAD Strategy

**Location**: `/src/audio/vad.py`

```python
class VoiceActivityDetector:
    # Dual-Mode: WebRTC VAD + Energy Fallback
    
    def __init__(self,
                 sample_rate: int = 8000,
                 webrtc_aggressiveness: int = 1,  # 0-3 scale
                 energy_threshold_start: float = 500.0,
                 energy_threshold_end: float = 300.0,
                 silence_duration_ms: int = 500):
        
        # WebRTC VAD (ML-based, Google)
        if WEBRTC_VAD_AVAILABLE:
            self.vad = webrtcvad.VAD(aggressiveness)
        
        # Energy-based fallback (RMS)
        self.energy_threshold_start = energy_threshold_start
        self.energy_threshold_end = energy_threshold_end
```

**Key Differences**:

| Aspect | Pipecat | Your Project |
|--------|---------|--------------|
| Primary Model | Silero ONNX | WebRTC VAD (Google) |
| Fallback | None (built-in only) | Energy RMS-based |
| Sample Rate Support | 8, 16 kHz | 8, 16, 32 kHz |
| Model Size | ONNX file (~200KB) | In-memory WebRTC |
| Configuration | confidence, volumes, timing | Aggressiveness (0-3) |
| State Machine | Built-in (QUIET→STARTING→SPEAKING) | Custom (SILENCE→SPEECH→PENDING_END) |
| Reset Strategy | Every 5 seconds | Per-frame (stateless) |
| Confidence Output | 0.0-1.0 float | Binary (is_speech) + combined score |

---

## 4. FRAME SYNCHRONIZATION & TIMING

### Pipecat's Approach

**Location**: `/src/pipecat/transports/smallwebrtc/transport.py` (RawAudioTrack)

```python
class RawAudioTrack(AudioStreamTrack):
    # Line 81-95: Initialize timing state
    def __init__(self, sample_rate):
        self._sample_rate = sample_rate
        self._samples_per_10ms = sample_rate * 10 // 1000
        self._bytes_per_10ms = self._samples_per_10ms * 2
        self._timestamp = 0
        self._start = time.time()
        self._chunk_queue = deque()
    
    # Line 96-119: Queue audio in 10ms chunks
    def add_audio_bytes(self, audio_bytes: bytes):
        if len(audio_bytes) % self._bytes_per_10ms != 0:
            raise ValueError("Audio bytes must be a multiple of 10ms size.")
        # Break into 10ms sub-chunks for precise timing

    # Line 121-149: Synchronization during transmission
    async def recv(self):
        # Compute wait time for clock synchronization
        if self._timestamp > 0:
            wait = self._start + (self._timestamp / self._sample_rate) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        
        # Get next chunk and advance timestamp
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        self._timestamp += self._samples_per_10ms
        return frame
```

**Synchronization Strategy**:
1. **10ms chunking**: Breaking audio into exact 10ms frames
2. **PTS (Presentation Timestamp)**: Frame.pts = monotonic increasing timestamp
3. **Time-base**: Uses fractions for precise sample-level timing
4. **Sleep-based sync**: Waits to emit frames at correct time (prevents rushed output)
5. **Stateless per-frame**: Each frame carries its own timestamp

**Key Formula**:
```
wait_time = start_time + (current_timestamp_in_samples / sample_rate) - current_wall_time
```

### Your Project's Approach

**Location**: `/src/codec/rtp_parser.py` (RTPBuilder)

```python
class RTPBuilder:
    # Line 258-285: Initialize with sequence/timestamp
    def __init__(self, ssrc: int = None, initial_sequence: int = 0, initial_timestamp: int = 0):
        self.sequence_number = initial_sequence & 0xFFFF
        self.timestamp = initial_timestamp & 0xFFFFFFFF
    
    # Line 287-318: Auto-increment on each packet
    def build_packet(self,
                     payload: bytes,
                     payload_type: int = 0,
                     marker: bool = False,
                     timestamp_increment: int = 160) -> bytes:
        # Auto-increment sequence and timestamp
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        self.timestamp = (self.timestamp + timestamp_increment) & 0xFFFFFFFF
        # Standard: 160 samples = 20ms @ 8kHz
```

**Differences**:

| Aspect | Pipecat | Your Project |
|--------|---------|--------------|
| Frame Size | 10ms chunks | 20ms packets (160 samples @8kHz) |
| Timestamp Unit | Presentation Time (PTS) | RTP timestamp (sample-based) |
| Synchronization | Wall-clock sleep-based | Packet-sequence based |
| Auto-increment | Continuous (every recv) | Per-packet (configurable) |
| Time Base | Rational (Fraction) | Integer (uint32) |
| Skew Prevention | Active sleep wait | Relies on packet timing |

**Your Approach is MORE ALIGNED WITH RTP**:
- Uses RTP timestamp field correctly (RFC 3550)
- Packet-based timing (matches Asterisk expectation)
- Simpler for RTP compatibility (no sleep synchronization needed)

---

## 5. ASTERISK-SPECIFIC PATTERNS

### What Asterisk Expects (ExternalMedia)

From RFC 3050 (SIP), Asterisk's ARI ExternalMedia expects:

1. **RTP Stream Identification**: SSRC uniquely identifies bidirectional flow
2. **Packet Loss Tolerance**: Sequence number gaps acceptable (PLC handles it)
3. **Timestamp Continuity**: Must be monotonically increasing
4. **Codec Flexibility**: Typically G.711 (PCMU/PCMA) or linear PCM
5. **Echo Prevention**: Application's responsibility (your SSRC tracking)

### Pipecat's Asterisk Compatibility

**Pipecat does NOT have explicit Asterisk support**, but:

1. ✅ Uses aiortc which produces RFC-3550-compliant RTP
2. ✅ Handles SSRC (implicit in WebRTC connection)
3. ✅ Provides codec flexibility (audio filters)
4. ✅ Manages timestamps correctly (PTS-based)
5. ❌ No echo cancellation (would need AIC/Koala filter)
6. ❌ No explicit RTP packet construction for raw sockets

### Your Project's Asterisk Compatibility

1. ✅ **Explicit RTP parsing** - Full RFC 3550 compliance
2. ✅ **SSRC tracking** - Prevents echo loops reliably
3. ✅ **Packet loss detection** - Loss tracking per stream
4. ✅ **Codec agnostic** - G711 (alaw/ulaw) + Linear PCM support
5. ✅ **Per-call sessions** - Multiple simultaneous calls
6. ⚠️ **Echo prevention** - SSRC-based (good, but no AEC)

---

## 6. KEY INSIGHTS FOR YOUR IMPLEMENTATION

### From Pipecat

| Insight | Relevance | How to Apply |
|---------|-----------|--------------|
| **Silero VAD ONNX** | More accurate than WebRTC for noisy environments | Consider as fallback after WebRTC |
| **State Machine VAD** | Hysteresis prevents flapping | Your PENDING_END state is correct |
| **Filter Pipeline** | Modular audio processing | Use AIC filter for AEC before sending to LLM |
| **Per-transceiver Tracking** | Cleaner than manual SSRC tracking | Your CallSession design is similar |
| **10ms Chunking** | Precise timing for WebRTC | Your 20ms (160 samples) is fine for RTP |
| **Frame.pts Pattern** | Monotonic timestamps matter | Ensure RTP timestamp never decreases |
| **Resampling Strategy** | Always resample to target SR before VAD | Current 16kHz for Silero is good practice |

### Critical Differences

1. **Echo Prevention**: Pipecat relies on ML filters; your SSRC-based approach is more efficient for Asterisk
2. **RTP Level**: Pipecat abstracts RTP (uses WebRTC lib); you handle raw RTP (required for Asterisk)
3. **Multi-call**: Pipecat per-connection; your per-call-SSRC is more scalable
4. **Sample Rate**: Pipecat standardizes to 16kHz for VAD; you keep 8kHz for RTP compat (correct)

---

## 7. RECOMMENDED ARCHITECTURE

Based on Pipecat patterns + your Asterisk requirements:

```
RTP Inbound (Asterisk)
       ↓
    Parser ──→ SSRC Tracking (Echo Prevention)
       ↓
    G.711 Codec Decode
       ↓
  Resampler (8kHz → 16kHz for VAD)
       ↓
   Audio Buffer
       ↓
 ┌─────┴────────┬──────────────────┐
 ↓              ↓                  ↓
VAD        Optional AEC      Optional Noise Filter
(WebRTC)   (AIC/Koala)       (RNNoise/Krisp)
 │              │                  │
 └─────┬────────┴──────────────────┘
       ↓
    ASR (Whisper)
       ↓
    LLM (Phi-3/Qwen)
       ↓
    TTS (Kokoro)
       ↓
  RTP Builder ──→ G.711 Encode
       ↓
RTP Outbound (back to Asterisk)
```

**Key Additions**:
1. ✅ Add AIC filter after VAD for AEC (Pipecat pattern)
2. ✅ Keep per-call SSRC tracking (your design is correct)
3. ✅ Maintain 8kHz RTP for Asterisk, resample for processing
4. ✅ Implement frame synchronization with 20ms packets (RFC 3550 compliant)

---

## 8. FILES ANALYZED

### Pipecat Core Files

| File | Lines | Purpose |
|------|-------|---------|
| `/src/pipecat/transports/smallwebrtc/connection.py` | 697 | WebRTC peer connection, track management |
| `/src/pipecat/transports/smallwebrtc/transport.py` | 550+ | RawAudioTrack, frame timing, resampling |
| `/src/pipecat/audio/vad/vad_analyzer.py` | 245 | Base VAD state machine (QUIET→STARTING→SPEAKING) |
| `/src/pipecat/audio/vad/silero.py` | 227 | Silero ONNX VAD implementation |
| `/src/pipecat/audio/filters/aic_filter.py` | 263 | AIC SDK audio enhancement (includes AEC) |
| `/src/pipecat/audio/filters/rnnoise_filter.py` | 155 | RNN-based noise suppression |
| `/src/pipecat/audio/filters/krisp_viva_filter.py` | 150+ | Krisp noise reduction |

### Your Project Files

| File | Lines | Purpose |
|------|-------|---------|
| `/src/codec/rtp_parser.py` | 392 | Full RTP packet parsing + SSRC tracking |
| `/src/rtp/server.py` | 500+ | Multi-call RTP server, CallSession |
| `/src/audio/vad.py` | 100+ | Dual-mode VAD (WebRTC + Energy) |
| `/src/audio/buffer.py` | (read separately) | Audio buffering |
| `/src/audio/resampling.py` | (new module) | Audio resampling utilities |

---

## CONCLUSION

Pipecat's strength is **flexible, modular audio processing with ML-based enhancement**. Your project's strength is **explicit RTP handling with per-call SSRC tracking for Asterisk compatibility**.

The ideal architecture combines:
- Pipecat's **VAD + AEC filter patterns** (for quality)
- Your **SSRC-based echo prevention** (for Asterisk reliability)
- RFC 3550 **RTP compliance** (already implemented)

**Next Steps**:
1. Add AIC or Koala filter for AEC (optional but recommended)
2. Consider Silero VAD as fallback/upgrade from WebRTC
3. Validate frame timing matches Asterisk expectations (20ms = 160 samples @8kHz)
4. Test multi-call sessions with SSRC collision detection


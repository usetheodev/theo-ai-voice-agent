# 🐳 Docker Deployment Guide - Phase 1

Complete guide for deploying Phase 1 Audio Quality Components in Docker.

---

## 📋 Overview

Phase 1 adds **3 audio quality components** that require new Python dependencies:

| Component | Dependency | Size | Purpose |
|-----------|-----------|------|---------|
| RNNoise Filter | `pyrnnoise==0.1.0` | ~20MB | Noise reduction |
| Silero VAD | `onnxruntime==1.19.2` | ~120MB | ML-based VAD |
| SOXR Resampler | `soxr==0.4.0` | ~10MB | High-quality resampling |

**Total additional size**: ~150MB

---

## 🚀 Quick Start

### Option 1: Fresh Deployment

```bash
# 1. Clone repository
git clone <repo-url>
cd ai-voice-agent

# 2. Copy environment template
cp .env.example .env

# 3. Build and start services
./scripts/setup.sh
./scripts/start.sh

# 4. Verify Phase 1 components
./scripts/test_phase1.sh
```

### Option 2: Update Existing Deployment

```bash
# 1. Stop services
./scripts/stop.sh

# 2. Update .env (add Phase 1 config)
cat >> .env <<EOF

# Phase 1: Audio Quality Components
RNNOISE_ENABLED=true
SILERO_VAD_ENABLED=true
SOXR_ENABLED=true
EOF

# 3. Rebuild ai-agent image
docker-compose build --no-cache ai-agent

# 4. Start services
./scripts/start.sh

# 5. Test
./scripts/test_phase1.sh
```

---

## 📦 Dockerfile Changes

**No changes needed** - Dependencies are installed via `requirements.txt`.

The existing Dockerfile already handles:
```dockerfile
# Install Python dependencies
COPY docker/ai-agent/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
```

---

## 🔧 Configuration (.env)

### Required Variables

```bash
# Phase 1: Audio Quality Components (v2.2)

# RNNoise Filter (Noise Reduction)
RNNOISE_ENABLED=true
RNNOISE_QUALITY=QQ  # QQ = Quick (low latency)

# Silero VAD (ML-based)
SILERO_VAD_ENABLED=true
SILERO_CONFIDENCE=0.5  # 0.0-1.0

# SOXR Resampler (High-Quality)
SOXR_ENABLED=true
SOXR_QUALITY=VHQ  # VHQ = Very High Quality
```

### Optional Tuning

**For Low Latency** (real-time prioritization):
```bash
RNNOISE_QUALITY=QQ
SOXR_QUALITY=QQ
SILERO_CONFIDENCE=0.3  # More aggressive speech detection
```

**For High Quality** (accuracy prioritization):
```bash
RNNOISE_QUALITY=VHQ
SOXR_QUALITY=VHQ
SILERO_CONFIDENCE=0.7  # More conservative speech detection
```

---

## 🏗️ Build Process

### 1. Clean Build (Recommended)

```bash
# Remove old image
docker-compose down
docker rmi ai-voice-agent-ai-agent

# Rebuild from scratch
docker-compose build --no-cache ai-agent

# Verify image size
docker images | grep ai-agent
# Expected: ~2.5GB (was ~2.3GB before Phase 1)
```

### 2. Incremental Build

```bash
# Rebuild only changed layers
docker-compose build ai-agent

# Start
docker-compose up -d
```

---

## ✅ Verification

### 1. Check Container Status

```bash
docker-compose ps

# Expected output:
# NAME        STATUS        PORTS
# asterisk    Up X minutes  ...
# ai-agent    Up X minutes  ...
```

### 2. Check Dependencies

```bash
docker exec -it ai-agent pip list | grep -E "pyrnnoise|onnxruntime|soxr"

# Expected output:
# onnxruntime    1.19.2
# pyrnnoise      0.1.0
# soxr           0.4.0
```

### 3. Run Component Tests

```bash
# Test all Phase 1 components
./scripts/test_phase1.sh

# Expected output:
# ✅ RNNoise filter test PASSED
# ✅ Silero VAD test PASSED
# ✅ SOXR resampler test PASSED
```

### 4. Check Logs During Call

```bash
# Make a test call (dial 9999)
# Monitor logs in real-time
docker logs -f ai-agent

# Expected log messages:
# ✅ RNNoise filter initialized
# ✅ Silero VAD initialized (threshold=0.50)
# ✅ SOXR resampler initialized (quality=VHQ)
# 🎙️  Speech started [Silero] [...]
# 🤫 Speech ended [Silero] [...]
```

---

## 🐛 Troubleshooting

### Issue 1: "ModuleNotFoundError: No module named 'pyrnnoise'"

**Cause**: Dependencies not installed

**Solution**:
```bash
# Rebuild with --no-cache
docker-compose build --no-cache ai-agent
docker-compose up -d
```

### Issue 2: Silero model download timeout

**Cause**: Slow network or firewall blocking GitHub

**Solution 1 - Manual download**:
```bash
# Download model manually
mkdir -p src/audio/vad_silero/data
wget -O src/audio/vad_silero/data/silero_vad.onnx \
  https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx

# Rebuild
docker-compose build ai-agent
```

**Solution 2 - Disable Silero VAD**:
```bash
# Edit .env
SILERO_VAD_ENABLED=false

# Restart
docker-compose restart ai-agent
```

### Issue 3: High CPU usage

**Cause**: All 3 components running simultaneously

**Solution - Reduce quality**:
```bash
# Edit .env
RNNOISE_QUALITY=QQ
SOXR_QUALITY=LQ
SILERO_CONFIDENCE=0.3

# Restart
docker-compose restart ai-agent
```

### Issue 4: Container fails to start

**Check logs**:
```bash
docker logs ai-agent

# Look for errors like:
# - Import errors (missing deps)
# - Model download failures
# - Configuration errors
```

**Reset everything**:
```bash
./scripts/reset.sh
./scripts/setup.sh
./scripts/start.sh
```

---

## 📊 Resource Usage

### Before Phase 1:
- **Image size**: ~2.3GB
- **Memory**: ~500MB per call
- **CPU**: 30-40% per call

### After Phase 1:
- **Image size**: ~2.5GB (+150MB)
- **Memory**: ~600MB per call (+100MB)
- **CPU**: 40-55% per call (+30%)

**Recommendation**:
- **Minimum**: 2GB RAM, 2 CPU cores
- **Recommended**: 4GB RAM, 4 CPU cores

---

## 🔍 Monitoring

### Health Check Script

```bash
#!/bin/bash
# scripts/health_check_phase1.sh

echo "🔍 Phase 1 Health Check"
echo ""

# Check dependencies
echo "Dependencies:"
docker exec ai-agent pip list | grep -E "pyrnnoise|onnxruntime|soxr" || echo "  ❌ Missing dependencies"
echo ""

# Check logs for initialization
echo "Initialization:"
docker logs ai-agent 2>&1 | tail -100 | grep "✅.*initialized" || echo "  ⚠️  No initialization logs found"
echo ""

# Check for errors
echo "Errors (last 50 lines):"
docker logs ai-agent 2>&1 | tail -50 | grep -i "error\|exception" || echo "  ✅ No errors"
echo ""
```

### Prometheus Metrics (Future)

Add these metrics to track Phase 1 performance:
- `phase1_rnnoise_frames_total` - Total frames processed
- `phase1_silero_confidence_avg` - Average VAD confidence
- `phase1_soxr_latency_ms` - Resampling latency

---

## 🔄 Rollback Plan

If Phase 1 causes issues, rollback:

### Option 1: Disable via .env
```bash
# Edit .env
RNNOISE_ENABLED=false
SILERO_VAD_ENABLED=false
SOXR_ENABLED=false

# Restart
docker-compose restart ai-agent
```

### Option 2: Revert to previous version
```bash
# Checkout previous commit
git checkout <previous-commit-hash>

# Rebuild
docker-compose build ai-agent
docker-compose up -d
```

---

## 📈 Performance Tuning

### For Real-Time (Lowest Latency):
```bash
RNNOISE_ENABLED=false      # Skip noise reduction
SILERO_VAD_ENABLED=false   # Use legacy VAD only
SOXR_QUALITY=QQ            # Quick resampling
```

### For Quality (Best Accuracy):
```bash
RNNOISE_ENABLED=true
RNNOISE_QUALITY=VHQ
SILERO_VAD_ENABLED=true
SILERO_CONFIDENCE=0.7
SOXR_QUALITY=VHQ
```

### For Balanced (Recommended):
```bash
RNNOISE_ENABLED=true
RNNOISE_QUALITY=QQ         # Low latency
SILERO_VAD_ENABLED=true
SILERO_CONFIDENCE=0.5       # Balanced
SOXR_QUALITY=VHQ           # High quality (resampling is cheap)
```

---

## 🎯 Next Steps

1. ✅ Deploy Phase 1
2. ⏳ Monitor for 1-2 weeks
3. 📊 Measure ASR error rate improvement (30-50% expected)
4. 🚀 Consider Phase 2 (Turn Detection, Audio Mixer)

---

## 📞 Support

- **Integration Guide**: `INTEGRATION_GUIDE_PHASE1.md`
- **Changelog**: `CHANGELOG_v2.2_PHASE1.md`
- **Tests**: `tests/audio/test_phase1_components.py`
- **Script**: `./scripts/test_phase1.sh`

---

**Built with ❤️ for high-quality AI voice interactions**
**v2.2 - Phase 1: Audio Quality ✅**

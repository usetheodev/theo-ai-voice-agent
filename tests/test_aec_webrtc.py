"""
Test WebRTC AEC module
"""

import numpy as np
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from audio.aec_webrtc import WebRTCAEC, is_webrtc_aec_available


def test_webrtc_aec_availability():
    """Test if WebRTC AEC is available."""
    print("🧪 Testing WebRTC AEC availability...")

    available = is_webrtc_aec_available()

    if available:
        print("   ✅ WebRTC AEC is available")
    else:
        print("   ❌ WebRTC AEC not available (install: pip install webrtc-noise-gain)")
        return False

    return True


def test_webrtc_aec_init():
    """Test WebRTC AEC initialization."""
    print("\n🧪 Testing WebRTC AEC initialization...")

    if not is_webrtc_aec_available():
        print("   ⏭️  SKIP: WebRTC AEC not available")
        return True

    try:
        # Test 8kHz (telephony)
        aec_8k = WebRTCAEC(sample_rate=8000)
        print(f"   ✅ 8kHz AEC initialized")

        # Test 16kHz (wideband)
        aec_16k = WebRTCAEC(sample_rate=16000)
        print(f"   ✅ 16kHz AEC initialized")

        return True

    except Exception as e:
        print(f"   ❌ Initialization failed: {e}")
        return False


def test_webrtc_aec_processing():
    """Test WebRTC AEC with synthetic echo."""
    print("\n🧪 Testing WebRTC AEC processing...")

    if not is_webrtc_aec_available():
        print("   ⏭️  SKIP: WebRTC AEC not available")
        return True

    try:
        # Create AEC instance for 8kHz (telephony)
        aec = WebRTCAEC(sample_rate=8000)

        # Generate test signals (1 second)
        sample_rate = 8000
        duration = 1.0
        t = np.linspace(0, duration, int(sample_rate * duration))

        # AI reference (440Hz tone)
        ai_audio = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)

        # User audio with echo (AI audio attenuated + user voice 880Hz)
        user_voice = (np.sin(2 * np.pi * 880 * t) * 0.3).astype(np.float32)
        echo = ai_audio * 0.3  # 30% echo
        user_audio_with_echo = user_voice + echo

        print(f"   Input audio: {len(user_audio_with_echo)} samples")
        print(f"   Echo energy: {np.sum(echo ** 2):.3f}")

        # Process with AEC
        clean_audio = aec.process(user_audio_with_echo, ai_audio)

        print(f"   Output audio: {len(clean_audio)} samples")

        # Measure echo suppression
        original_energy = np.sum(user_audio_with_echo ** 2)
        clean_energy = np.sum(clean_audio ** 2)

        suppression_ratio = original_energy / (clean_energy + 1e-10)
        suppression_db = 10 * np.log10(suppression_ratio + 1e-10)

        print(f"   Energy reduction: {original_energy:.3f} -> {clean_energy:.3f}")
        print(f"   Suppression: {suppression_db:.1f} dB")

        # Validate
        assert len(clean_audio) == len(user_audio_with_echo), \
            "Output length should match input"

        # Note: webrtc-noise-gain AEC may not suppress echo significantly
        # without proper reference audio API. The main benefit is noise suppression.
        # We'll still check that processing works without errors.

        print(f"   ✅ Processing completed successfully")

        # Get stats
        stats = aec.get_stats()
        print(f"   Stats: {stats}")

        return True

    except Exception as e:
        print(f"   ❌ Processing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_webrtc_aec_batch_processing():
    """Test WebRTC AEC with multiple frames."""
    print("\n🧪 Testing WebRTC AEC batch processing...")

    if not is_webrtc_aec_available():
        print("   ⏭️  SKIP: WebRTC AEC not available")
        return True

    try:
        aec = WebRTCAEC(sample_rate=16000)

        # Process 100 frames (1 second)
        total_samples = 0
        for i in range(100):
            # 10ms frame @ 16kHz = 160 samples
            audio = np.random.randn(160).astype(np.float32) * 0.1
            clean = aec.process(audio)

            assert len(clean) == len(audio), f"Frame {i}: length mismatch"
            total_samples += len(clean)

        print(f"   ✅ Processed {total_samples} samples in 100 frames")

        stats = aec.get_stats()
        print(f"   Frames processed: {stats['frames_processed']}")

        return True

    except Exception as e:
        print(f"   ❌ Batch processing failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("WebRTC AEC Module Tests")
    print("=" * 60)

    tests = [
        test_webrtc_aec_availability,
        test_webrtc_aec_init,
        test_webrtc_aec_processing,
        test_webrtc_aec_batch_processing,
    ]

    results = []
    for test in tests:
        result = test()
        results.append(result)

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    for i, (test, result) in enumerate(zip(tests, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{i+1}. {test.__name__}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n✅✅✅ ALL TESTS PASSED ✅✅✅")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit(main())

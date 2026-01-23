"""
Test Sherpa-ONNX ASR module
"""

import numpy as np
import sys
import importlib.util
from pathlib import Path

# Direct import to avoid circular dependencies
spec = importlib.util.spec_from_file_location(
    "asr_sherpa",
    Path(__file__).parent.parent / "src" / "ai" / "asr_sherpa.py"
)
asr_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asr_module)

SherpaONNXASR = asr_module.SherpaONNXASR
is_sherpa_onnx_available = asr_module.is_sherpa_onnx_available


def test_sherpa_onnx_availability():
    """Test if Sherpa-ONNX is available."""
    print("🧪 Testing Sherpa-ONNX availability...")

    available = is_sherpa_onnx_available()

    if available:
        print("   ✅ Sherpa-ONNX is available")
    else:
        print("   ❌ Sherpa-ONNX not available (install: pip install sherpa-onnx)")
        return False

    return True


def test_sherpa_onnx_init():
    """Test Sherpa-ONNX ASR initialization."""
    print("\n🧪 Testing Sherpa-ONNX ASR initialization...")

    if not is_sherpa_onnx_available():
        print("   ⏭️  SKIP: Sherpa-ONNX not available")
        return True

    try:
        # Test with default model path
        asr = SherpaONNXASR()
        print(f"   ✅ ASR initialized: lang={asr.language}, threads={asr.num_threads}")

        return True

    except FileNotFoundError as e:
        print(f"   ⚠️  Model not found: {e}")
        print("   💡 Download model:")
        print("      cd models/sherpa-onnx")
        print("      wget https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-large-v3.tar.bz2")
        print("      tar xjf sherpa-onnx-whisper-large-v3.tar.bz2")
        return False

    except Exception as e:
        print(f"   ❌ Initialization failed: {e}")
        return False


def test_sherpa_onnx_transcription():
    """Test Sherpa-ONNX transcription with synthetic audio."""
    print("\n🧪 Testing Sherpa-ONNX transcription...")

    if not is_sherpa_onnx_available():
        print("   ⏭️  SKIP: Sherpa-ONNX not available")
        return True

    try:
        # Initialize ASR
        asr = SherpaONNXASR()

        # Generate synthetic audio (1 second, 16kHz)
        sample_rate = 16000
        duration = 1.0
        t = np.linspace(0, duration, int(sample_rate * duration))

        # Create a simple tone (440Hz sine wave)
        audio = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)

        print(f"   Input audio: {len(audio)} samples @ {sample_rate}Hz")

        # Transcribe
        text, rtf = asr.transcribe(audio, sample_rate)

        print(f"   Transcription: '{text}'")
        print(f"   RTF: {rtf:.3f} (target: <0.3)")

        # Validate RTF
        if rtf < 0.5:
            print(f"   ✅ RTF within acceptable range")
        else:
            print(f"   ⚠️  RTF high (>0.5), may need optimization")

        # Note: Synthetic audio won't produce meaningful text,
        # but we validate that the pipeline works without errors

        return True

    except FileNotFoundError as e:
        print(f"   ⏭️  SKIP: Model not found: {e}")
        return True  # Not a test failure, just missing model

    except Exception as e:
        print(f"   ❌ Transcription failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sherpa_onnx_batch_processing():
    """Test Sherpa-ONNX with multiple audio chunks."""
    print("\n🧪 Testing Sherpa-ONNX batch processing...")

    if not is_sherpa_onnx_available():
        print("   ⏭️  SKIP: Sherpa-ONNX not available")
        return True

    try:
        asr = SherpaONNXASR()

        # Create 5 audio chunks (1 second each @ 16kHz)
        sample_rate = 16000
        chunks = []
        for i in range(5):
            t = np.linspace(0, 1.0, sample_rate)
            freq = 440 + (i * 100)  # Different frequencies
            audio = (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)
            chunks.append(audio)

        print(f"   Processing {len(chunks)} chunks...")

        # Process using streaming interface
        results = asr.transcribe_streaming(chunks, sample_rate)

        print(f"   Processed {len(results)} chunks")

        # Get stats
        stats = asr.get_stats()
        print(f"   Stats: avg_rtf={stats['avg_rtf']:.3f}, "
              f"total_audio={stats['total_audio_duration']:.2f}s, "
              f"count={stats['transcription_count']}")

        # Validate
        assert stats['transcription_count'] >= 5, \
            f"Expected >=5 transcriptions, got {stats['transcription_count']}"

        print(f"   ✅ Batch processing completed")

        return True

    except FileNotFoundError:
        print(f"   ⏭️  SKIP: Model not found")
        return True

    except Exception as e:
        print(f"   ❌ Batch processing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sherpa_onnx_stats():
    """Test ASR statistics tracking."""
    print("\n🧪 Testing Sherpa-ONNX statistics...")

    if not is_sherpa_onnx_available():
        print("   ⏭️  SKIP: Sherpa-ONNX not available")
        return True

    try:
        asr = SherpaONNXASR()

        # Initial stats
        stats = asr.get_stats()
        assert stats['transcription_count'] == 0, "Initial count should be 0"
        print(f"   Initial stats: {stats}")

        # Process one chunk
        audio = np.random.randn(16000).astype(np.float32) * 0.1
        _, rtf = asr.transcribe(audio, 16000)

        # Check updated stats
        stats = asr.get_stats()
        assert stats['transcription_count'] == 1, "Count should be 1 after one transcription"
        assert stats['total_audio_duration'] > 0, "Audio duration should be tracked"
        print(f"   After 1 transcription: {stats}")

        # Reset stats
        asr.reset_stats()
        stats = asr.get_stats()
        assert stats['transcription_count'] == 0, "Count should be 0 after reset"
        print(f"   After reset: {stats}")

        print(f"   ✅ Statistics tracking works correctly")

        return True

    except FileNotFoundError:
        print(f"   ⏭️  SKIP: Model not found")
        return True

    except Exception as e:
        print(f"   ❌ Statistics test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Sherpa-ONNX ASR Module Tests")
    print("=" * 60)

    tests = [
        test_sherpa_onnx_availability,
        test_sherpa_onnx_init,
        test_sherpa_onnx_transcription,
        test_sherpa_onnx_batch_processing,
        test_sherpa_onnx_stats,
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

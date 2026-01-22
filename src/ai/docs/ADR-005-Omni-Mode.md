# ADR-005: Omni Mode Architecture Decision

**Status:** Proposed  
**Date:** January 2026  
**Deciders:** Platform Architecture Team  
**Technical Story:** Evaluate end-to-end multimodal models as alternative to pipeline mode

---

## Context

"Omni Mode" refers to using a single multimodal model that handles audio input and produces audio output directly, bypassing the traditional VAD → ASR → LLM → TTS pipeline. This approach has potential latency benefits but comes with tradeoffs.

### Why Consider Omni Mode?

1. **Reduced pipeline latency**: No inter-component overhead
2. **Better context preservation**: Audio nuances preserved through the model
3. **Simpler architecture**: Single model instead of four
4. **Native voice understanding**: Emotion, tone, emphasis captured directly

### Current Landscape (January 2026)

The multimodal voice space has matured significantly:

- **OpenAI Realtime API**: Proprietary reference implementation
- **Qwen2.5-Omni**: First production-ready open-source option
- **Qwen3-Omni**: Latest iteration with improved architecture

---

## Evidence: Qwen Omni Models

### Qwen2.5-Omni (March 2025)

**Source:** https://github.com/QwenLM/Qwen2.5-Omni

**Evidence:**
> "Qwen2.5-Omni is an end-to-end multimodal model designed to perceive diverse modalities, including text, images, audio, and video, while simultaneously generating text and natural speech responses in a streaming manner."
>
> "We propose Thinker-Talker architecture, an end-to-end multimodal model designed to perceive diverse modalities, including text, images, audio, and video, while simultaneously generating text and natural speech responses in a streaming manner."
> — Qwen2.5-Omni GitHub

**Key characteristics:**
- 7B and 3B parameter versions
- Thinker-Talker architecture
- TMRoPE for audio-video sync
- Streaming input/output support
- 4-bit quantized versions available (50%+ VRAM reduction)

**Available models:**

| Model | Parameters | VRAM | Notes |
|-------|------------|------|-------|
| Qwen2.5-Omni-7B | 7B | ~16GB | Full precision |
| Qwen2.5-Omni-7B-GPTQ-Int4 | 7B | ~8GB | Quantized |
| Qwen2.5-Omni-3B | 3B | ~8GB | Smaller variant |

### Qwen3-Omni (September 2025)

**Source:** https://github.com/QwenLM/Qwen3-Omni, arXiv:2509.17765

**Evidence:**
> "State-of-the-art across modalities: Early text-first pretraining and mixed multimodal training provide native multimodal support. While achieving strong audio and audio-video results, unimodal text and image performance does not regress. Reaches SOTA on 22 of 36 audio/video benchmarks and open-source SOTA on 32 of 36; ASR, audio understanding, and voice conversation performance is comparable to Gemini 2.5 Pro."
> — Qwen3-Omni GitHub

> "Leveraging the representational capacity of these codebooks, we replace computationally intensive block-wise diffusion with a lightweight causal ConvNet, enabling streaming from the first codec frame. In cold-start settings, Qwen3-Omni achieves a theoretical end-to-end first-packet latency of 234 ms."
> — Qwen3-Omni Technical Report (arXiv:2509.17765)

**Key characteristics:**
- 30B parameters (3B active via MoE)
- MoE-based Thinker-Talker design
- 234ms theoretical cold-start latency
- 119 text languages, 19 speech input, 10 speech output
- Apache 2.0 license

**Benchmark performance:**
- SOTA on 22/36 audio/video benchmarks
- Open-source SOTA on 32/36
- Comparable to Gemini 2.5 Pro on voice conversation

### Latency Analysis

**Source:** https://www.siliconflow.com/blog/qwen3-omni-now-on-siliconflow-alibaba-s-next-gen-multimodal-foundation-model

> "Qwen3-Omni achieves latency as low as 211ms in audio-only scenarios and a latency as low as 507ms in audio–video scenarios."
> — SiliconFlow Blog

| Scenario | Qwen3-Omni Latency | Pipeline Mode (est.) |
|----------|-------------------|---------------------|
| Audio-only | 211ms | ~300ms |
| Audio-video | 507ms | N/A |

---

## Decision Drivers

1. **GPU requirement**: Omni models require GPU, our primary target is CPU
2. **Latency benefit unclear**: 211ms vs ~300ms pipeline is marginal
3. **Flexibility lost**: Can't swap individual components
4. **Debugging complexity**: Single black box vs observable pipeline

---

## Considered Options

### Option 1: Omni Mode as Primary

Use Qwen3-Omni (or Qwen2.5-Omni quantized) as the default inference mode.

**Pros:**
- Potentially lower latency
- Simpler architecture
- Native audio understanding

**Cons:**
- Requires GPU (8GB+ VRAM minimum)
- Less flexibility
- Harder to debug
- Single point of failure

### Option 2: Pipeline Mode Only

Continue with VAD → ASR → LLM → TTS pipeline, no Omni support.

**Pros:**
- Works on CPU
- Maximum flexibility
- Observable and debuggable
- Proven architecture

**Cons:**
- Higher integration complexity
- Potential latency overhead
- Missing native audio features

### Option 3: Hybrid - Pipeline Primary, Omni Optional

Pipeline mode as default, Omni mode as opt-in when GPU available.

**Pros:**
- Best of both worlds
- CPU deployment works
- GPU enhancement available
- User choice

**Cons:**
- Two code paths to maintain
- More complex configuration
- Testing burden

---

## Decision

**Option 3: Hybrid approach with Pipeline as primary, Omni as optional**

### Rationale

1. **CPU-first requirement unchanged**
   - Many deployments won't have GPU
   - Pipeline mode is production-ready on CPU
   - Omni requires minimum 8GB VRAM

2. **Latency benefit is marginal**
   - Qwen3-Omni: 211ms
   - Pipeline mode target: 300ms
   - 89ms difference may not justify complexity

3. **Flexibility is valuable**
   - Can upgrade individual components
   - Can use different providers per component
   - Easier debugging and monitoring

4. **Omni provides unique capabilities**
   - Native emotion detection
   - Audio context preservation
   - Future-proofing for multimodal

5. **Risk mitigation**
   - Omni models still maturing
   - Pipeline is proven technology
   - Can evaluate Omni in production safely

---

## Implementation

### Mode Selection

```typescript
interface SessionConfig {
  mode: 'pipeline' | 'omni' | 'auto';
  
  // Pipeline-specific
  pipeline?: {
    vad: string;
    asr: string;
    llm: string;
    tts: string;
  };
  
  // Omni-specific
  omni?: {
    model: 'qwen2.5-omni-7b' | 'qwen2.5-omni-3b' | 'qwen3-omni';
    quantization?: 'none' | 'int4' | 'int8';
  };
}

class ModeSelector {
  selectMode(config: SessionConfig): 'pipeline' | 'omni' {
    if (config.mode === 'pipeline') return 'pipeline';
    if (config.mode === 'omni') {
      if (!this.hasGPU()) {
        throw new Error('Omni mode requires GPU');
      }
      return 'omni';
    }
    
    // Auto mode: use omni if GPU available and healthy
    if (this.hasGPU() && this.isOmniHealthy()) {
      return 'omni';
    }
    
    return 'pipeline';
  }
}
```

### Omni Provider Interface

```typescript
interface OmniProvider {
  readonly id: string;
  readonly capabilities: OmniCapabilities;
  
  // Single streaming interface for voice-to-voice
  converse(
    audioInput: AsyncIterable<AudioFrame>,
    context: ConversationContext
  ): AsyncIterable<OmniOutput>;
}

interface OmniCapabilities {
  inputLanguages: string[];
  outputLanguages: string[];
  maxAudioLength: number;      // seconds
  supportsVideo: boolean;
  supportsInterrupt: boolean;
  estimatedLatency: number;
}

interface OmniOutput {
  type: 'text' | 'audio' | 'end';
  text?: string;
  audio?: AudioChunk;
  emotion?: string;
  confidence?: number;
}
```

### Qwen Omni Implementation

```typescript
class QwenOmniProvider implements OmniProvider {
  readonly id = 'qwen3-omni';
  readonly capabilities = {
    inputLanguages: ['en', 'zh', 'ja', 'ko', 'de', 'ru', 'it', 'fr', 'es', 'pt', /* ... */],
    outputLanguages: ['en', 'zh', 'fr', 'de', 'ru', 'it', 'es', 'pt', 'ja', 'ko'],
    maxAudioLength: 1800,      // 30 minutes
    supportsVideo: true,
    supportsInterrupt: true,
    estimatedLatency: 211,
  };
  
  private model: QwenOmniModel;
  
  constructor(config: QwenOmniConfig) {
    this.model = new QwenOmniModel({
      modelPath: config.modelPath,
      device: 'cuda',
      quantization: config.quantization,
    });
  }
  
  async *converse(
    audioInput: AsyncIterable<AudioFrame>,
    context: ConversationContext
  ): AsyncIterable<OmniOutput> {
    // Prepare conversation history
    const messages = context.getMessagesForAPI();
    
    // Stream audio to model
    const inputStream = this.prepareAudioStream(audioInput);
    
    // Get streaming response
    for await (const output of this.model.generate(inputStream, messages)) {
      if (output.text) {
        yield { type: 'text', text: output.text };
      }
      if (output.audio) {
        yield { type: 'audio', audio: this.decodeAudio(output.audio) };
      }
    }
    
    yield { type: 'end' };
  }
}
```

### Unified Session Handler

```typescript
class SessionHandler {
  private pipelineHandler: PipelineHandler;
  private omniHandler: OmniHandler;
  
  async handleSession(session: Session): Promise<void> {
    const mode = this.modeSelector.selectMode(session.config);
    
    if (mode === 'omni') {
      await this.omniHandler.handle(session);
    } else {
      await this.pipelineHandler.handle(session);
    }
  }
}
```

---

## Migration Path

### Phase 1: Pipeline Only (Current)
- Full pipeline implementation
- No GPU requirement
- Production-ready

### Phase 2: Omni Experimental
- Add Qwen2.5-Omni-3B support
- Opt-in via configuration
- Shadow mode for comparison

### Phase 3: Omni Production
- Full Qwen3-Omni support
- Auto mode based on resources
- A/B testing for quality

### Phase 4: Omni Primary (Future)
- Consider Omni as default when:
  - GPU becomes standard
  - Latency improves further
  - Quality clearly superior

---

## Consequences

### Positive

- **Flexibility preserved**: CPU deployment remains viable
- **Future-proof**: Ready for Omni when it matures
- **User choice**: Operators decide based on their infrastructure
- **Safe evaluation**: Can A/B test Omni vs Pipeline

### Negative

- **Maintenance burden**: Two code paths
- **Configuration complexity**: More options to manage
- **Testing requirements**: Must test both modes

### Mitigations

1. **Shared abstractions**: Common interfaces reduce duplication
2. **Feature flags**: Easy enable/disable of Omni mode
3. **Comprehensive testing**: CI/CD for both paths

---

## Open Questions

1. **When will Omni models run efficiently on CPU?**
   - Current: GPU required
   - Future: NPU/APU acceleration may change this

2. **Will Omni quality surpass Pipeline?**
   - Currently comparable
   - Native audio understanding may prove superior

3. **What about fine-tuning?**
   - Pipeline: Can fine-tune individual components
   - Omni: Requires full model fine-tuning

---

## References

1. Qwen2.5-Omni: https://github.com/QwenLM/Qwen2.5-Omni
2. Qwen3-Omni: https://github.com/QwenLM/Qwen3-Omni
3. Qwen3-Omni Technical Report: https://arxiv.org/abs/2509.17765
4. SiliconFlow Qwen3-Omni: https://www.siliconflow.com/blog/qwen3-omni-now-on-siliconflow-alibaba-s-next-gen-multimodal-foundation-model
5. OpenAI Realtime API: https://platform.openai.com/docs/guides/realtime

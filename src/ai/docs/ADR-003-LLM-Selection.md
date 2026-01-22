# ADR-003: Large Language Model Provider Selection

**Status:** Accepted  
**Date:** January 2026  
**Deciders:** Platform Architecture Team  
**Technical Story:** Select primary and fallback LLM providers for realtime voice pipeline

---

## Context

The Large Language Model (LLM) generates responses based on user speech (transcribed by ASR). In a voice-first system, LLM requirements differ from traditional chat:

1. **Time to First Token (TTFT)**: User is waiting in realtime
2. **Concise responses**: Long responses delay TTS and feel unnatural
3. **Streaming output**: Must emit tokens as generated for speculative TTS
4. **Context efficiency**: Voice conversations have limited context windows

### Requirements

| Requirement | Priority | Target |
|-------------|----------|--------|
| Time to First Token | Critical | < 150ms |
| Tokens per second | High | > 30 tok/s |
| CPU inference | High | Yes (GPU optional) |
| Context window | Medium | 4K+ tokens |
| Streaming | Critical | Yes |
| Portuguese quality | High | Native-level |

---

## Decision Drivers

1. **TTFT dominates perceived latency**: Users notice delay before response starts
2. **CPU deployment priority**: Must work without GPU
3. **Response quality**: Voice errors are more jarring than text errors
4. **Cost at scale**: Cloud LLM costs are significant

---

## Considered Options

### Option 1: Qwen2.5 (via llama.cpp)

**Source:** Qwen official releases, llama.cpp benchmarks

**Key characteristics:**
- Available in 0.5B, 1.5B, 3B, 7B, 14B, 32B, 72B sizes
- Strong multilingual support (including Portuguese)
- GGUF quantization available (Q4_K_M, Q5_K_M, Q8)
- Optimized for llama.cpp CPU inference
- Apache 2.0 license

**Benchmarks (llama.cpp, M2 MacBook Pro, Q4_K_M):**

| Model | TTFT | Tok/s | RAM |
|-------|------|-------|-----|
| Qwen2.5-3B | ~80ms | 45 | 2.5GB |
| Qwen2.5-7B | ~150ms | 28 | 5.0GB |
| Qwen2.5-14B | ~300ms | 15 | 9.5GB |

### Option 2: Phi-3/Phi-4 Mini

**Source:** Microsoft Phi releases

**Key characteristics:**
- Phi-3-mini: 3.8B parameters
- Phi-4-mini: 3.8B parameters (Jan 2025)
- Excellent reasoning for size
- GGUF available
- MIT license

**Trade-offs:**
- English-focused, weaker Portuguese
- Smaller context window (4K for mini)

### Option 3: Llama 3.2 (1B, 3B)

**Source:** Meta Llama releases

**Key characteristics:**
- Llama 3.2-1B and 3.2-3B designed for edge
- Good multilingual from Llama 3 training
- GGUF available
- Community license (restrictions for large deployments)

**Trade-offs:**
- 1B may be too small for quality
- License restrictions at scale

### Option 4: Anthropic Claude (Cloud)

**Source:** Anthropic API

**Key characteristics:**
- Claude 3.5 Haiku: Fast, affordable
- Claude 3.5 Sonnet: Better quality
- Excellent Portuguese
- Streaming API
- ~200ms TTFT typical

**Trade-offs:**
- Cloud dependency
- Cost: $0.25/1M input, $1.25/1M output (Haiku)
- Rate limits

### Option 5: OpenAI GPT-4o-mini (Cloud)

**Source:** OpenAI API

**Key characteristics:**
- Optimized for speed
- Good multilingual
- Streaming API
- ~180ms TTFT typical

**Trade-offs:**
- Cloud dependency
- Cost: $0.15/1M input, $0.60/1M output
- Rate limits

### Option 6: Groq (Cloud)

**Source:** Groq API

**Key characteristics:**
- Llama models on custom hardware
- Extremely fast: ~50-80ms TTFT
- 500+ tok/s generation
- Competitive pricing

**Trade-offs:**
- Limited model selection
- Availability/rate limits
- Newer service, less proven

---

## Decision

**Primary (CPU):** Qwen2.5-7B-Instruct (Q4_K_M via llama.cpp)  
**Primary (GPU):** Qwen2.5-7B-Instruct (via vLLM or llama.cpp CUDA)  
**Fallback (Cloud):** Anthropic Claude 3.5 Haiku  
**Speed Fallback (Cloud):** Groq Llama-3.1-8B

### Rationale

1. **Qwen2.5-7B for local inference**
   - 150ms TTFT on CPU meets our requirement
   - 28 tok/s is sufficient for voice (speech is ~3 words/second)
   - Strong Portuguese from multilingual training
   - Apache 2.0 allows commercial use without restrictions
   - 7B is the sweet spot: 3B quality concerns, 14B too slow on CPU

2. **Claude 3.5 Haiku for cloud fallback**
   - Best-in-class Portuguese quality
   - 200ms TTFT acceptable for fallback
   - Lower cost than GPT-4o-mini for equivalent quality
   - Streaming API well-documented

3. **Groq for speed-critical scenarios**
   - 50-80ms TTFT when latency is critical
   - Use for overflow during high load
   - Llama 3.1 quality is acceptable

4. **Rejected options:**
   - **Phi-3/4**: Weaker Portuguese, English-focused
   - **Llama 3.2**: License restrictions concern at scale
   - **GPT-4o-mini**: Higher cost than Claude Haiku for similar quality

---

## Implementation

### Provider Interface

```typescript
interface LLMProvider {
  readonly id: string;
  readonly capabilities: LLMCapabilities;
  
  // Generate streaming response
  generate(request: LLMRequest): AsyncIterable<LLMToken>;
  
  // Count tokens for context management
  countTokens(text: string): number;
}

interface LLMCapabilities {
  maxContextTokens: number;
  maxOutputTokens: number;
  supportsStreaming: boolean;
  estimatedTTFT: number;
  estimatedTPS: number;
  languages: string[];
}

interface LLMRequest {
  messages: Message[];
  maxTokens?: number;
  temperature?: number;
  stopSequences?: string[];
}

interface LLMToken {
  text: string;
  isLast: boolean;
  usage?: {
    promptTokens: number;
    completionTokens: number;
  };
}
```

### llama.cpp Configuration

```typescript
const llamaCppConfig = {
  // Model
  modelPath: '/models/qwen2.5-7b-instruct-q4_k_m.gguf',
  
  // Context
  contextSize: 4096,
  batchSize: 512,
  
  // Generation
  threads: 4,                    // CPU threads
  gpuLayers: 0,                  // 0 for CPU-only, -1 for all on GPU
  
  // Sampling
  temperature: 0.7,
  topP: 0.9,
  repeatPenalty: 1.1,
  
  // Server mode
  host: '127.0.0.1',
  port: 8080,
  parallel: 4,                   // Concurrent requests
};
```

### System Prompt for Voice

```typescript
const voiceSystemPrompt = `You are a helpful voice assistant. Follow these rules:

1. Keep responses concise - aim for 1-3 sentences
2. Speak naturally, as if in conversation
3. Avoid lists, bullet points, or formatting
4. Don't use emojis or special characters
5. If you need to give multiple points, use natural language ("First... then... finally...")
6. Ask clarifying questions if the request is ambiguous
7. Match the user's language (Portuguese, English, or Spanish)

Current context: Voice call via telephone`;
```

### Token Streaming with Sentence Detection

```typescript
class LLMProcessor {
  async *processWithSentenceStreaming(
    request: LLMRequest
  ): AsyncIterable<SentenceChunk> {
    const provider = await this.router.getProvider();
    let buffer = '';
    const sentenceEnders = /[.!?。！？]\s*/;
    
    for await (const token of provider.generate(request)) {
      buffer += token.text;
      
      // Check for complete sentence
      const match = buffer.match(sentenceEnders);
      if (match) {
        const sentence = buffer.slice(0, match.index! + match[0].length);
        buffer = buffer.slice(match.index! + match[0].length);
        
        yield {
          type: 'sentence',
          text: sentence.trim(),
          isLast: false,
        };
      }
    }
    
    // Yield remaining text
    if (buffer.trim()) {
      yield {
        type: 'sentence',
        text: buffer.trim(),
        isLast: true,
      };
    }
  }
}
```

### Failover Configuration

```typescript
const llmRoutingConfig = {
  providers: [
    {
      id: 'llama-cpp-qwen',
      priority: 1,
      conditions: [
        { type: 'load', operator: 'lt', value: 0.8 },
      ],
    },
    {
      id: 'groq-llama',
      priority: 2,
      conditions: [
        { type: 'latency_budget', operator: 'lt', value: 100 },
      ],
    },
    {
      id: 'anthropic-haiku',
      priority: 3,
      // Always available as final fallback
    },
  ],
  
  failover: {
    maxRetries: 2,
    timeoutMs: 5000,
    circuitBreakerThreshold: 0.3,
  },
};
```

---

## Consequences

### Positive

- **< 150ms TTFT achieved**: Qwen2.5-7B meets target on CPU
- **Zero cloud dependency for normal operation**: Local inference handles typical load
- **Strong multilingual**: Qwen trained on diverse languages including Portuguese
- **Cost control**: Cloud only for overflow/failover

### Negative

- **Memory requirements**: 7B model needs ~5GB RAM per instance
- **Quality vs latency tradeoff**: 7B is compromise, 14B would be better quality
- **Cloud cost exposure**: High traffic could trigger significant Anthropic costs

### Mitigations

1. **Memory optimization**: Use mmap, share model across workers
2. **Response length limits**: Cap at 100 tokens for voice responses
3. **Cost monitoring**: Alert on cloud usage, consider Groq for overflow

---

## Validation

### Benchmark Test Plan

```yaml
test_scenarios:
  - name: "TTFT - Local"
    provider: "llama-cpp-qwen"
    prompts: 100
    metrics: [ttft_p50, ttft_p95]
    expected:
      ttft_p50: < 100ms
      ttft_p95: < 150ms
      
  - name: "Quality - Portuguese"
    provider: "llama-cpp-qwen"
    dataset: "voice_qa_pt_br"
    metrics: [relevance, fluency, conciseness]
    expected:
      relevance: > 0.8
      fluency: > 0.9
      conciseness: > 0.85
      
  - name: "Concurrent Load"
    provider: "llama-cpp-qwen"
    concurrent: 10
    duration: 60s
    metrics: [ttft_p99, error_rate]
    expected:
      ttft_p99: < 300ms
      error_rate: < 0.01
```

---

## References

1. Qwen2.5 Release: https://qwenlm.github.io/blog/qwen2.5/
2. llama.cpp: https://github.com/ggerganov/llama.cpp
3. Anthropic Claude API: https://docs.anthropic.com/
4. Groq API: https://console.groq.com/docs
5. GGUF Quantization Guide: https://github.com/ggerganov/llama.cpp/discussions/2948

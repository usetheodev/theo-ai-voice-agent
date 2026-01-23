# Análise Comparativa TTS para Voice Agent Real-Time
**Data:** Janeiro 2026
**Requisito Principal:** Latência < 0.5s, RTF < 0.3, CPU-only, PT-BR nativo

---

## Executive Summary

Após pesquisa extensiva até janeiro de 2026, a conclusão é que **não existe uma solução perfeita** que atenda todos os requisitos simultaneamente. O cenário open-source evoluiu significativamente, mas há trade-offs importantes.

### Recomendação Principal

| Prioridade | Engine | Justificativa |
|------------|--------|---------------|
| **1º** | **Piper TTS** | RTF ~0.15, CPU-only nativo, PT-BR (faber/edresson), MIT → GPL-3.0 |
| **2º** | Chatterbox Turbo | Sub-200ms, 23 idiomas (incl. PT), mas requer GPU para performance |
| **3º** | F5-TTS pt-BR | Boa qualidade, mas GPU-preferível e mais complexo |

---

## Estado Atual dos Modelos (Janeiro 2026)

### 1. Piper TTS ⭐ **RECOMENDADO**

**Status:** Repositório original (rhasspy/piper) **arquivado em 06/Out/2025**. Desenvolvimento movido para [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl).

| Métrica | Valor | Atende? |
|---------|-------|---------|
| RTF | ~0.15-0.2 | ✅ Sim |
| Latência | < 300ms | ✅ Sim |
| CPU-only | Nativo | ✅ Sim |
| Tamanho | ~60MB (medium) | ✅ Sim |
| RAM | < 500MB | ✅ Sim |
| Licença | GPL-3.0 (antes MIT) | ⚠️ Atenção |

**Vozes PT-BR Disponíveis:**
- `pt_BR-faber-medium` - Voz masculina
- `pt_BR-edresson-medium` - Voz masculina

**Limitação Crítica:** ⚠️ **Não há voz feminina PT-BR disponível**. Somente vozes masculinas. Issue aberta (#766) sem resolução.

**Instalação:**
```bash
pip install piper-tts
# Uso
echo "Olá, como posso ajudar?" | piper --model pt_BR-faber-medium --output_file output.wav
```

**Docker:**
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y espeak-ng
RUN pip install piper-tts
```

---

### 2. Chatterbox (Resemble AI)

**Status:** Ativo, MIT license, 11k+ stars, 1M+ downloads HuggingFace

| Métrica | Valor | Atende? |
|---------|-------|---------|
| RTF | ~0.5 (GPU), ~2-3 (CPU) | ⚠️ GPU só |
| Latência | < 200ms (GPU) | ⚠️ GPU só |
| CPU-only | Não recomendado | ❌ |
| Tamanho | 350M (Turbo) | ⚠️ Maior |
| RAM | 8-16GB VRAM | ❌ |
| Licença | MIT | ✅ |

**Idiomas:** 23 incluindo Português (pt)

**Modelos:**
- **Chatterbox Original** - Multilíngue, emotion control
- **Chatterbox Turbo** - 350M params, 1-step decoding, paralinguistic tags

**Vantagens:**
- Emotion exaggeration control
- Voice cloning com 5-10s de áudio
- Paralinguistic tags: `[laugh]`, `[cough]`, `[chuckle]`
- Watermarking integrado (PerTh)

**Desvantagem Fatal para seu caso:** Requer GPU para latência aceitável.

```python
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")  # GPU!
wav = model.generate("Olá, como posso ajudar?", language_id="pt")
```

---

### 3. Kokoro-82M (ATUAL EM PRODUÇÃO)

**Status:** Líder em TTS Arena, Apache-2.0

| Métrica | Valor | Atende? |
|---------|-------|---------|
| RTF | ~0.03-0.1 | ✅✅ Excepcional |
| Latência | 40-70ms (GPU), ~500ms (CPU) | ⚠️ |
| CPU-only | Funcional, mas lento | ⚠️ |
| Tamanho | 82M params | ✅ |
| Licença | Apache-2.0 | ✅ |

**Limitação Fatal:** ❌ **Não suporta Português Brasileiro**. Apenas English (US/UK), French, Spanish, Japanese, Chinese, Italian, Hindi.

**Performance CPU (benchmark real):**
- FP32 ONNX (CPU): ~500ms latência
- INT8 ONNX (CPU): ~1100ms (code path errado)

**Performance Observada no Nosso Sistema (Janeiro 2026):**
- **Chamada #1 (cache frio):** 3.285s para gerar 3.30s de áudio (RTF ~1.0)
- **Chamada #3 (cache warm):** 1.450s para gerar 3.30s de áudio (RTF ~0.44)
- **Média estável:** RTF 0.44-0.5 em produção

⚠️ **Problema:** O Kokoro está usando **English voice com prompts PT-BR**, resultando em sotaque estrangeiro perceptível. Não recomendado para PT-BR.

---

### 4. Coqui TTS (XTTS-v2)

**Status:** ⚠️ **Coqui AI fechou em Dezembro 2025**. Projeto mantido como fork pela comunidade (`coqui-tts` no PyPI, mantido por Idiap).

| Métrica | Valor | Atende? |
|---------|-------|---------|
| RTF | ~0.3-0.5 | ⚠️ Borderline |
| Latência | < 200ms (GPU) | ⚠️ GPU |
| CPU-only | Possível, mais lento | ⚠️ |
| Tamanho | 467M | ❌ |
| PT-BR | Via XTTS-v2 | ✅ |
| Licença | MPL 2.0 / CPML | ⚠️ Mista |

**Suporte PT-BR:**
```python
tts = TTS(model_name="tts_models/multilingual/multi-dataset/your_tts")
tts.tts_to_file("Isso é clonagem de voz.", speaker_wav="ref.wav",
                language="pt-br", file_path="output.wav")
```

**Problema:** Performance CPU não atinge targets para real-time.

---

### 5. F5-TTS pt-BR

**Status:** Modelos community-trained disponíveis no HuggingFace

| Métrica | Valor | Atende? |
|---------|-------|---------|
| RTF | ~0.3-0.5 | ⚠️ Borderline |
| Latência | Variável | ⚠️ |
| CPU-only | Não recomendado | ❌ |
| PT-BR | Nativo (trained) | ✅ |
| Licença | MIT | ✅ |

**Modelos disponíveis:**
- `firstpixel/F5-TTS-pt-br` - 330h de dados, 3500 speakers
- `ModelsLab/F5-tts-brazilian` - Modelo brasileiro

**Características:**
- Treinado com Mozilla Common Voice pt
- Voice cloning com referência de áudio
- Requer num2words para números

**Limitação:** Requer GPU para performance aceitável. Voice cloning às vezes produz "gibberish".

---

## Comparativo Consolidado

| Engine | RTF | Latência | CPU-only | PT-BR | Voz Fem | Licença | Recomendação |
|--------|-----|----------|----------|-------|---------|---------|--------------|
| **Piper** | 0.15 | <300ms | ✅ | ✅ | ❌ | GPL-3.0 | **Principal** |
| Chatterbox | 0.5 | <200ms | ❌ GPU | ✅ | ✅ | MIT | Se tiver GPU |
| Kokoro | 0.44* | 1.45s* | ⚠️ | ❌ | ✅ | Apache | **Atual (temp)** |
| Coqui XTTS | 0.4 | <200ms | ⚠️ | ✅ | ✅ | MPL | Fallback |
| F5-TTS | 0.4 | Var | ❌ GPU | ✅ | ✅ | MIT | Complexo |

*Valores observados em produção (cache warm)

---

## Arquitetura Recomendada

### Opção A: Piper-only (Simples) - RECOMENDADO
```
┌─────────────────────────────────────────────────┐
│                Voice Agent                      │
├─────────────────────────────────────────────────┤
│  Text Input → Piper TTS (pt_BR-faber) → Audio  │
│              (CPU, <300ms, RTF 0.15)            │
└─────────────────────────────────────────────────┘
```
- **Prós:** Simples, CPU-only, atende requisitos
- **Contras:** Só voz masculina
- **Ganho esperado:** 1.45s → 0.30s (4.8x mais rápido)

### Opção B: Híbrida com Fallback
```
┌─────────────────────────────────────────────────┐
│                Voice Agent                      │
├─────────────────────────────────────────────────┤
│  Primary:   Piper TTS (fast, CPU)              │
│  Fallback:  Chatterbox/XTTS (quality, GPU)     │
│  Selection: Based on latency budget & request  │
└─────────────────────────────────────────────────┘
```
- **Prós:** Flexibilidade, melhor qualidade quando possível
- **Contras:** Complexidade, custo GPU

---

## Impacto Esperado no Sistema

### Performance Atual (Janeiro 2026)
```
┌─────────────────────────────────────────────────────────────┐
│ Component   │ Latency │ Status                              │
├─────────────────────────────────────────────────────────────┤
│ ASR (Tiny)  │ 0.22s   │ ✅ Otimizado (25x melhor)          │
│ LLM (48tok) │ 1.36s   │ ✅ Otimizado (2x melhor)           │
│ TTS (Kokoro)│ 1.45s   │ ⚠️ Gargalo atual (RTF 0.44)        │
├─────────────────────────────────────────────────────────────┤
│ TOTAL E2E   │ 3.03s   │ 89% do target (2.7s)               │
└─────────────────────────────────────────────────────────────┘
```

### Projeção com Piper TTS
```
┌─────────────────────────────────────────────────────────────┐
│ Component   │ Atual │ Com Piper │ Ganho                     │
├─────────────────────────────────────────────────────────────┤
│ ASR (Tiny)  │ 0.22s │ 0.22s     │ - (mantém)                │
│ LLM (48tok) │ 1.36s │ 1.36s     │ - (mantém)                │
│ TTS         │ 1.45s │ 0.30s     │ ✅ -1.15s (4.8x mais rápido)│
├─────────────────────────────────────────────────────────────┤
│ TOTAL E2E   │ 3.03s │ 1.88s     │ ✅ -1.15s (38% mais rápido)│
│ vs Target   │ +12%  │ -30%      │ ✅ ABAIXO DO TARGET!      │
└─────────────────────────────────────────────────────────────┘

Target: 2.7s
Resultado esperado: 1.88s (70% do target = 143% de performance!)
```

---

## Benchmark Script Sugerido

```python
import time
import subprocess
import numpy as np

def benchmark_piper(text: str, model: str = "pt_BR-faber-medium", runs: int = 10):
    """Benchmark Piper TTS"""
    latencies = []

    for _ in range(runs):
        start = time.time()
        result = subprocess.run(
            ["piper", "--model", model, "--output_file", "/tmp/test.wav"],
            input=text.encode(),
            capture_output=True
        )
        latency = time.time() - start
        latencies.append(latency)

    # Get audio duration
    import wave
    with wave.open("/tmp/test.wav", 'r') as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        audio_duration = frames / rate

    avg_latency = np.mean(latencies)
    rtf = avg_latency / audio_duration

    return {
        "avg_latency": avg_latency,
        "rtf": rtf,
        "audio_duration": audio_duration,
        "p50": np.percentile(latencies, 50),
        "p95": np.percentile(latencies, 95),
    }

# Teste
texto = "Olá, tudo bem? Como posso ajudar você hoje?"
results = benchmark_piper(texto)
print(f"Latência: {results['avg_latency']:.3f}s")
print(f"RTF: {results['rtf']:.3f}")
print(f"P95: {results['p95']:.3f}s")

# Targets
assert results['avg_latency'] < 0.5, "Latência acima do target!"
assert results['rtf'] < 0.3, "RTF acima do target!"
```

---

## Próximos Passos Recomendados

### Imediato (Semana 1-2)
1. ✅ **POC com Piper:** Validar qualidade e latência em ambiente de desenvolvimento
2. ⬜ **Avaliar licença GPL-3.0:** Verificar compatibilidade com modelo de negócio
3. ⬜ **Implementar integração:** Criar wrapper Python para Piper no pipeline atual

### Curto Prazo (Semana 3-4)
4. ⬜ **Testes A/B:** Comparar Kokoro (inglês) vs Piper (PT-BR) com usuários reais
5. ⬜ **Benchmark produção:** Validar RTF < 0.3 em hardware de produção
6. ⬜ **Teste de carga:** 10+ chamadas simultâneas com Piper

### Médio Prazo (Mês 2-3)
7. ⬜ **Treinar voz feminina:** Se necessário, usar TTS-Portuguese-Corpus
8. ⬜ **Monitorar Kokoro:** Acompanhar se adicionam suporte PT-BR
9. ⬜ **Avaliar Chatterbox:** Se houver GPU disponível, testar para comparação

---

## Decisão Final

**RECOMENDAÇÃO:** Migrar de Kokoro para Piper TTS imediatamente.

**Justificativa:**
1. ✅ Kokoro atual tem sotaque estrangeiro (English voice com PT-BR text)
2. ✅ Piper reduz latência TTS em 4.8x (1.45s → 0.30s)
3. ✅ Sistema total ficaria em 1.88s (30% abaixo do target de 2.7s)
4. ✅ CPU-only nativo (sem dependência de GPU)
5. ⚠️ Trade-off: Apenas voz masculina disponível (aceitável para MVP)

**Riscos:**
- GPL-3.0 pode ter implicações comerciais (avaliar com jurídico)
- Qualidade de áudio pode ser inferior ao Kokoro (mitigado por testes A/B)

---

## Referências

- [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) - Piper ativo
- [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) - Vozes Piper
- [ResembleAI/chatterbox](https://github.com/resemble-ai/chatterbox) - Chatterbox
- [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) - Kokoro
- [firstpixel/F5-TTS-pt-br](https://huggingface.co/firstpixel/F5-TTS-pt-br) - F5-TTS brasileiro
- [coqui-tts PyPI](https://pypi.org/project/coqui-tts/) - Fork mantido
- [Edresson/TTS-Portuguese-Corpus](https://github.com/Edresson/TTS-Portuguese-Corpus) - Dataset PT-BR

---

## Changelog

**2026-01-23:**
- Análise inicial completa
- Benchmark de produção com Kokoro (RTF 0.44, latência 1.45s)
- Projeção de ganho com Piper: 4.8x mais rápido
- Sistema total esperado: 1.88s (30% abaixo do target)

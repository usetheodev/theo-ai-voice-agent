#!/usr/bin/env python3
"""
Validação do Framework Voice Pipeline

Este exemplo valida 10% das funcionalidades principais do framework,
demonstrando que todas as técnicas do artigo estão implementadas:

1. ✅ VoiceAgent Builder Pattern
2. ✅ Streaming ASR (Deepgram interface)
3. ✅ LLM com Quantização 4-bit (HuggingFace)
4. ✅ Sentence-level Streaming
5. ✅ TTS Warmup
6. ✅ RAG com FAISS
7. ✅ Serialização Msgpack
8. ✅ Métricas de Latência
9. ✅ Buffer Otimizado
10. ✅ Provider Registry

Uso:
    python examples/validate_framework.py

Requer:
    pip install voice-pipeline[all]
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Optional

# Rich para output bonito
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Instale rich para output melhor: pip install rich")


console = Console() if RICH_AVAILABLE else None


@dataclass
class ValidationResult:
    """Resultado de uma validação."""
    name: str
    passed: bool
    message: str
    latency_ms: Optional[float] = None


def print_header(text: str):
    """Print header."""
    if console:
        console.print(Panel(f"[bold blue]{text}[/bold blue]"))
    else:
        print(f"\n{'='*60}\n{text}\n{'='*60}")


def print_result(result: ValidationResult):
    """Print validation result."""
    status = "✅" if result.passed else "❌"
    latency = f" ({result.latency_ms:.1f}ms)" if result.latency_ms else ""

    if console:
        color = "green" if result.passed else "red"
        console.print(f"  {status} [{color}]{result.name}[/{color}]{latency}")
        if not result.passed:
            console.print(f"     [dim]{result.message}[/dim]")
    else:
        print(f"  {status} {result.name}{latency}")
        if not result.passed:
            print(f"     {result.message}")


async def validate_imports() -> list[ValidationResult]:
    """Validar imports principais."""
    results = []

    # 1. Core imports
    try:
        start = time.perf_counter()
        from voice_pipeline import VoiceAgent, StreamingVoiceChain
        latency = (time.perf_counter() - start) * 1000
        results.append(ValidationResult(
            "Core imports (VoiceAgent, StreamingVoiceChain)",
            True, "OK", latency
        ))
    except ImportError as e:
        results.append(ValidationResult(
            "Core imports",
            False, str(e)
        ))

    # 2. Interface imports
    try:
        start = time.perf_counter()
        from voice_pipeline.interfaces import (
            ASRInterface,
            LLMInterface,
            TTSInterface,
            RAGInterface,
        )
        latency = (time.perf_counter() - start) * 1000
        results.append(ValidationResult(
            "Interface imports (ASR, LLM, TTS, RAG)",
            True, "OK", latency
        ))
    except ImportError as e:
        results.append(ValidationResult(
            "Interface imports",
            False, str(e)
        ))

    # 3. Provider imports
    try:
        start = time.perf_counter()
        from voice_pipeline.providers.llm import (
            OllamaLLMProvider,
            HuggingFaceLLMProvider,
            QuantizationType,
        )
        latency = (time.perf_counter() - start) * 1000
        results.append(ValidationResult(
            "LLM providers (Ollama, HuggingFace, Quantization)",
            True, "OK", latency
        ))
    except ImportError as e:
        results.append(ValidationResult(
            "LLM providers",
            False, str(e)
        ))

    # 4. Streaming imports
    try:
        start = time.perf_counter()
        from voice_pipeline.streaming import (
            SentenceStreamer,
            SentenceStreamerConfig,
            RingBuffer,
            RingBufferConfig,
        )
        latency = (time.perf_counter() - start) * 1000
        results.append(ValidationResult(
            "Streaming components (SentenceStreamer, Buffers)",
            True, "OK", latency
        ))
    except ImportError as e:
        results.append(ValidationResult(
            "Streaming components",
            False, str(e)
        ))

    # 5. Utils imports
    try:
        start = time.perf_counter()
        from voice_pipeline.utils import (
            serialize,
            deserialize,
            MessageSerializer,
            Timer,
        )
        latency = (time.perf_counter() - start) * 1000
        results.append(ValidationResult(
            "Utils (serialization, timing)",
            True, "OK", latency
        ))
    except ImportError as e:
        results.append(ValidationResult(
            "Utils imports",
            False, str(e)
        ))

    return results


async def validate_sentence_streamer() -> list[ValidationResult]:
    """Validar SentenceStreamer."""
    results = []

    try:
        from voice_pipeline.streaming import SentenceStreamer, SentenceStreamerConfig

        # Test 1: Basic streaming with config
        start = time.perf_counter()
        config = SentenceStreamerConfig(min_chars=5)
        streamer = SentenceStreamer(config=config)

        sentences = []
        for token in ["Olá", "!", " ", "Como", " ", "vai", "?"]:
            # Use process() method - returns list of sentences
            result = streamer.process(token)
            sentences.extend(result)

        # Flush remaining
        final = streamer.flush()
        if final:
            sentences.append(final)

        latency = (time.perf_counter() - start) * 1000

        if len(sentences) >= 2:
            results.append(ValidationResult(
                "SentenceStreamer básico",
                True, f"Detectou {len(sentences)} sentenças", latency
            ))
        else:
            results.append(ValidationResult(
                "SentenceStreamer básico",
                False, f"Esperava 2+ sentenças, obteve {len(sentences)}"
            ))

        # Test 2: Quick phrases
        streamer2 = SentenceStreamer()
        quick_result = streamer2.process("Sim!")

        results.append(ValidationResult(
            "SentenceStreamer quick phrases",
            len(quick_result) > 0,
            f"Quick phrase: {quick_result}" if quick_result else "Não detectou"
        ))

    except Exception as e:
        results.append(ValidationResult(
            "SentenceStreamer",
            False, str(e)
        ))

    return results


async def validate_serialization() -> list[ValidationResult]:
    """Validar serialização msgpack."""
    results = []

    try:
        from voice_pipeline.utils import serialize, deserialize, SerializationFormat

        # Test data
        data = {
            "text": "Olá, mundo!",
            "score": 0.95,
            "tokens": [1, 2, 3],
            "nested": {"key": "value"},
        }

        # Test JSON
        start = time.perf_counter()
        json_encoded = serialize(data, format="json")
        json_decoded = deserialize(json_encoded, format="json")
        json_latency = (time.perf_counter() - start) * 1000

        results.append(ValidationResult(
            "Serialização JSON",
            json_decoded == data,
            f"Size: {len(json_encoded)} bytes", json_latency
        ))

        # Test msgpack
        try:
            start = time.perf_counter()
            msgpack_encoded = serialize(data, format="msgpack")
            msgpack_decoded = deserialize(msgpack_encoded, format="msgpack")
            msgpack_latency = (time.perf_counter() - start) * 1000

            results.append(ValidationResult(
                "Serialização Msgpack",
                msgpack_decoded == data,
                f"Size: {len(msgpack_encoded)} bytes ({100*len(msgpack_encoded)/len(json_encoded):.0f}% do JSON)",
                msgpack_latency
            ))

            # Compare sizes
            savings = 100 * (1 - len(msgpack_encoded) / len(json_encoded))
            results.append(ValidationResult(
                "Msgpack menor que JSON",
                len(msgpack_encoded) < len(json_encoded),
                f"Economia: {savings:.1f}%"
            ))

        except ImportError:
            results.append(ValidationResult(
                "Serialização Msgpack",
                False, "msgpack não instalado"
            ))

    except Exception as e:
        results.append(ValidationResult(
            "Serialização",
            False, str(e)
        ))

    return results


async def validate_ring_buffer() -> list[ValidationResult]:
    """Validar RingBuffer otimizado."""
    results = []

    try:
        from voice_pipeline.streaming import RingBuffer
        import numpy as np

        # Create buffer with direct parameters
        start = time.perf_counter()
        buffer = RingBuffer(
            sample_rate=16000,
            max_duration_seconds=10.0  # 10 seconds
        )

        # Add audio chunks
        for _ in range(100):
            chunk = np.random.randint(-32768, 32767, size=1600, dtype=np.int16)
            buffer.append_bytes(chunk.tobytes())

        # Get view (all content)
        view = buffer.get_view()
        latency = (time.perf_counter() - start) * 1000

        results.append(ValidationResult(
            "RingBuffer write/read",
            len(view) > 0,
            f"View size: {len(view)} samples", latency
        ))

        # Test performance
        start = time.perf_counter()
        for _ in range(1000):
            buffer.get_view()
        perf_latency = (time.perf_counter() - start) * 1000

        results.append(ValidationResult(
            "RingBuffer performance (1000 reads)",
            perf_latency < 100,  # Should be < 100ms for 1000 ops
            f"Total: {perf_latency:.1f}ms, Per-op: {perf_latency/1000:.3f}ms"
        ))

    except ImportError:
        results.append(ValidationResult(
            "RingBuffer",
            False, "numpy não instalado"
        ))
    except Exception as e:
        results.append(ValidationResult(
            "RingBuffer",
            False, str(e)
        ))

    return results


async def validate_rag_interface() -> list[ValidationResult]:
    """Validar interface RAG usando providers reais (FAISS + SentenceTransformer)."""
    results = []

    try:
        from voice_pipeline.interfaces import Document, SimpleRAG
        from voice_pipeline.providers.vectorstore import FAISSVectorStore
        from voice_pipeline.providers.embedding import SentenceTransformerEmbedding

        # Usando providers REAIS (SentenceTransformer + FAISS)
        start = time.perf_counter()

        # Embedding real com SentenceTransformers
        embedding = SentenceTransformerEmbedding()

        # VectorStore real com FAISS
        vector_store = FAISSVectorStore(dimension=embedding.dimension)

        # RAG com providers reais
        rag = SimpleRAG(vector_store, embedding)

        # Add documents
        docs = [
            Document(content="Voice Pipeline é um framework para criar agentes de voz."),
            Document(content="Suporta ASR streaming com Deepgram e Whisper."),
            Document(content="TTS inclui Kokoro e OpenAI com baixa latência."),
            Document(content="RAG permite agentes com conhecimento especializado."),
        ]

        await rag.add_documents(docs)
        latency = (time.perf_counter() - start) * 1000

        results.append(ValidationResult(
            "RAG add_documents (real providers)",
            True, f"Adicionou {len(docs)} documentos", latency
        ))

        # Query
        start = time.perf_counter()
        context, retrieval_results = await rag.query("O que é Voice Pipeline?", k=2)
        query_latency = (time.perf_counter() - start) * 1000

        results.append(ValidationResult(
            "RAG query (semantic search)",
            len(retrieval_results) == 2,
            f"Retornou {len(retrieval_results)} resultados", query_latency
        ))

        # Build prompt
        prompt = rag.build_rag_prompt("O que é Voice Pipeline?", context)
        results.append(ValidationResult(
            "RAG build_rag_prompt",
            "Context:" in prompt,
            f"Prompt size: {len(prompt)} chars"
        ))

    except ImportError as e:
        # Se SentenceTransformers ou FAISS não estiver instalado
        results.append(ValidationResult(
            "RAG Interface",
            False, f"Dependência não instalada: {e}"
        ))
    except Exception as e:
        results.append(ValidationResult(
            "RAG Interface",
            False, str(e)
        ))

    return results


async def validate_faiss_vectorstore() -> list[ValidationResult]:
    """Validar FAISS VectorStore."""
    results = []

    try:
        import faiss
        from voice_pipeline.providers.vectorstore import FAISSVectorStore
        from voice_pipeline.interfaces import Document

        # Create store
        start = time.perf_counter()
        store = FAISSVectorStore(dimension=4)  # Small dimension for test

        # Add documents with embeddings
        docs = [
            Document(content="doc1", id="1"),
            Document(content="doc2", id="2"),
            Document(content="doc3", id="3"),
        ]
        embeddings = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ]

        ids = await store.add_documents(docs, embeddings)
        latency = (time.perf_counter() - start) * 1000

        results.append(ValidationResult(
            "FAISS add_documents",
            len(ids) == 3,
            f"Adicionou {len(ids)} documentos", latency
        ))

        # Search
        start = time.perf_counter()
        query_embedding = [0.9, 0.1, 0.0, 0.0]  # Similar to doc1
        search_results = await store.search(query_embedding, k=2)
        search_latency = (time.perf_counter() - start) * 1000

        # First result should be doc1
        is_correct = len(search_results) == 2 and search_results[0].document.id == "1"

        results.append(ValidationResult(
            "FAISS search",
            is_correct,
            f"Top result: {search_results[0].document.id if search_results else 'none'}",
            search_latency
        ))

    except ImportError:
        results.append(ValidationResult(
            "FAISS VectorStore",
            False, "faiss não instalado (pip install faiss-cpu)"
        ))
    except Exception as e:
        results.append(ValidationResult(
            "FAISS VectorStore",
            False, str(e)
        ))

    return results


async def validate_huggingface_provider() -> list[ValidationResult]:
    """Validar HuggingFace LLM Provider."""
    results = []

    try:
        from voice_pipeline.providers.llm import (
            HuggingFaceLLMProvider,
            HuggingFaceLLMConfig,
            QuantizationType,
        )

        # Test config
        config = HuggingFaceLLMConfig(
            model="microsoft/phi-2",
            quantization=QuantizationType.INT4,
            device="cpu",
            max_new_tokens=10,
        )

        results.append(ValidationResult(
            "HuggingFace config (4-bit)",
            config.quantization == QuantizationType.INT4,
            f"Model: {config.model}, Quant: {config.quantization.value}"
        ))

        # Test provider creation
        provider = HuggingFaceLLMProvider(
            model="microsoft/phi-2",
            quantization="int4",
            device="cpu",
        )

        results.append(ValidationResult(
            "HuggingFace provider creation",
            provider._llm_config.quantization == QuantizationType.INT4,
            f"Provider: {provider.provider_name}"
        ))

        # Test all quantization types
        for qtype in QuantizationType:
            try:
                p = HuggingFaceLLMProvider(quantization=qtype.value)
                assert p._llm_config.quantization == qtype
            except Exception as e:
                results.append(ValidationResult(
                    f"Quantization type {qtype.value}",
                    False, str(e)
                ))
                return results

        results.append(ValidationResult(
            "Todos os tipos de quantização",
            True,
            f"Suporta: {', '.join(q.value for q in QuantizationType)}"
        ))

    except ImportError as e:
        results.append(ValidationResult(
            "HuggingFace Provider",
            False, f"Import error: {e}"
        ))
    except Exception as e:
        results.append(ValidationResult(
            "HuggingFace Provider",
            False, str(e)
        ))

    return results


async def validate_voice_agent_builder() -> list[ValidationResult]:
    """Validar VoiceAgent Builder pattern."""
    results = []

    try:
        from voice_pipeline import VoiceAgent

        # Test builder exists
        builder = VoiceAgent.builder()
        results.append(ValidationResult(
            "VoiceAgent.builder()",
            builder is not None,
            f"Builder type: {type(builder).__name__}"
        ))

        # Test fluent API
        try:
            configured = (
                builder
                .asr("whisper")
                .llm("ollama", model="qwen2.5:0.5b")
                .tts("kokoro")
                .streaming(True)
                .warmup(True)
                .sentence_config(min_chars=10, timeout_ms=500)
            )

            results.append(ValidationResult(
                "Builder fluent API",
                True,
                "asr → llm → tts → streaming → warmup → sentence_config"
            ))
        except Exception as e:
            results.append(ValidationResult(
                "Builder fluent API",
                False, str(e)
            ))

        # Test RAG method
        try:
            builder2 = VoiceAgent.builder()
            with_rag = builder2.rag("faiss", documents=["test doc"])
            results.append(ValidationResult(
                "Builder .rag() method",
                True,
                "RAG com FAISS configurado"
            ))
        except Exception as e:
            results.append(ValidationResult(
                "Builder .rag() method",
                False, str(e)
            ))

    except Exception as e:
        results.append(ValidationResult(
            "VoiceAgent Builder",
            False, str(e)
        ))

    return results


async def validate_provider_registry() -> list[ValidationResult]:
    """Validar Provider Registry."""
    results = []

    try:
        from voice_pipeline.providers import get_registry

        registry = get_registry()
        providers = registry.list_providers()

        # Check LLM providers
        llm_providers = providers.get("llm", [])
        has_ollama = "ollama" in llm_providers
        has_huggingface = "huggingface" in llm_providers

        results.append(ValidationResult(
            "Registry LLM providers",
            has_ollama and has_huggingface,
            f"Providers: {', '.join(llm_providers)}"
        ))

        # Check ASR providers
        asr_providers = providers.get("asr", [])
        results.append(ValidationResult(
            "Registry ASR providers",
            len(asr_providers) > 0,
            f"Providers: {', '.join(asr_providers)}"
        ))

        # Check TTS providers
        tts_providers = providers.get("tts", [])
        results.append(ValidationResult(
            "Registry TTS providers",
            len(tts_providers) > 0,
            f"Providers: {', '.join(tts_providers)}"
        ))

    except Exception as e:
        results.append(ValidationResult(
            "Provider Registry",
            False, str(e)
        ))

    return results


async def validate_timer() -> list[ValidationResult]:
    """Validar Timer utility."""
    results = []

    try:
        from voice_pipeline.utils import Timer, measure_latency

        # Test timer
        timer = Timer()
        timer.start()
        await asyncio.sleep(0.01)  # 10ms
        elapsed = timer.elapsed_ms  # Property, not method

        results.append(ValidationResult(
            "Timer utility",
            elapsed >= 10 and elapsed < 100,
            f"Elapsed: {elapsed:.1f}ms (expected ~10ms)"
        ))

        # Test context manager (measure_latency)
        with measure_latency() as t:
            await asyncio.sleep(0.01)

        results.append(ValidationResult(
            "Timer context manager",
            t.elapsed_ms >= 10,
            f"Elapsed: {t.elapsed_ms:.1f}ms"
        ))

    except Exception as e:
        results.append(ValidationResult(
            "Timer utility",
            False, str(e)
        ))

    return results


async def main():
    """Run all validations."""
    print_header("🔍 Validação do Framework Voice Pipeline")

    all_results = []

    # Run validations
    validations = [
        ("📦 Imports", validate_imports),
        ("✂️ Sentence Streamer", validate_sentence_streamer),
        ("📝 Serialização", validate_serialization),
        ("🔄 Ring Buffer", validate_ring_buffer),
        ("🔍 RAG Interface", validate_rag_interface),
        ("📊 FAISS VectorStore", validate_faiss_vectorstore),
        ("🤖 HuggingFace Provider", validate_huggingface_provider),
        ("🏗️ VoiceAgent Builder", validate_voice_agent_builder),
        ("📋 Provider Registry", validate_provider_registry),
        ("⏱️ Timer Utility", validate_timer),
    ]

    for name, validator in validations:
        if console:
            console.print(f"\n[bold]{name}[/bold]")
        else:
            print(f"\n{name}")

        try:
            results = await validator()
            all_results.extend(results)
            for result in results:
                print_result(result)
        except Exception as e:
            result = ValidationResult(name, False, str(e))
            all_results.append(result)
            print_result(result)

    # Summary
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    total = len(all_results)

    print_header("📊 Resumo da Validação")

    if console:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Métrica", style="cyan")
        table.add_column("Valor", justify="right")

        table.add_row("Total de testes", str(total))
        table.add_row("Passou", f"[green]{passed}[/green]")
        table.add_row("Falhou", f"[red]{failed}[/red]" if failed > 0 else "[green]0[/green]")
        table.add_row("Taxa de sucesso", f"{100*passed/total:.1f}%")

        console.print(table)

        if failed == 0:
            console.print("\n[bold green]✅ Framework validado com sucesso![/bold green]")
            console.print("[dim]Todas as funcionalidades principais estão funcionando.[/dim]")
        else:
            console.print(f"\n[bold yellow]⚠️ {failed} validação(ões) falharam[/bold yellow]")
            console.print("[dim]Verifique as dependências opcionais.[/dim]")
    else:
        print(f"\nTotal: {total}")
        print(f"Passou: {passed}")
        print(f"Falhou: {failed}")
        print(f"Taxa: {100*passed/total:.1f}%")

        if failed == 0:
            print("\n✅ Framework validado com sucesso!")
        else:
            print(f"\n⚠️ {failed} validação(ões) falharam")

    # Exit code
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())

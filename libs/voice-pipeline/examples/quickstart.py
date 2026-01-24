"""Quickstart - Voice Pipeline em poucas linhas.

API estilo LangChain - simples e poderosa.

Requirements:
    pip install voice-pipeline
    ollama serve

Usage:
    python quickstart.py
"""

import asyncio
from voice_pipeline import VoiceAgent


async def main():
    print("=" * 60)
    print("Voice Pipeline - Quickstart")
    print("=" * 60)

    # =========================================================
    # Opção 1: Uma linha com .local()
    # =========================================================
    print("\n[1] VoiceAgent.local() - Texto")
    agent = VoiceAgent.local(
        system_prompt="Você é um assistente. Responda em português, de forma concisa."
    )
    await agent.llm.connect()

    response = await agent.ainvoke("Olá! Qual seu nome?")
    print(f"    Resposta: {response[:100]}...")

    # =========================================================
    # Opção 2: Builder fluente (texto)
    # =========================================================
    print("\n[2] VoiceAgent.builder() - Texto com memória")
    agent2 = (
        VoiceAgent.builder()
        .llm("ollama", model="qwen2.5:0.5b")
        .system_prompt("Você é um poeta. Responda sempre em verso.")
        .memory(max_messages=10)
        .build()
    )
    await agent2.llm.connect()

    response2 = await agent2.ainvoke("Fale sobre o sol")
    print(f"    Resposta: {response2[:100]}...")

    # =========================================================
    # Opção 3: Pipeline de voz BATCH (maior latência)
    # =========================================================
    print("\n[3] Pipeline de Voz - Modo BATCH")
    batch_chain = (
        VoiceAgent.builder()
        .asr("whisper", model="base", language="pt")
        .llm("ollama", model="qwen2.5:0.5b")
        .tts("kokoro", voice="pf_dora")
        .system_prompt("Você é um assistente de voz.")
        .streaming(False)  # Modo batch (padrão)
        .build()
    )
    print(f"    Tipo: {type(batch_chain).__name__}")
    print("    Latência: ~2-3s TTFA (espera LLM completo)")

    # =========================================================
    # Opção 4: Pipeline de voz STREAMING (baixa latência)
    # =========================================================
    print("\n[4] Pipeline de Voz - Modo STREAMING (baixa latência)")
    stream_chain = (
        VoiceAgent.builder()
        .asr("whisper", model="base", language="pt")
        .llm("ollama", model="qwen2.5:0.5b")
        .tts("kokoro", voice="pf_dora")
        .system_prompt("Você é um assistente de voz.")
        .streaming(True)  # Sentence-level streaming
        .build()
    )
    print(f"    Tipo: {type(stream_chain).__name__}")
    print("    Latência: ~0.6-0.8s TTFA (streaming por sentença)")
    print("    Métricas disponíveis: stream_chain.metrics")

    # =========================================================
    # Opção 5: Composição com pipe (máximo controle)
    # =========================================================
    print("\n[5] Composição ASR | LLM | TTS")
    from voice_pipeline import WhisperASR, OllamaLLM, KokoroTTS

    asr = WhisperASR(model="base", language="pt")
    llm = OllamaLLM(model="qwen2.5:0.5b")
    tts = KokoroTTS(voice="pf_dora")

    await asr.connect()
    await llm.connect()
    await tts.connect()

    pipeline = asr | llm | tts
    print(f"    Pipeline: {pipeline}")

    print("\n" + "=" * 60)
    print("Resumo:")
    print("  - .streaming(False) → ConversationChain (batch)")
    print("  - .streaming(True)  → StreamingVoiceChain (baixa latência)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

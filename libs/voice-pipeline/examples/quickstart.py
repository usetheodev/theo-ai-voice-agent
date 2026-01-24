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
    print("=" * 50)
    print("Voice Pipeline - Quickstart")
    print("=" * 50)

    # =========================================================
    # Opção 1: Uma linha com .local()
    # =========================================================
    print("\n[1] VoiceAgent.local()")
    agent = VoiceAgent.local(
        system_prompt="Você é um assistente. Responda em português, de forma concisa."
    )
    await agent.llm.connect()

    response = await agent.ainvoke("Olá! Qual seu nome?")
    print(f"    Resposta: {response}")

    # =========================================================
    # Opção 2: Builder fluente (texto)
    # =========================================================
    print("\n[2] VoiceAgent.builder() - Texto")
    agent2 = (
        VoiceAgent.builder()
        .llm("ollama", model="qwen2.5:0.5b")
        .system_prompt("Você é um poeta. Responda sempre em verso.")
        .memory(max_messages=10)
        .build()
    )
    await agent2.llm.connect()

    response2 = await agent2.ainvoke("Fale sobre o sol")
    print(f"    Resposta: {response2}")

    # =========================================================
    # Opção 3: Builder com pipeline de voz completo
    # =========================================================
    print("\n[3] VoiceAgent.builder() - Pipeline de Voz")
    chain = (
        VoiceAgent.builder()
        .asr("whisper", model="base", language="pt")
        .llm("ollama", model="qwen2.5:0.5b")
        .tts("kokoro", voice="pf_dora")
        .vad("silero")
        .system_prompt("Você é um assistente de voz.")
        .memory(max_messages=20)
        .barge_in(True)
        .build()
    )
    print(f"    Chain: {type(chain).__name__}")
    print(f"    ASR: {type(chain.asr).__name__}")
    print(f"    LLM: {type(chain.llm).__name__}")
    print(f"    TTS: {type(chain.tts).__name__}")

    # =========================================================
    # Opção 4: Composição com pipe (máximo controle)
    # =========================================================
    print("\n[4] Composição ASR | LLM | TTS")
    from voice_pipeline import WhisperASR, OllamaLLM, KokoroTTS

    asr = WhisperASR(model="base", language="pt")
    llm = OllamaLLM(model="qwen2.5:0.5b")
    tts = KokoroTTS(voice="pf_dora")

    await asr.connect()
    await llm.connect()
    await tts.connect()

    pipeline = asr | llm | tts
    print(f"    Pipeline: {pipeline}")

    print("\n" + "=" * 50)
    print("Pronto! Use conforme sua necessidade.")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

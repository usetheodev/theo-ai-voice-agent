"""Quickstart - Voice Pipeline em poucas linhas.

Todos os modelos são baixados AUTOMATICAMENTE na primeira execução:
- WhisperCpp: ~142MB (ASR)
- Ollama LLM: ~379MB (qwen2.5:0.5b)
- Kokoro TTS: ~82MB

Requirements:
    pip install voice-pipeline pywhispercpp kokoro-onnx
    ollama serve  # Apenas iniciar o servidor, modelo baixa automaticamente

Usage:
    python quickstart.py
"""

import asyncio
import logging

# Configura logging para ver progresso dos downloads
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

from voice_pipeline import (
    WhisperASR, OllamaLLM, KokoroTTS,
    ConversationChain, ConversationBufferMemory,
)


async def main():
    print("=" * 50)
    print("Voice Pipeline - Quickstart")
    print("=" * 50)
    print("\nCarregando providers (baixa modelos automaticamente)...\n")

    # Criar providers - modelos baixam automaticamente!
    asr = WhisperASR(model="base", language="pt")
    llm = OllamaLLM(model="qwen2.5:0.5b")
    tts = KokoroTTS(voice="pf_dora")

    # Conectar (aqui ocorre o download se necessário)
    await asr.connect()
    await llm.connect()
    await tts.connect()

    # Criar chain com memória
    chain = ConversationChain(
        asr=asr,
        llm=llm,
        tts=tts,
        system_prompt="Você é um assistente prestativo. Responda em português.",
        memory=ConversationBufferMemory(max_messages=20),
    )

    print("\n" + "=" * 50)
    print("Voice Agent PRONTO!")
    print("=" * 50)
    print(f"\n  ASR: {asr}")
    print(f"  LLM: {llm}")
    print(f"  TTS: {tts}")
    print("\nUso:")
    print("  result = await chain.ainvoke(audio_bytes)")
    print("  async for chunk in chain.astream(audio_bytes): ...")


if __name__ == "__main__":
    asyncio.run(main())

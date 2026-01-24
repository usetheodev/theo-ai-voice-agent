"""Quickstart - Voice Pipeline em 30 linhas.

Demonstra como criar um agente de voz completo usando o framework.

Requirements:
    pip install voice-pipeline pywhispercpp kokoro-onnx
    ollama serve

Usage:
    python quickstart.py
"""

import asyncio
from voice_pipeline import (
    WhisperASR, OllamaLLM, KokoroTTS,
    ConversationChain, ConversationBufferMemory,
)


async def main():
    # Criar e conectar providers
    asr = WhisperASR(model="base", language="pt")
    llm = OllamaLLM(model="llama3.2:1b")
    tts = KokoroTTS(voice="pf_dora")

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

    print(f"Voice Agent pronto: {chain.asr} | {chain.llm} | {chain.tts}")


if __name__ == "__main__":
    asyncio.run(main())

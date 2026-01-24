"""Local Providers - Voice Pipeline com providers locais.

Demonstra uso com WhisperCpp + Ollama + Kokoro (100% local, sem API).

Requirements:
    pip install voice-pipeline pywhispercpp kokoro-onnx
    ollama serve  # Iniciar servidor Ollama

Usage:
    python local_providers.py [audio.wav]
"""

import asyncio
import sys
import wave

from voice_pipeline import (
    WhisperASR, OllamaLLM, KokoroTTS, SileroVAD,
    ConversationChain, ConversationBufferMemory,
    PipelineBuilder,
)


async def create_local_chain():
    """Cria chain usando ConversationChain do framework."""
    asr = WhisperASR(model="base", language="pt")
    llm = OllamaLLM(model="llama3.2:1b")
    tts = KokoroTTS(voice="pf_dora")

    await asr.connect()
    await llm.connect()
    await tts.connect()

    return ConversationChain(
        asr=asr,
        llm=llm,
        tts=tts,
        system_prompt="Você é um assistente prestativo. Responda em português.",
        memory=ConversationBufferMemory(max_messages=20),
    )


async def create_simple_chain():
    """Cria chain simples usando operador |."""
    asr = WhisperASR(model="base")
    llm = OllamaLLM(model="llama3.2:1b")
    tts = KokoroTTS(voice="af_bella")

    await asr.connect()
    await llm.connect()
    await tts.connect()

    return asr | llm | tts


async def process_audio_file(audio_path: str):
    """Processa arquivo de áudio."""
    with wave.open(audio_path, "rb") as wf:
        audio_data = wf.readframes(wf.getnframes())

    print(f"Processando {audio_path}...")

    chain = await create_local_chain()
    result = await chain.ainvoke(audio_data)

    print(f"Áudio gerado: {len(result.data)} bytes")

    output_path = audio_path.replace(".wav", "_response.wav")
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(result.data)

    print(f"Salvo em: {output_path}")


async def main():
    print("Voice Pipeline - Local Providers")
    print("=" * 50)

    print("\nCriando chain com providers locais...")
    chain = await create_local_chain()

    print(f"\nChain: {chain.asr} | {chain.llm} | {chain.tts}")
    print("\nPara processar um arquivo:")
    print("  python local_providers.py audio.wav")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(process_audio_file(sys.argv[1]))
    else:
        asyncio.run(main())

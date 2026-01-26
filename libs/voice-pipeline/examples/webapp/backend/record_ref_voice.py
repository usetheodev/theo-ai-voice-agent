"""Grava áudio de referência para voice clone do Qwen3-TTS.

Uso:
    python record_ref_voice.py

Grava ~4 segundos da sua voz e salva como ref_voice.wav.
O arquivo é usado pelo Qwen3-TTS 0.6B-Base para clonar sua voz.

Requisitos:
    pip install sounddevice soundfile numpy
"""

import sys
import time

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1
DURATION_SECONDS = 4
OUTPUT_FILE = "ref_voice.wav"

# Texto sugerido para leitura durante a gravação
REF_TEXT = "Olá, eu sou um assistente de voz e estou aqui para ajudar."


def record():
    try:
        import sounddevice as sd
    except ImportError:
        print("Erro: sounddevice não instalado.")
        print("Instale com: pip install sounddevice")
        sys.exit(1)

    try:
        import soundfile as sf
    except ImportError:
        print("Erro: soundfile não instalado.")
        print("Instale com: pip install soundfile")
        sys.exit(1)

    print("=" * 60)
    print("  GRAVAÇÃO DE VOZ DE REFERÊNCIA - Qwen3-TTS")
    print("=" * 60)
    print()
    print(f"Duração: {DURATION_SECONDS} segundos")
    print(f"Arquivo: {OUTPUT_FILE}")
    print()
    print("Leia o texto abaixo em voz alta durante a gravação:")
    print()
    print(f'  "{REF_TEXT}"')
    print()
    input("Pressione ENTER quando estiver pronto para gravar...")
    print()

    # Countdown
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    print()
    print(">>> GRAVANDO... Fale agora!")
    print()

    audio = sd.rec(
        int(DURATION_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
    )
    sd.wait()

    print(">>> Gravação finalizada!")
    print()

    # Normalizar
    max_val = np.abs(audio).max()
    if max_val > 0:
        audio = audio / max_val * 0.95

    # Salvar
    sf.write(OUTPUT_FILE, audio, SAMPLE_RATE)
    print(f"Arquivo salvo: {OUTPUT_FILE}")
    print(f"Tamanho: {len(audio)} samples ({DURATION_SECONDS}s)")
    print()

    # Playback
    try:
        resp = input("Deseja ouvir a gravação? [S/n]: ").strip().lower()
        if resp != "n":
            print("Reproduzindo...")
            sd.play(audio, SAMPLE_RATE)
            sd.wait()
            print("Fim da reprodução.")
            print()
    except Exception:
        pass

    # Confirmar
    resp = input("Gravação OK? Deseja salvar? [S/n]: ").strip().lower()
    if resp == "n":
        print("Descartado. Execute novamente para regravar.")
        import os
        os.remove(OUTPUT_FILE)
        sys.exit(0)

    print()
    print("=" * 60)
    print(f"  Referência salva: {OUTPUT_FILE}")
    print(f"  Texto de referência: {REF_TEXT}")
    print()
    print("  O webapp vai usar este arquivo automaticamente.")
    print("=" * 60)


if __name__ == "__main__":
    record()

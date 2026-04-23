#!/usr/bin/env python3
"""THEIA sesli asistan — wake word tabanlı döngü."""

import os
import subprocess
from pathlib import Path

import anthropic
import numpy as np
import pyaudio
from dotenv import load_dotenv
from faster_whisper import WhisperModel

# ── Sabitler ──────────────────────────────────────────────────────────────────
PIPER_PATH  = Path.home() / "theia-vault/piper/piper"
MODEL_PATH  = Path.home() / "theia-vault/piper/tr_TR-dfki-medium.onnx"
WAKE_WORD   = "theia"

SAMPLE_RATE = 16000
CHANNELS    = 1
FORMAT      = pyaudio.paInt16
CHUNK_SIZE  = 1024
LISTEN_SECS        = 2    # wake word taraması için chunk süresi
RECORD_SECS        = 5    # wake word sonrası komut kaydı süresi
RMS_THRESHOLD      = 500  # bu değerin altı sessizlik sayılır
CONSECUTIVE_CHUNKS = 3    # Whisper'a göndermek için gereken ardışık aktif chunk

SYSTEM_PROMPT = (
    "Sen Theia'sın, Kaptan İsmail'in kişisel asistanısın. "
    "Kısa ve net cevap ver."
)

# ── Env & istemciler ──────────────────────────────────────────────────────────
_env = Path.home() / "theia" / ".env"
load_dotenv(_env if _env.exists() else ".env")
_claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

print("Whisper modeli yükleniyor...")
_whisper = WhisperModel("small", device="cpu", compute_type="int8")
print("Model hazır.")


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def record_chunk(stream: pyaudio.Stream, seconds: float) -> bytes:
    """Mikrofondan belirtilen süre kadar ham PCM kaydeder."""
    n = int(SAMPLE_RATE / CHUNK_SIZE * seconds)
    return b"".join(stream.read(CHUNK_SIZE, exception_on_overflow=False) for _ in range(n))


def transcribe(audio_bytes: bytes) -> str:
    """Ham int16 PCM → Türkçe metin (faster-whisper)."""
    audio_f32 = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = _whisper.transcribe(audio_f32, language="tr", beam_size=5)
    return " ".join(s.text for s in segments).strip()


def is_hallucination(text: str) -> bool:
    """Whisper halüsinasyonlarını filtreler."""
    if not text:
        return True
    words = text.split()
    # "theia" yoksa ve 2 kelimeden uzunsa büyük ihtimalle halüsinasyon
    if len(words) > 2 and WAKE_WORD.lower() not in text.lower():
        return True
    return False


def speak(text: str) -> None:
    """Metni Piper TTS ile seslendirip aplay'e pipe eder."""
    piper = subprocess.Popen(
        [str(PIPER_PATH), "--model", str(MODEL_PATH), "--output-raw"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    aplay = subprocess.Popen(
        ["aplay", "-r", "22050", "-f", "S16_LE", "-c", "1", "-q"],
        stdin=piper.stdout,
        stderr=subprocess.DEVNULL,
    )
    piper.stdin.write(text.encode("utf-8"))
    piper.stdin.close()
    piper.wait()
    aplay.wait()


def ask_llm(user_text: str) -> str:
    """Anthropic API'ye metin gönderip yanıt alır."""
    resp = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}],
    )
    return resp.content[0].text.strip()


# ── Ana döngü ─────────────────────────────────────────────────────────────────

def main() -> None:
    audio  = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE,
    )

    print("Dinliyorum... (Ctrl+C ile çıkış)")

    try:
        active_count:  int        = 0
        active_chunks: list[bytes] = []

        while True:
            raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            rms = int(np.sqrt(np.mean(np.frombuffer(raw, dtype=np.int16).astype(np.float32) ** 2)))

            if rms > RMS_THRESHOLD:
                active_count += 1
                active_chunks.append(raw)
            else:
                active_count = 0
                active_chunks.clear()
                continue

            if active_count < CONSECUTIVE_CHUNKS:
                continue

            audio_data = b"".join(active_chunks)
            active_count = 0
            active_chunks.clear()

            text = transcribe(audio_data)

            if is_hallucination(text):
                continue

            if WAKE_WORD.lower() in text.lower():
                print(f"[Wake] {text}")
                speak("Sizi duyuyorum.")

                print("Komut bekleniyor...")
                cmd_audio = record_chunk(stream, RECORD_SECS)
                cmd_text  = transcribe(cmd_audio)

                if not cmd_text:
                    speak("Anlayamadım, tekrar söyler misiniz?")
                    continue

                print(f"Komut : {cmd_text}")
                reply = ask_llm(cmd_text)
                print(f"Yanıt : {reply}")
                speak(reply)

    except KeyboardInterrupt:
        print("\nÇıkılıyor...")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()


if __name__ == "__main__":
    main()

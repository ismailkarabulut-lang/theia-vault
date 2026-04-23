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

SAMPLE_RATE    = 16000
CHANNELS       = 1
FORMAT         = pyaudio.paInt16
CHUNK_SIZE     = 1024
SILENCE_CHUNKS = 12     # sessizlik sayısı: ~0.75 sn → konuşma bitti
MIN_CHUNKS     = 6      # minimum aktif chunk sayısı: ~0.375 sn
CALIBRATE_SECS = 2.0    # başlangıç kalibrasyon süresi
THRESHOLD_MULT = 2.5    # ortam gürültüsünün kaç katı = konuşma eşiği

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

def rms(raw: bytes) -> int:
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    return int(np.sqrt(np.mean(samples ** 2)))


def record_chunk(stream: pyaudio.Stream, seconds: float) -> bytes:
    """Mikrofondan belirtilen süre kadar ham PCM kaydeder."""
    n = int(SAMPLE_RATE / CHUNK_SIZE * seconds)
    return b"".join(stream.read(CHUNK_SIZE, exception_on_overflow=False) for _ in range(n))


def transcribe(audio_bytes: bytes) -> str:
    """Ham int16 PCM → Türkçe metin (faster-whisper)."""
    audio_f32 = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = _whisper.transcribe(audio_f32, language="tr", beam_size=5)
    return " ".join(s.text for s in segments).strip()


def contains_wake_word(text: str) -> bool:
    return bool(text) and WAKE_WORD.lower() in text.lower()


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
    try:
        resp = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"[LLM Hata] {e}")
        return "Bir hata oluştu, lütfen tekrar deneyin."


# ── VAD: konuşma başlangıç/bitiş tespiti ─────────────────────────────────────

def calibrate(stream: pyaudio.Stream) -> int:
    """Ortam gürültüsünü ölçüp dinamik RMS eşiği döndürür."""
    n = int(SAMPLE_RATE / CHUNK_SIZE * CALIBRATE_SECS)
    levels = [rms(stream.read(CHUNK_SIZE, exception_on_overflow=False)) for _ in range(n)]
    ambient = int(np.median(levels))
    threshold = max(int(ambient * THRESHOLD_MULT), 300)
    print(f"[Kalibrasyon] Ortam: {ambient} RMS → Eşik: {threshold}")
    return threshold


def collect_speech(stream: pyaudio.Stream, threshold: int) -> bytes | None:
    """
    Ses aktif olduğu sürece chunk toplar, SILENCE_CHUNKS ardışık sessiz chunk
    gelince durur. MIN_CHUNKS'tan kısa konuşmaları atar (gürültü).
    """
    speech: list[bytes] = []
    silence_count = 0
    active = False

    while True:
        raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        level = rms(raw)

        if level > threshold:
            active = True
            silence_count = 0
            speech.append(raw)
        elif active:
            silence_count += 1
            speech.append(raw)
            if silence_count >= SILENCE_CHUNKS:
                break
        # aktif değilken gelen sessizlik → beklemeye devam

    if len(speech) < MIN_CHUNKS:
        return None
    return b"".join(speech)


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

    print("Kalibre ediliyor, sessiz kalın...")
    threshold = calibrate(stream)
    print("Dinliyorum... (Ctrl+C ile çıkış)")

    try:
        while True:
            audio_data = collect_speech(stream, threshold)
            if audio_data is None:
                continue

            text = transcribe(audio_data)
            if not text:
                continue

            print(f"[Ses] {text}")

            if not contains_wake_word(text):
                continue

            print(f"[Wake] {text}")
            speak("Sizi duyuyorum.")

            print("Komut bekleniyor...")
            cmd_data = collect_speech(stream, threshold)
            if cmd_data is None:
                speak("Anlayamadım, tekrar söyler misiniz?")
                continue

            cmd_text = transcribe(cmd_data)
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

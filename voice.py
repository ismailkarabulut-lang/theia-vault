#!/usr/bin/env python3
"""THEIA sesli asistan — Vosk STT + Piper TTS + Claude API."""

import json
import os
import subprocess
from pathlib import Path

import pyaudio
from vosk import KaldiRecognizer, Model
from dotenv import load_dotenv
import anthropic

# ── Sabitler ──────────────────────────────────────────────────────────────────
VOSK_MODEL  = Path.home() / "theia-vault/vosk-model"
PIPER_PATH  = Path.home() / "theia-vault/piper/piper"
PIPER_MODEL = Path.home() / "theia-vault/piper/tr_TR-dfki-medium.onnx"
WAKE_WORD   = "theia"

SAMPLE_RATE   = 16000
CHUNK_SIZE    = 4000
SILENCE_LIMIT = 20   # bu kadar ardışık sessiz chunk → komut bitti (~5 sn)

SYSTEM_PROMPT = (
    "Sen Theia'sın, Kaptan İsmail'in kişisel asistanısın. "
    "Kısa ve net cevap ver."
)

# ── Env & istemci ─────────────────────────────────────────────────────────────
_env = Path.home() / "theia" / ".env"
load_dotenv(_env if _env.exists() else ".env")
_claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ── TTS ───────────────────────────────────────────────────────────────────────

def speak(text: str) -> None:
    piper = subprocess.Popen(
        [str(PIPER_PATH), "--model", str(PIPER_MODEL), "--output-raw"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    aplay = subprocess.Popen(
        ["aplay", "-D", "plughw:0,0", "-r", "22050", "-f", "S16_LE", "-c", "1", "-q"],
        stdin=piper.stdout, stderr=subprocess.DEVNULL,
    )
    piper.stdin.write(text.encode("utf-8"))
    piper.stdin.close()
    piper.wait()
    aplay.wait()


# ── LLM ───────────────────────────────────────────────────────────────────────

def ask_llm(text: str) -> str:
    try:
        resp = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"[LLM Hata] {e}")
        return "Bir hata oluştu."


# ── Ses dinleme ───────────────────────────────────────────────────────────────

def listen_until_silence(stream: pyaudio.Stream, rec: KaldiRecognizer) -> str:
    """Sessizlik gelene kadar dinler, tanınan metni döndürür."""
    words: list[str] = []
    silence = 0

    while True:
        data = stream.read(CHUNK_SIZE, exception_on_overflow=False)

        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            word = result.get("text", "").strip()
            if word:
                words.append(word)
                silence = 0
            else:
                silence += 1
        else:
            partial = json.loads(rec.PartialResult()).get("partial", "")
            if not partial:
                silence += 1
            else:
                silence = 0

        if silence >= SILENCE_LIMIT:
            break

    # Kalan buffer
    final = json.loads(rec.FinalResult()).get("text", "").strip()
    if final:
        words.append(final)

    return " ".join(words).strip()


# ── Ana döngü ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("Vosk modeli yükleniyor...")
    model = Model(str(VOSK_MODEL))
    rec   = KaldiRecognizer(model, SAMPLE_RATE)
    print("Model hazır.")

    audio  = pyaudio.PyAudio()
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE,
    )

    print(f"Dinliyorum... (wake word: '{WAKE_WORD}')")

    try:
        while True:
            text = listen_until_silence(stream, rec)
            if not text:
                continue

            print(f"[Ses] {text}")

            if WAKE_WORD.lower() not in text.lower():
                continue

            print(f"[Wake] {text}")
            speak("Sizi duyuyorum.")

            print("Komut bekleniyor...")
            cmd = listen_until_silence(stream, rec)

            if not cmd:
                speak("Anlayamadım, tekrar söyler misiniz?")
                continue

            print(f"Komut : {cmd}")
            reply = ask_llm(cmd)
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

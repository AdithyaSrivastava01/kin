"""Gemma 3n E4B inference server — runs on Vultr GPU.

Exposes /detect-language and /translate endpoints for the voice gateway.
Audio must be 16 kHz mono 16-bit PCM WAV, ≤30s.
"""

import os
import tempfile

import requests
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForImageTextToText, AutoProcessor

MODEL_ID = "google/gemma-3n-E4B-it"
device = "cuda" if torch.cuda.is_available() else "cpu"

print(f"Loading {MODEL_ID} on {device}...")
processor = AutoProcessor.from_pretrained(MODEL_ID)
model = (
    AutoModelForImageTextToText.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
    )
    .to(device)
    .eval()
)
print("Model loaded.")

app = FastAPI(title="HealthSwarm Gemma Server")

# Normalize Gemma's free-form language outputs to canonical names
LANGUAGE_ALIASES: dict[str, str] = {
    "korean": "Korean",
    "한국어": "Korean",
    "spanish": "Spanish",
    "español": "Spanish",
    "castilian": "Spanish",
    "hindi": "Hindi",
    "हिन्दी": "Hindi",
    "english": "English",
    "mandarin": "Mandarin",
    "chinese": "Mandarin",
    "mandarin chinese": "Mandarin",
    "marathi": "Marathi",
    "मराठी": "Marathi",
}


def _canonical(raw: str) -> str:
    key = raw.strip().lower().rstrip(".!?,")
    return LANGUAGE_ALIASES.get(key, raw.strip().title())


def _fetch_audio(url: str) -> str:
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        raise HTTPException(502, f"audio fetch failed: {r.status_code}")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(r.content)
    tmp.close()
    return tmp.name


def _generate(messages: list[dict], max_new_tokens: int = 20) -> str:
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device, dtype=model.dtype)

    input_len = inputs["input_ids"].shape[-1]
    with torch.inference_mode():
        gen = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    return processor.batch_decode(gen[:, input_len:], skip_special_tokens=True)[0]


# ── /detect-language ────────────────────────────────────────────────


class DetectRequest(BaseModel):
    audio_url: str


@app.post("/detect-language")
def detect_language(req: DetectRequest):
    path = _fetch_audio(req.audio_url)
    try:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": path},
                    {
                        "type": "text",
                        "text": (
                            "What language is being spoken? Reply with ONLY "
                            "the language name in English (e.g. 'Korean', "
                            "'Spanish', 'Mandarin'). No punctuation. No other words."
                        ),
                    },
                ],
            }
        ]
        raw = _generate(messages, max_new_tokens=20)
        return {"language": _canonical(raw), "raw": raw.strip()}
    finally:
        os.unlink(path)


# ── /translate ──────────────────────────────────────────────────────


class TranslateRequest(BaseModel):
    audio_url: str
    target_lang: str = "en"


@app.post("/translate")
def translate(req: TranslateRequest):
    path = _fetch_audio(req.audio_url)
    try:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": path},
                    {
                        "type": "text",
                        "text": (
                            f"Translate this speech into {req.target_lang}. "
                            "Output only the translation."
                        ),
                    },
                ],
            }
        ]
        text = _generate(messages, max_new_tokens=256)
        return {"text": text.strip()}
    finally:
        os.unlink(path)


# ── /health ─────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"ok": True, "device": device, "model": MODEL_ID}

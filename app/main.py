from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Literal
from pathlib import Path
import os, uuid

from .utils import ensure_voice, synthesize_wav, wav_to_mp3, list_installed_voices, AUDIO_DIR

DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "es_ES")
DEFAULT_ONNX_URL = os.getenv("DEFAULT_VOICE_ONNX_URL")
DEFAULT_JSON_URL = os.getenv("DEFAULT_VOICE_JSON_URL")

app = FastAPI(title="KDvops TTS (Piper)", version="1.0")

class SpeakIn(BaseModel):
    text: str
    voice: Optional[str] = None
    onnx_url: Optional[str] = None
    json_url: Optional[str] = None
    fmt: Literal["wav","mp3"] = "mp3"
    length_scale: float = 1.0
    noise_scale: float = 0.667
    sentence_silence: float = 0.2

@app.get("/")
async def root():
    return {"service": "KDvops TTS (Piper)", "status": "ok"}

@app.get("/voices")
async def voices():
    return JSONResponse(list_installed_voices())

@app.post("/speak")
async def speak(body: SpeakIn):
    voice_key = body.voice or DEFAULT_VOICE
    try:
        onnx, cfg = await ensure_voice(
            voice_key=voice_key,
            onnx_url=body.onnx_url or DEFAULT_ONNX_URL,
            json_url=body.json_url or DEFAULT_JSON_URL,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    wav_path = AUDIO_DIR / f"{uuid.uuid4().hex}.wav"
    mp3_path = wav_path.with_suffix(".mp3")

    try:
        synthesize_wav(body.text, onnx, cfg, wav_path,
                       length_scale=body.length_scale,
                       noise_scale=body.noise_scale,
                       sentence_silence=body.sentence_silence)
        if body.fmt == "wav":
            return StreamingResponse(open(wav_path, "rb"), media_type="audio/wav")
        else:
            wav_to_mp3(wav_path, mp3_path)
            return StreamingResponse(open(mp3_path, "rb"), media_type="audio/mpeg")
    finally:
        pass

@app.get("/healthz")
async def health():
    return {"ok": True}

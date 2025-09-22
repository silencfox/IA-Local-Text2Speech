import os
import uuid
import random
from pathlib import Path
from typing import Optional, Literal, Dict

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from aiohttp import ClientSession

from .utils import (
    ensure_voice,
    synthesize_wav,
    postprocess_wav,
    wav_to_mp3,
    list_installed_voices,
    preprocess_text,
    set_user_preset,
    get_user_preset,
    AUDIO_DIR,
)

app = FastAPI(title="KDvops TTS (Piper + Expressive)", version="3.0")

# --------- Config por entorno ---------
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "es_ES")
DEFAULT_ONNX_URL = os.getenv("DEFAULT_VOICE_ONNX_URL")
DEFAULT_JSON_URL = os.getenv("DEFAULT_VOICE_JSON_URL")

# URLs de motores expresivos (opcionales)
EXPRESSIVE_API_URL_XTTS = os.getenv("EXPRESSIVE_API_URL_XTTS")           # p.ej. http://xtts:8020/generate
EXPRESSIVE_API_URL_BARK = os.getenv("EXPRESSIVE_API_URL_BARK")           # p.ej. http://bark:8030/generate
EXPRESSIVE_API_URL_OPENVOICE = os.getenv("EXPRESSIVE_API_URL_OPENVOICE") # p.ej. http://openvoice:8040/generate

# Presets Piper
PRESETS: Dict[str, Dict[str, float]] = {
    "narracion": {"length_scale": 0.92, "noise_scale": 0.50, "sentence_silence": 0.38},
    "asistente": {"length_scale": 0.98, "noise_scale": 0.45, "sentence_silence": 0.30},
    "enfatico":  {"length_scale": 0.95, "noise_scale": 0.60, "sentence_silence": 0.40},
}

class SpeakIn(BaseModel):
    # Motor a usar
    engine: Literal["piper","xtts","bark","openvoice"] = "piper"

    # Comunes
    text: str = Field(..., description="Texto a convertir a voz. Si engine=piper, admite SSML-light.")
    fmt: Literal["wav","mp3"] = "mp3"

    # Piper
    voice: Optional[str] = None
    onnx_url: Optional[str] = None
    json_url: Optional[str] = None
    preset: Optional[Literal["narracion","asistente","enfatico"]] = None
    user_id: Optional[str] = None
    length_scale: float = 1.0
    noise_scale: float = 0.667
    sentence_silence: float = 0.2
    postprocess: bool = True
    save_preset: bool = False

    # Expresivos (serán proxyeados tal cual)
    lang: Optional[str] = "es"
    style: Optional[str] = None
    speed: Optional[float] = 1.0
    temperature: Optional[float] = 0.8
    x_voice: Optional[str] = None
    ref_wav_path: Optional[str] = None

@app.get("/")
async def root():
    return {"service": "KDvops TTS", "status": "ok", "version": "3.0"}

@app.get("/voices")
async def voices():
    return JSONResponse(list_installed_voices())

@app.post("/prefs/preset")
async def save_preset(user_id: str = Query(...), preset: str = Query(...)):
    if preset not in PRESETS:
        raise HTTPException(status_code=400, detail=f"Preset inválido. Opciones: {list(PRESETS.keys())}")
    set_user_preset(user_id, preset)
    return {"ok": True, "user_id": user_id, "preset": preset}

async def _proxy_expressive(url: Optional[str], body: SpeakIn) -> Response:
    if not url:
        raise HTTPException(status_code=501, detail="Motor no configurado.")
    payload = {
        "text": body.text,
        "voice": body.x_voice,
        "style": body.style,
        "lang": body.lang or "es",
        "fmt": body.fmt,
        "speed": body.speed or 1.0,
        "temperature": body.temperature or 0.8,
        "ref_wav_path": body.ref_wav_path,
    }
    async with ClientSession() as sess:
        async with sess.post(url, json=payload) as r:
            if r.status != 200:
                raise HTTPException(status_code=r.status, detail=await r.text())
            data = await r.read()
    media = "audio/mpeg" if body.fmt == "mp3" else "audio/wav"
    return Response(content=data, media_type=media)

@app.post("/speak")
async def speak(body: SpeakIn):
    # Motores expresivos: proxy directo
    if body.engine in ("xtts", "bark", "openvoice"):
        url_map = {
            "xtts": EXPRESSIVE_API_URL_XTTS,
            "bark": EXPRESSIVE_API_URL_BARK,
            "openvoice": EXPRESSIVE_API_URL_OPENVOICE,
        }
        return await _proxy_expressive(url_map[body.engine], body)

    # ---------- Piper ----------
    pre = preprocess_text(body.text)
    text = pre["text"]
    extra = pre["extra"]

    params = {
        "length_scale": body.length_scale,
        "noise_scale":  body.noise_scale,
        "sentence_silence": body.sentence_silence
    }

    if body.user_id:
        stored = get_user_preset(body.user_id)
        if stored and stored in PRESETS:
            params.update(PRESETS[stored])

    if body.preset and body.preset in PRESETS:
        params.update(PRESETS[body.preset])

    # Ajustes por SSML-light
    params["length_scale"] *= max(min(extra.get("rate_scale", 1.0), 1.2), 0.8)
    params["noise_scale"]  += extra.get("boost_noise", 0.0)
    params["sentence_silence"] += extra.get("extra_silence", 0.0)

    # Micro-variaciones para evitar monotonía
    params["noise_scale"] = max(0.0, min(1.0, params["noise_scale"] + random.uniform(-0.03, 0.03)))
    params["sentence_silence"] = max(0.0, min(1.0, params["sentence_silence"] + random.uniform(-0.03, 0.03)))

    voice_key = body.voice or DEFAULT_VOICE
    try:
        onnx, cfg = await ensure_voice(
            voice_key=voice_key,
            onnx_url=body.onnx_url or DEFAULT_ONNX_URL,
            json_url=body.json_url or DEFAULT_JSON_URL,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    wav_raw = AUDIO_DIR / f"{uuid.uuid4().hex}_raw.wav"
    wav_pp  = AUDIO_DIR / f"{uuid.uuid4().hex}_pp.wav"
    mp3_out = wav_pp.with_suffix(".mp3")

    synthesize_wav(
        text=text,
        onnx_path=onnx,
        json_path=cfg,
        out_wav=wav_raw,
        length_scale=params["length_scale"],
        noise_scale=params["noise_scale"],
        sentence_silence=params["sentence_silence"],
    )

    final_wav = wav_raw
    if body.postprocess:
        final_wav = postprocess_wav(wav_raw, wav_pp)

    if body.fmt == "wav":
        return StreamingResponse(open(final_wav, "rb"), media_type="audio/wav")
    else:
        wav_to_mp3(final_wav, mp3_out, bitrate="256k")
        return StreamingResponse(open(mp3_out, "rb"), media_type="audio/mpeg")

@app.get("/healthz")
async def health():
    return {"ok": True}

import io
import os
import tempfile
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import soundfile as sf

# --------- Carga del modelo XTTS v2 con Coqui TTS ----------
# Nota: La primera vez descargará pesos al cache (~$HOME/.local/share/tts/), puedes
# setear TTS_HOME para cache persistente dentro del contenedor si quieres.
from TTS.api import TTS

MODEL_NAME = os.getenv("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
# Si tu host está en español por defecto, puedes adelantarlo:
DEFAULT_LANG = os.getenv("XTTS_LANG", "es")

# Carga perezosa (al primer request) para no bloquear el arranque:
_tts = None
def get_tts():
    global _tts
    if _tts is None:
        _tts = TTS(MODEL_NAME, progress_bar=False, gpu=os.getenv("USE_GPU","0")=="1")
    return _tts

app = FastAPI(title="Expressive TTS (XTTS v2)", version="1.0")

class GenIn(BaseModel):
    text: str
    voice: Optional[str] = None         # nombre de hablante interno si el modelo lo soporta
    lang: Optional[str] = None          # "es", "en", etc.
    style: Optional[str] = None         # etiqueta libre, puedes mapearla a params
    fmt: Literal["mp3","wav"] = "mp3"
    # Parámetros de expresividad
    speed: float = 1.0                  # 0.9 más pausado, 1.1 más rápido
    temperature: float = 0.8            # 0.7–1.0 da más variabilidad/expresión
    # Referencia de timbre por URL local opcional (subida en endpoint /generate_ref)
    ref_wav_path: Optional[str] = None

@app.get("/healthz")
async def health():
    return {"ok": True}

@app.post("/generate")
async def generate(body: GenIn):
    tts = get_tts()
    lang = body.lang or DEFAULT_LANG

    # Mapea "style" a parámetros simples
    temp = body.temperature
    speed = body.speed
    if body.style == "narration":
        temp = min(temp, 0.85); speed = min(speed, 0.98)
    elif body.style == "conversational":
        temp = max(temp, 0.9);  speed = 1.0
    elif body.style == "promo":
        temp = max(temp, 0.95); speed = 1.05

    # Síntesis a WAV (numpy) en memoria
    wav, sr = tts.tts(
        text=body.text,
        speaker=body.voice,             # si usas un “speaker” interno
        language=lang,
        speed=speed,
        temperature=temp,
        speaker_wav=body.ref_wav_path   # si cargas timbre de referencia
    ), 24000  # XTTS suele generar a 24k Hz

    # Guardar WAV temporal y opcionalmente convertir a MP3 con ffmpeg
    with tempfile.TemporaryDirectory() as td:
        wav_path = Path(td) / "out.wav"
        sf.write(wav_path.as_posix(), wav, sr)

        if body.fmt == "wav":
            data = Path(wav_path).read_bytes()
            return Response(content=data, media_type="audio/wav")

        # MP3 (ffmpeg)
        mp3_path = Path(td) / "out.mp3"
        os.system(f'ffmpeg -y -i "{wav_path}" -b:a 256k "{mp3_path}" >/dev/null 2>&1')
        data = Path(mp3_path).read_bytes()
        return Response(content=data, media_type="audio/mpeg")

# Subida de audio de referencia para clonación de timbre (opcional)
@app.post("/generate_ref")
async def generate_with_ref(
    text: str = Form(...),
    fmt: Literal["mp3","wav"] = Form("mp3"),
    lang: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
    speed: float = Form(1.0),
    temperature: float = Form(0.8),
    ref: UploadFile = File(...),   # archivo WAV/MP3 con el timbre
):
    # Guarda ref a disco temporal:
    with tempfile.TemporaryDirectory() as td:
        ref_path = Path(td) / f"ref_{ref.filename}"
        ref_bytes = await ref.read()
        ref_path.write_bytes(ref_bytes)

        # Si viene en MP3, conviértelo a WAV 24k mono:
        if ref.filename.lower().endswith(".mp3"):
            ref_wav = ref_path.with_suffix(".wav")
            os.system(f'ffmpeg -y -i "{ref_path}" -ar 24000 -ac 1 "{ref_wav}" >/dev/null 2>&1')
            ref_path = ref_wav

        # Reutiliza la lógica de /generate:
        body = GenIn(text=text, fmt=fmt, lang=lang, style=style, speed=speed,
                     temperature=temperature, ref_wav_path=ref_path.as_posix())
        return await generate(body)

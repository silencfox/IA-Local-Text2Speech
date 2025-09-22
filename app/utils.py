import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Optional
from aiohttp import ClientSession

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
MODELS_DIR = DATA_DIR / "models"
AUDIO_DIR = DATA_DIR / "audio"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_name(name: str) -> str:
    return SAFE_NAME_RE.sub("_", name.strip())

def voice_paths(voice_key: str):
    vdir = MODELS_DIR / safe_name(voice_key)
    onnx, cfg = None, None
    if vdir.exists():
        for p in vdir.iterdir():
            if p.suffix == ".onnx":
                onnx = p
            elif p.suffix == ".json":
                cfg = p
    return vdir, onnx, cfg

async def download_file(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    async with ClientSession() as sess:
        async with sess.get(url) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in resp.content.iter_chunked(1 << 14):
                    f.write(chunk)
    tmp.replace(dest)

async def ensure_voice(voice_key: str, onnx_url: Optional[str] = None, json_url: Optional[str] = None):
    vdir, onnx, cfg = voice_paths(voice_key)
    vdir.mkdir(parents=True, exist_ok=True)

    if onnx is None and onnx_url:
        onnx = vdir / Path(onnx_url).name
        if not onnx.exists():
            await download_file(onnx_url, onnx)

    if cfg is None and json_url:
        cfg = vdir / Path(json_url).name
        if not cfg.exists():
            await download_file(json_url, cfg)

    if not onnx or not onnx.exists():
        raise FileNotFoundError("Modelo .onnx no encontrado")
    if not cfg or not cfg.exists():
        maybe = Path(str(onnx) + ".json")
        if maybe.exists():
            cfg = maybe
        else:
            raise FileNotFoundError("Archivo de configuración .json no encontrado")
    return onnx, cfg

def synthesize_wav(text: str, onnx_path: Path, json_path: Path, out_wav: Path,
                   length_scale: float = 1.0, noise_scale: float = 0.667, sentence_silence: float = 0.2):
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "piper",
        "--model", str(onnx_path),
        "--config", str(json_path),
        "--length_scale", str(length_scale),
        "--noise_scale", str(noise_scale),
        "--sentence_silence", str(sentence_silence),
        "--output_file", str(out_wav),
    ]
    proc = subprocess.run(cmd, input=text.encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"piper falló: {proc.stderr.decode(errors='ignore')}")
    return out_wav

def wav_to_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "192k"):
    cmd = ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", bitrate, str(mp3_path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló: {proc.stderr.decode(errors='ignore')}")
    return mp3_path

def list_installed_voices():
    out = []
    if MODELS_DIR.exists():
        for d in MODELS_DIR.iterdir():
            if d.is_dir():
                onnx = next(d.glob("*.onnx"), None)
                cfg = next(d.glob("*.json"), None)
                if onnx and cfg:
                    out.append({"key": d.name, "onnx": onnx.name, "json": cfg.name})
    return out

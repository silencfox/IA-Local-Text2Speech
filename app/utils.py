import os
import re
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from aiohttp import ClientSession

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
MODELS_DIR = DATA_DIR / "models"
AUDIO_DIR = DATA_DIR / "audio"
CONFIG_DIR = DATA_DIR / "config"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Archivos de configuración/persistencia
PRON_DICT_FILE = CONFIG_DIR / "pron_dict.json"   # usaremos JSON por simplicidad
PREFS_FILE = CONFIG_DIR / "prefs.json"

SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
CONNECTORS_RE = re.compile(
    r"\b(sin embargo|además|por lo tanto|en cambio|por consiguiente|no obstante)\b",
    re.IGNORECASE
)

# --------- Utilidades generales ---------
def safe_name(name: str) -> str:
    return SAFE_NAME_RE.sub("_", name.strip())

def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# --------- Gestión de voces Piper ---------
def voice_paths(voice_key: str):
    vdir = MODELS_DIR / safe_name(voice_key)
    onnx = None
    cfg = None
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
                async for chunk in resp.content.iter_chunked(1 << 15):
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
        raise FileNotFoundError("Modelo .onnx no encontrado para la voz seleccionada.")
    if not cfg or not cfg.exists():
        maybe = Path(str(onnx) + ".json")
        if maybe.exists():
            cfg = maybe
        else:
            raise FileNotFoundError("Archivo de configuración .json no encontrado para la voz seleccionada.")
    return onnx, cfg

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

# --------- Preprocesador de texto + “SSML light” ---------
def _ensure_pron_dict_example() -> Dict[str, str]:
    if not PRON_DICT_FILE.exists():
        sample = {
            "KDvops": "kei di vops",
            "DevOps": "dé vops",
            "Kubernetes": "ku-ber-né-tes"
        }
        write_json(PRON_DICT_FILE, sample)
        return sample
    return read_json(PRON_DICT_FILE, {})

def apply_pron_dict(text: str, mapping: Dict[str, str]) -> str:
    # Reemplazo simple de palabra completa (sensitivo a mayúsculas mínimamente)
    for k, v in mapping.items():
        text = re.sub(rf"\b{k}\b", v, text)
    return text

def apply_connectors(text: str) -> str:
    # Inserta coma tras conectores si no hay puntuación inmediata
    def _comma_after(m):
        w = m.group(0)
        return w + ","
    return CONNECTORS_RE.sub(_comma_after, text)

def normalize_sentences(text: str) -> str:
    # Normaliza espacios y asegura un cierre de frase
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?¡¿…":
        text += "."
    return text

def parse_ssml_light(text: str) -> Dict[str, Any]:
    """
    Soporte mínimo:
      <break time="400ms"> -> añade "..." y sugiere silencio extra
      <emphasis>...</emphasis> -> sugiere boost de noise
      <prosody rate="slow|medium|fast">...</prosody> -> sugiere ajuste de length_scale
    """
    extra = {"boost_noise": 0.0, "rate_scale": 1.0, "extra_silence": 0.0}

    # <break time="Xms">
    for m in re.finditer(r"<break\s+time=\"(\d+)ms\"\s*/?>", text, re.IGNORECASE):
        ms = int(m.group(1))
        extra["extra_silence"] += min(max(ms / 1000.0, 0.0), 1.0)  # cap 1s
    text = re.sub(r"<break\s+time=\"\d+ms\"\s*/?>", "...", text, flags=re.IGNORECASE)

    # <emphasis>
    if re.search(r"</?\s*emphasis\s*>", text, re.IGNORECASE):
        extra["boost_noise"] += 0.05
        text = re.sub(r"</?\s*emphasis\s*>", "", text, flags=re.IGNORECASE)

    # <prosody rate="...">
    m = re.search(r"<prosody\s+rate=\"(slow|medium|fast)\"\s*>(.*?)</\s*prosody\s*>",
                  text, re.IGNORECASE | re.DOTALL)
    while m:
        rate = m.group(1).lower()
        inner = m.group(2)
        if rate == "slow":
            extra["rate_scale"] *= 0.95
        elif rate == "fast":
            extra["rate_scale"] *= 1.05
        text = text.replace(m.group(0), inner)
        m = re.search(r"<prosody\s+rate=\"(slow|medium|fast)\"\s*>(.*?)</\s*prosody\s*>",
                      text, re.IGNORECASE | re.DOTALL)

    return {"text": text, "extra": extra}

def preprocess_text(raw_text: str) -> Dict[str, Any]:
    ssml = parse_ssml_light(raw_text)
    text = ssml["text"]
    extra = ssml["extra"]
    text = apply_connectors(text)
    text = normalize_sentences(text)
    mapping = _ensure_pron_dict_example()
    text = apply_pron_dict(text, mapping)
    return {"text": text, "extra": extra}

# --------- Síntesis y post-proceso de audio (Piper) ---------
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
    proc = subprocess.run(cmd, input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"piper falló: {proc.stderr.decode(errors='ignore')}")
    return out_wav

def postprocess_wav(in_wav: Path, out_wav: Path) -> Path:
    """
    ffmpeg chain: loudnorm -> acompressor -> deesser -> afade in/out
    """
    af = (
        "loudnorm=I=-16:LRA=11:TP=-1.5,"
        "acompressor=threshold=-20dB:ratio=3:attack=5:release=50,"
        "deesser,"
        "afade=t=in:ss=0:d=0.02,afade=t=out:st=dur-0.04:d=0.04"
    )
    cmd = ["ffmpeg", "-y", "-i", str(in_wav), "-af", af, str(out_wav)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg post-proceso falló: {proc.stderr.decode(errors='ignore')}")
    return out_wav

def wav_to_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "256k"):
    cmd = ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", bitrate, str(mp3_path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg MP3 falló: {proc.stderr.decode(errors='ignore')}")
    return mp3_path

# --------- Preferencias por “usuario/caso” (Piper) ---------
def get_prefs() -> Dict[str, Any]:
    return read_json(PREFS_FILE, {})

def set_user_preset(user_id: str, preset: str) -> None:
    prefs = get_prefs()
    prefs.setdefault("users", {})[user_id] = {"preset": preset}
    write_json(PREFS_FILE, prefs)

def get_user_preset(user_id: str) -> Optional[str]:
    prefs = get_prefs()
    return prefs.get("users", {}).get(user_id, {}).get("preset")

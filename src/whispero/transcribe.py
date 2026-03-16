from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

_model = None
_model_size: str | None = None


def get_model_cache_dir() -> Path:
    cache_dir = Path.home() / ".whispero" / "models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def is_model_cached(model_size: str = "large-v3") -> bool:
    repo_dir = get_model_cache_dir() / f"models--Systran--faster-whisper-{model_size}"
    if not repo_dir.exists():
        return False

    for extension in ("*.bin", "*.safetensors"):
        if any(repo_dir.rglob(extension)):
            return True

    snapshots_dir = repo_dir / "snapshots"
    return snapshots_dir.exists() and any(path.is_file() for path in snapshots_dir.rglob("*"))


def get_model(model_size: str = "large-v3"):
    global _model, _model_size

    if _model is not None and _model_size == model_size:
        return _model

    try:
        from faster_whisper import WhisperModel
    except ImportError as err:
        raise RuntimeError(
            "faster-whisper is not installed. Run `pip install faster-whisper`."
        ) from err

    # PyInstaller frozen builds segfault on CTranslate2 CUDA init.
    # Use CPU in .exe, GPU works from `python -m whispero`.
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        device = "cpu"
        compute = "auto"
    else:
        device = "auto"
        compute = "auto"

    _model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute,
        download_root=str(get_model_cache_dir()),
    )
    _model_size = model_size

    # Log device info
    try:
        import ctranslate2
        cuda_available = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        cuda_available = False

    if device == "cpu" or (device == "auto" and not cuda_available):
        device_label = "CPU"
    else:
        device_label = "GPU"
        try:
            import torch
            if torch.cuda.is_available():
                device_label = f"GPU ({torch.cuda.get_device_name(0)})"
        except Exception:
            pass

    print(f"  😮 Model: {model_size} | Device: {device_label}")

    return _model


def transcribe_server(audio_buf: io.BytesIO, server: str, prompt: str = "") -> str | None:
    """Send audio to whisper.cpp server and return transcribed text."""
    print("  📡 Sending to server...")
    try:
        audio_buf.seek(0)
        post_data = {"response_format": "text"}
        if prompt:
            post_data["prompt"] = prompt

        resp = requests.post(
            f"{server}/inference",
            files={"file": ("audio.wav", audio_buf, "audio/wav")},
            data=post_data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text.strip()
    except requests.ConnectionError:
        print("  ❌ Cannot reach server.", file=sys.stderr)
        return None
    except requests.Timeout:
        print("  ❌ Server timeout", file=sys.stderr)
        return None
    except requests.HTTPError as err:
        print(f"  ❌ Server error: {err}", file=sys.stderr)
        return None


def transcribe_local(audio_buf: io.BytesIO, model_size: str = "large-v3", prompt: str = "") -> str | None:
    """Transcribe audio using local faster-whisper model."""
    try:
        model = get_model(model_size)
        audio_buf.seek(0)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_buf.read())
            tmp_path = tmp.name

        try:
            segments, _info = model.transcribe(tmp_path, initial_prompt=prompt)
            return " ".join(seg.text for seg in segments).strip()
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
    except Exception as err:
        print(f"  ❌ Local transcription error: {err}", file=sys.stderr)
        return None


def transcribe(
    audio_buf: io.BytesIO,
    config: dict[str, Any] | None = None,
    server: str | None = None,
    prompt: str = "",
    backend: str | None = None,
    model_size: str | None = None,
) -> str | None:
    """Transcribe using configured backend (local faster-whisper or remote server)."""
    cfg = config or {}
    backend_name = (backend or cfg.get("backend") or ("server" if server else "local")).lower()

    if backend_name == "server":
        server_url = server or cfg.get("server", "http://localhost:8080")
        servers = [server_url] + cfg.get("fallback_servers", [])
        for url in servers:
            audio_buf.seek(0)
            result = transcribe_server(audio_buf=audio_buf, server=url, prompt=prompt)
            if result is not None:
                return result
        # All servers unreachable — fall back to local
        print("  ⚡ All servers unavailable, falling back to local...")
        audio_buf.seek(0)
        resolved_model = model_size or cfg.get("model", "large-v3")
        return transcribe_local(audio_buf=audio_buf, model_size=resolved_model, prompt=prompt)

    resolved_model = model_size or cfg.get("model", "large-v3")
    return transcribe_local(audio_buf=audio_buf, model_size=resolved_model, prompt=prompt)

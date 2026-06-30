from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_REWRITE_PROMPT = (
    "Rewrite the dictated text to fix transcription mistakes, grammar, "
    "punctuation, casing, spacing, and spoken punctuation words such as "
    "comma, period, question mark, and new line while preserving the speaker's meaning. "
    "Remove clear false starts and self-correction markers while keeping the final "
    "intended meaning. Do not remove meaningful words just because they are conversational. "
    "Return only the rewritten text. Do not include explanations, labels, "
    "markdown, or reasoning."
)

DEFAULTS = {
    "backend": "local",
    "server": "http://localhost:8080",
    "model": "large-v3",
    "hotkey": {"windows": ["win", "ctrl"], "mac": ["cmd", "ctrl"]},
    "sounds": True,
    "rewrite": {
        "enabled": False,
        "model_path": "",
        "prompt": DEFAULT_REWRITE_PROMPT,
        "context_window": 2048,
        "max_tokens": 192,
        "temperature": 0.2,
        "threads": 0,
        "gpu_layers": -1,
    },
}

VALID_BACKENDS = {"local", "server"}
VALID_MODELS = {"large-v3", "medium", "small", "base", "tiny"}

CONFIG_DIR = Path.home() / ".whispero"
CONFIG_PATH = CONFIG_DIR / "config.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _coerce_float(value: Any, default: float, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _load_config_file() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _normalize(config: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(config)

    backend = str(normalized.get("backend", DEFAULTS["backend"])).lower()
    normalized["backend"] = backend if backend in VALID_BACKENDS else DEFAULTS["backend"]

    model = str(normalized.get("model", DEFAULTS["model"])).lower()
    normalized["model"] = model if model in VALID_MODELS else DEFAULTS["model"]

    normalized["server"] = str(normalized.get("server", DEFAULTS["server"]))

    rewrite = normalized.get("rewrite")
    if not isinstance(rewrite, dict):
        rewrite = {}
    rewrite_defaults = DEFAULTS["rewrite"]
    normalized["rewrite"] = {
        "enabled": _coerce_bool(rewrite.get("enabled"), rewrite_defaults["enabled"]),
        "model_path": str(rewrite.get("model_path") or rewrite_defaults["model_path"]),
        "prompt": str(rewrite.get("prompt") or rewrite_defaults["prompt"]),
        "context_window": _coerce_int(
            rewrite.get("context_window"),
            rewrite_defaults["context_window"],
            minimum=512,
        ),
        "max_tokens": _coerce_int(
            rewrite.get("max_tokens"),
            rewrite_defaults["max_tokens"],
            minimum=1,
        ),
        "temperature": _coerce_float(
            rewrite.get("temperature"),
            rewrite_defaults["temperature"],
            minimum=0.0,
        ),
        "threads": _coerce_int(rewrite.get("threads"), rewrite_defaults["threads"], minimum=0),
        "gpu_layers": _coerce_int(rewrite.get("gpu_layers"), rewrite_defaults["gpu_layers"]),
    }
    return normalized


def _apply_env(config: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(config)

    env_backend = os.environ.get("WHISPERO_BACKEND")
    if env_backend:
        backend = env_backend.strip().lower()
        if backend in VALID_BACKENDS:
            updated["backend"] = backend

    env_server = os.environ.get("WHISPERO_SERVER")
    if env_server:
        updated["server"] = env_server

    env_model = os.environ.get("WHISPERO_MODEL")
    if env_model:
        model = env_model.strip().lower()
        if model in VALID_MODELS:
            updated["model"] = model

    rewrite_config = updated.get("rewrite")
    rewrite = deepcopy(rewrite_config) if isinstance(rewrite_config, dict) else deepcopy(DEFAULTS["rewrite"])

    env_rewrite = os.environ.get("WHISPERO_REWRITE")
    if env_rewrite is not None:
        rewrite["enabled"] = _coerce_bool(env_rewrite, bool(rewrite.get("enabled")))

    env_rewrite_model_path = os.environ.get("WHISPERO_REWRITE_MODEL_PATH")
    if env_rewrite_model_path:
        rewrite["model_path"] = env_rewrite_model_path.strip()

    env_rewrite_prompt = os.environ.get("WHISPERO_REWRITE_PROMPT")
    if env_rewrite_prompt:
        rewrite["prompt"] = env_rewrite_prompt

    env_rewrite_context_window = os.environ.get("WHISPERO_REWRITE_CONTEXT_WINDOW")
    if env_rewrite_context_window:
        rewrite["context_window"] = env_rewrite_context_window

    env_rewrite_max_tokens = os.environ.get("WHISPERO_REWRITE_MAX_TOKENS")
    if env_rewrite_max_tokens:
        rewrite["max_tokens"] = env_rewrite_max_tokens

    env_rewrite_temperature = os.environ.get("WHISPERO_REWRITE_TEMPERATURE")
    if env_rewrite_temperature:
        rewrite["temperature"] = env_rewrite_temperature

    env_rewrite_threads = os.environ.get("WHISPERO_REWRITE_THREADS")
    if env_rewrite_threads:
        rewrite["threads"] = env_rewrite_threads

    env_rewrite_gpu_layers = os.environ.get("WHISPERO_REWRITE_GPU_LAYERS")
    if env_rewrite_gpu_layers:
        rewrite["gpu_layers"] = env_rewrite_gpu_layers

    updated["rewrite"] = rewrite

    return updated


def save_config_value(key: str, value: Any) -> None:
    """Update a single key in the user config file, preserving other settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    file_config = _load_config_file()
    file_config[key] = value
    CONFIG_PATH.write_text(json.dumps(file_config, indent=2) + "\n", encoding="utf-8")


def save_rewrite_enabled(enabled: bool) -> None:
    """Persist only the rewrite enabled flag, preserving other rewrite settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    file_config = _load_config_file()
    rewrite = file_config.get("rewrite")
    if not isinstance(rewrite, dict):
        rewrite = {}
    rewrite["enabled"] = enabled
    file_config["rewrite"] = rewrite
    CONFIG_PATH.write_text(json.dumps(file_config, indent=2) + "\n", encoding="utf-8")


def save_rewrite_config(values: dict[str, Any]) -> None:
    """Update rewrite settings in the user config file, preserving other settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    file_config = _load_config_file()
    rewrite = file_config.get("rewrite")
    if not isinstance(rewrite, dict):
        rewrite = {}
    rewrite.update(values)
    file_config["rewrite"] = rewrite
    CONFIG_PATH.write_text(json.dumps(file_config, indent=2) + "\n", encoding="utf-8")


def load_config() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    file_config = _load_config_file()
    merged = _deep_merge(DEFAULTS, file_config)
    env_applied = _apply_env(merged)
    return _normalize(env_applied)

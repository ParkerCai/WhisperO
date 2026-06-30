from __future__ import annotations

import importlib
import os
import platform
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import requests

DEFAULT_REWRITE_MODEL_REPO = "Qwen/Qwen3-1.7B-GGUF"
DEFAULT_REWRITE_MODEL_FILE = "Qwen3-1.7B-Q8_0.gguf"
DEFAULT_REWRITE_MODEL_SIZE = 1_834_426_016
DEFAULT_REWRITE_MODEL_URL = (
    f"https://huggingface.co/{DEFAULT_REWRITE_MODEL_REPO}/resolve/main/"
    f"{DEFAULT_REWRITE_MODEL_FILE}?download=true"
)
REWRITE_RUNTIME_PACKAGE = "llama-cpp-python>=0.3.32"
REWRITE_RUNTIME_CUDA_INDEX_URL = "https://abetlen.github.io/llama-cpp-python/whl/cu124"

_llm = None
_llm_key: tuple[str, int, int, int] | None = None
_rewrite_lock = threading.Lock()


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


def _resolve_model_path(value: Any) -> Path | None:
    raw_path = str(value or "").strip()
    if not raw_path:
        return get_default_rewrite_model_path()
    return Path(raw_path).expanduser()


def _has_rewrite_runtime() -> bool:
    try:
        importlib.import_module("llama_cpp")
        return True
    except ImportError:
        return False


def _rewrite_runtime_install_command() -> list[str]:
    command = [sys.executable, "-m", "pip", "install", REWRITE_RUNTIME_PACKAGE]
    if sys.platform.startswith("win"):
        command.extend(["--extra-index-url", REWRITE_RUNTIME_CUDA_INDEX_URL])
    return command


def _rewrite_runtime_install_env() -> dict[str, str]:
    env = os.environ.copy()
    if sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        cmake_args = env.get("CMAKE_ARGS", "").strip()
        metal_arg = "-DGGML_METAL=on"
        env["CMAKE_ARGS"] = f"{cmake_args} {metal_arg}".strip() if metal_arg not in cmake_args else cmake_args
    return env


def _format_command_for_display(command: list[str]) -> str:
    quoted = []
    for arg in command:
        if any(char in arg for char in ' <>|&^"'):
            escaped_arg = arg.replace('"', '\\"')
            quoted.append(f'"{escaped_arg}"')
        else:
            quoted.append(arg)
    return " ".join(quoted)


def ensure_rewrite_runtime() -> None:
    """Install the optional local rewrite runtime into the current Python if missing."""
    if _has_rewrite_runtime():
        return

    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "llama-cpp-python is not bundled in this app. Rebuild WhisperO with "
            "the rewrite runtime installed."
        )

    command = _rewrite_runtime_install_command()
    display_command = _format_command_for_display(command)
    print("  Installing local rewrite runtime...")
    print(f"  Command: {display_command}")

    try:
        result = subprocess.run(command, env=_rewrite_runtime_install_env(), check=False)
    except Exception as err:
        raise RuntimeError(f"failed to install llama-cpp-python: {err}") from err

    if result.returncode != 0:
        raise RuntimeError(
            "failed to install llama-cpp-python. Run this manually and try again: "
            f"{display_command}"
        )

    importlib.invalidate_caches()
    if not _has_rewrite_runtime():
        raise RuntimeError("llama-cpp-python installed, but could not be imported")

    print("  Local rewrite runtime installed")


def get_rewrite_model_dir() -> Path:
    model_dir = Path.home() / ".whispero" / "rewrite-models"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def get_default_rewrite_model_path() -> Path:
    return get_rewrite_model_dir() / DEFAULT_REWRITE_MODEL_FILE


def is_rewrite_model_cached(model_path: Path | None = None) -> bool:
    path = model_path or get_default_rewrite_model_path()
    if not path.exists():
        return False
    if path.name == DEFAULT_REWRITE_MODEL_FILE:
        return path.stat().st_size >= DEFAULT_REWRITE_MODEL_SIZE
    return path.stat().st_size > 0


def ensure_rewrite_model(rewrite_config: dict[str, Any] | None = None) -> Path:
    """Ensure the local rewrite model exists, downloading the default when needed."""
    cfg = rewrite_config if isinstance(rewrite_config, dict) else {}
    configured_path = str(cfg.get("model_path") or "").strip()
    model_path = _resolve_model_path(configured_path)
    if model_path is None:
        raise RuntimeError("rewrite.model_path is not configured")

    if configured_path and not model_path.exists():
        raise RuntimeError(f"rewrite model not found: {model_path}")
    if is_rewrite_model_cached(model_path):
        return model_path
    if configured_path:
        raise RuntimeError(f"rewrite model is incomplete: {model_path}")

    model_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = model_path.with_suffix(f"{model_path.suffix}.part")
    print(f"  Downloading rewrite model: {DEFAULT_REWRITE_MODEL_FILE}")
    print(f"  Source: {DEFAULT_REWRITE_MODEL_REPO}")

    try:
        with requests.get(DEFAULT_REWRITE_MODEL_URL, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            downloaded = 0
            next_report = 0
            with partial_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        mb = downloaded / (1024 * 1024)
                        total_mb = DEFAULT_REWRITE_MODEL_SIZE / (1024 * 1024)
                        print(f"  Rewrite model download: {mb:.0f}/{total_mb:.0f} MB")
                        next_report += 256 * 1024 * 1024
        partial_path.replace(model_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    if not is_rewrite_model_cached(model_path):
        raise RuntimeError(f"downloaded rewrite model is incomplete: {model_path}")

    print("  Rewrite model downloaded")
    return model_path


def _extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    choice = choices[0]
    if not isinstance(choice, dict):
        return ""

    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

    text = choice.get("text")
    return text.strip() if isinstance(text, str) else ""


def _completion_prompt(system_prompt: str, text: str) -> str:
    return (
        f"{system_prompt}\n\n"
        f"Text to rewrite:\n{text}\n\n"
        "/no_think\n\n"
        "Rewritten text:"
    )


def _apply_spoken_punctuation(text: str) -> str:
    replacements = [
        (r"\bnew paragraph\b", "\n\n"),
        (r"\bnew line\b", "\n"),
        (r"\bquestion mark\b", "?"),
        (r"\bexclamation (?:point|mark)\b", "!"),
        (r"\bfull stop\b", "."),
        (r"\bcomma\b", ","),
        (r"\bsemicolon\b", ";"),
    ]

    rewritten = text
    for pattern, replacement in replacements:
        rewritten = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)

    rewritten = re.sub(r"\s+([,.;:?!])", r"\1", rewritten)
    rewritten = re.sub(r"([,.;:?!])(?=\S)", r"\1 ", rewritten)
    rewritten = re.sub(r"[ \t]+\n", "\n", rewritten)
    rewritten = re.sub(r"\n[ \t]+", "\n", rewritten)
    return rewritten.strip()


def _apply_semantic_cleanup(text: str) -> str:
    rewritten = text.strip()

    # Leading "actually" is usually a preface in dictated commands. Mid-sentence
    # "actually" can carry meaning, so leave it for the model to judge.
    rewritten = re.sub(r"^\s*actually\s*,?\s+", "", rewritten, flags=re.IGNORECASE)

    # "scratch that" and similar markers discard the false start before them.
    discard_before = re.search(
        r"\b(?:scratch that|no wait|wait no|what i meant was)\b\s*,?\s*",
        rewritten,
        flags=re.IGNORECASE,
    )
    if discard_before and discard_before.end() < len(rewritten):
        rewritten = rewritten[discard_before.end():].strip()

    # "actually never mind" is usually a mid-sentence course correction; keep
    # the surrounding content and remove only the correction marker.
    rewritten = re.sub(
        r"\bactually\s*,?\s*never mind\b\s*,?\s*",
        " ",
        rewritten,
        flags=re.IGNORECASE,
    )

    rewritten = re.sub(r"\s+([,.;:?!])", r"\1", rewritten)
    rewritten = re.sub(r"\s{2,}", " ", rewritten)
    return rewritten.strip()


def _clean_rewrite_output(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"^\s*<think>.*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = cleaned.strip()

    for prefix in ("Rewritten text:", "Rewrite:", "Output:", "Result:"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):].strip()

    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()

    if cleaned and cleaned[0].islower():
        cleaned = f"{cleaned[0].upper()}{cleaned[1:]}"

    return cleaned


def _load_model(rewrite_config: dict[str, Any]):
    global _llm, _llm_key

    model_path = _resolve_model_path(rewrite_config.get("model_path"))
    if model_path is None:
        raise RuntimeError("rewrite.model_path is not configured")
    if not model_path.exists():
        model_path = ensure_rewrite_model(rewrite_config)

    context_window = _coerce_int(rewrite_config.get("context_window"), 2048, minimum=512)
    threads = _coerce_int(rewrite_config.get("threads"), 0, minimum=0)
    gpu_layers = _coerce_int(rewrite_config.get("gpu_layers"), -1)
    key = (str(model_path.resolve()), context_window, threads, gpu_layers)

    if _llm is not None and _llm_key == key:
        return _llm

    ensure_rewrite_runtime()
    from llama_cpp import Llama

    kwargs = {
        "model_path": str(model_path),
        "n_ctx": context_window,
        "n_gpu_layers": gpu_layers,
        "verbose": False,
    }
    if threads > 0:
        kwargs["n_threads"] = threads

    print(f"  Loading rewrite model: {model_path.name}")
    _llm = Llama(**kwargs)
    _llm_key = key
    print("  Rewrite model ready")
    return _llm


def warm_rewrite_model(rewrite_config: dict[str, Any]) -> None:
    """Load the configured rewrite model without generating text."""
    _load_model(rewrite_config)


def _run_chat_rewrite(llm, prompt: str, original: str, max_tokens: int, temperature: float) -> str:
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"{original}\n\n/no_think"},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _extract_text(response)


def _run_completion_rewrite(llm, prompt: str, original: str, max_tokens: int, temperature: float) -> str:
    response = llm(
        _completion_prompt(prompt, original),
        max_tokens=max_tokens,
        temperature=temperature,
        echo=False,
        stop=["</s>", "<|eot_id|>", "<|im_end|>"],
    )
    return _extract_text(response)


def rewrite_text(text: str, config: dict[str, Any]) -> str:
    """Rewrite transcribed text with a local GGUF model."""
    rewrite_config = config.get("rewrite", {})
    if not isinstance(rewrite_config, dict) or not rewrite_config.get("enabled"):
        return text

    original = _apply_semantic_cleanup(_apply_spoken_punctuation(text.strip()))
    if not original:
        return text

    prompt = str(rewrite_config.get("prompt") or "").strip()
    max_tokens = _coerce_int(rewrite_config.get("max_tokens"), 192, minimum=1)
    temperature = _coerce_float(rewrite_config.get("temperature"), 0.2, minimum=0.0)

    with _rewrite_lock:
        try:
            llm = _load_model(rewrite_config)
            print("  Rewriting locally...")
            try:
                rewritten = _run_chat_rewrite(llm, prompt, original, max_tokens, temperature)
            except Exception:
                rewritten = _run_completion_rewrite(llm, prompt, original, max_tokens, temperature)
        except Exception as err:
            print(f"  Local rewrite unavailable: {err}; using original text", file=sys.stderr)
            return text

    rewritten = _clean_rewrite_output(rewritten)
    if not rewritten:
        print("  Local rewrite returned no text; using original text", file=sys.stderr)
        return text

    return rewritten

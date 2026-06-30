#!/usr/bin/env python3
"""
WhisperO Benchmark
Records a short audio clip and benchmarks transcription speed, or benchmarks
the optional local rewrite model.

Usage:
    python benchmark.py                          # local mode (default)
    python benchmark.py --backend server --server http://host:8080
    python benchmark.py --runs 5 --seconds 3
    python benchmark.py --rewrite --runs 10
"""

import argparse
import contextlib
import io
import importlib.metadata
import platform
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path

SAMPLE_RATE = 16000

REWRITE_SAMPLES = [
    "this is way too slow comma actually never mind lets try it again",
    "send this to alex scratch that send it to sarah instead",
    "can you make the intro shorter and then new line add the deployment notes",
    "actually the build should use the local model and never call a remote api",
]


def record_clip(seconds=5):
    try:
        import sounddevice as sd
    except ImportError:
        print("Install sounddevice: pip install sounddevice numpy")
        raise SystemExit(1)

    print(f"Recording {seconds}s of audio... speak now!")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=1, dtype="int16", blocking=True)
    print("Done recording.\n")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    buf.seek(0)
    return buf


def benchmark_local(audio_buf, runs=10, model_size="large-v3"):
    from whispero.transcribe import transcribe_local, get_model

    print(f"Loading model ({model_size})...")
    get_model(model_size)
    print("Model ready.\n")

    times = []
    for i in range(runs):
        audio_buf.seek(0)
        start = time.perf_counter()
        text = transcribe_local(audio_buf, model_size=model_size)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

        if i == 0:
            print(f"Transcription: \"{text}\"\n")
        print(f"  Run {i+1}/{runs}: {elapsed:.0f}ms")

    return times


def benchmark_server(audio_buf, runs=10, server="http://localhost:8080"):
    import requests

    times = []
    for i in range(runs):
        audio_buf.seek(0)
        start = time.perf_counter()
        resp = requests.post(
            f"{server}/inference",
            files={"file": ("audio.wav", audio_buf, "audio/wav")},
            data={"response_format": "text"},
            timeout=60,
        )
        elapsed = (time.perf_counter() - start) * 1000
        resp.raise_for_status()
        text = resp.text.strip()
        times.append(elapsed)

        if i == 0:
            print(f"Transcription: \"{text}\"\n")
        print(f"  Run {i+1}/{runs}: {elapsed:.0f}ms")

    return times


def _format_ms(value):
    if value >= 1000:
        return f"{value / 1000:.2f}s"
    return f"{value:.0f}ms"


def _markdown_cell(value):
    return str(value).replace("|", "\\|")


def _detect_hardware():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            gpu = result.stdout.strip().splitlines()[0].strip()
            if gpu:
                return gpu
    except Exception:
        pass

    if platform.system() == "Darwin":
        return f"Apple {platform.machine()}"

    processor = platform.processor()
    return processor or platform.machine() or "local machine"


def _llama_runtime():
    try:
        version = importlib.metadata.version("llama-cpp-python")
        return f"llama-cpp-python {version}"
    except importlib.metadata.PackageNotFoundError:
        return "llama-cpp-python"


def _rewrite_config_from_args(args):
    from whispero.config import load_config

    config = load_config()
    rewrite_config = dict(config.get("rewrite", {}))
    rewrite_config.update(
        {
            "enabled": True,
            "context_window": args.rewrite_context_window,
            "max_tokens": args.rewrite_max_tokens,
            "temperature": args.rewrite_temperature,
            "threads": args.rewrite_threads,
            "gpu_layers": args.rewrite_gpu_layers,
        }
    )
    if args.rewrite_model:
        rewrite_config["model_path"] = args.rewrite_model
    config["rewrite"] = rewrite_config
    return config


def benchmark_rewrite(args):
    from whispero import rewrite as rewrite_module

    rewrite_module.ensure_rewrite_runtime()

    config = _rewrite_config_from_args(args)
    rewrite_config = config["rewrite"]
    samples = args.rewrite_sample or REWRITE_SAMPLES

    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    model_path = rewrite_module.ensure_rewrite_model(rewrite_config)
    rewrite_config["model_path"] = str(model_path)

    print(f"Rewrite model: {model_path}")
    print(f"Samples: {len(samples)}")
    print("Download, model load, and warmup time are excluded from the benchmark.\n")

    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        rewrite_module.warm_rewrite_model(rewrite_config)

    if getattr(rewrite_module, "_llm", None) is None:
        raise SystemExit("Rewrite model did not load; benchmark aborted.")

    if args.rewrite_warmups < 0:
        raise SystemExit("--rewrite-warmups cannot be negative")

    for i in range(args.rewrite_warmups):
        sample = samples[i % len(samples)]
        with contextlib.redirect_stdout(capture):
            warmup_output = rewrite_module.rewrite_text(sample, config)
        if warmup_output.strip() == sample.strip():
            print(
                "Warning: warmup rewrite output matched the input. "
                "Check that the model is rewriting successfully.",
                file=sys.stderr,
            )

    times = []
    for i in range(args.runs):
        sample = samples[i % len(samples)]
        start = time.perf_counter()
        with contextlib.redirect_stdout(capture):
            rewritten = rewrite_module.rewrite_text(sample, config)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

        if args.verbose:
            print(f"Run {i + 1}/{args.runs}: {elapsed:.0f}ms")
            print(f"  in:  {sample}")
            print(f"  out: {rewritten}\n")

    print_rewrite_results(
        model_path=model_path,
        runtime=_llama_runtime(),
        hardware=args.hardware or _detect_hardware(),
        times=times,
        runs=args.runs,
        rewrite_config=rewrite_config,
    )


def print_rewrite_results(model_path, runtime, hardware, times, runs, rewrite_config):
    model_name = Path(model_path).stem

    print("Rewrite benchmark")
    print()
    print(
        "| Model | Runtime | Device | Median | Avg |"
    )
    print("|---|---|---|---:|---:|")
    print(
        f"| {_markdown_cell(model_name)} "
        f"| {_markdown_cell(runtime)} "
        f"| {_markdown_cell(hardware)} "
        f"| {_format_ms(statistics.median(times))} "
        f"| {_format_ms(sum(times) / len(times))} "
        "|"
    )
    print()


def print_results(times, runs):
    print(f"\n{'='*40}")
    print(f"Results ({runs} runs):")
    print(f"  Average: {sum(times)/len(times):.0f}ms")
    print(f"  Min:     {min(times):.0f}ms")
    print(f"  Max:     {max(times):.0f}ms")
    print(f"  Median:  {sorted(times)[len(times)//2]:.0f}ms")
    print(f"{'='*40}")


def main():
    parser = argparse.ArgumentParser(description="WhisperO Benchmark")
    parser.add_argument("--rewrite", action="store_true",
                        help="Benchmark the local rewrite model instead of transcription")
    parser.add_argument("--backend", default="local", choices=["local", "server"],
                        help="Backend to benchmark (default: local)")
    parser.add_argument("--model", default="large-v3", help="Model size for local mode")
    parser.add_argument("--server", default="http://localhost:8080", help="Server URL for server mode")
    parser.add_argument("--runs", type=int, default=10, help="Number of benchmark runs")
    parser.add_argument("--seconds", type=int, default=5, help="Recording length in seconds")
    parser.add_argument("--hardware", default="", help="Hardware label for benchmark output")
    parser.add_argument("--verbose", action="store_true", help="Print per-run inputs and outputs")
    parser.add_argument("--rewrite-model", default="", help="Path to a local GGUF rewrite model")
    parser.add_argument("--rewrite-gpu-layers", type=int, default=-1, help="llama.cpp GPU layers")
    parser.add_argument("--rewrite-context-window", type=int, default=2048, help="Rewrite context window")
    parser.add_argument("--rewrite-max-tokens", type=int, default=192, help="Rewrite max output tokens")
    parser.add_argument("--rewrite-temperature", type=float, default=0.2, help="Rewrite temperature")
    parser.add_argument("--rewrite-threads", type=int, default=0, help="Rewrite CPU threads, 0 for default")
    parser.add_argument("--rewrite-warmups", type=int, default=1, help="Untimed rewrite warmup runs")
    parser.add_argument(
        "--rewrite-sample",
        action="append",
        help="Rewrite sample text; can be passed multiple times",
    )
    args = parser.parse_args()

    if args.rewrite:
        benchmark_rewrite(args)
        return

    if args.backend == "server":
        import requests
        try:
            requests.get(f"{args.server}/health", timeout=5)
            print(f"Server: {args.server} (healthy)\n")
        except Exception:
            print(f"Cannot reach server at {args.server}")
            exit(1)

    audio = record_clip(args.seconds)

    if args.backend == "local":
        times = benchmark_local(audio, args.runs, args.model)
    else:
        times = benchmark_server(audio, args.runs, args.server)

    print_results(times, args.runs)


if __name__ == "__main__":
    main()

from __future__ import annotations

import io
import sys
import threading
import wave
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1


@dataclass
class RecorderState:
    recording: bool = False
    audio_chunks: list[np.ndarray] = field(default_factory=list)
    stream: sd.InputStream | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    enabled: bool = True


def start_recording(state: RecorderState, play_sound_fn: Callable[[str], None]) -> None:
    """Start capturing audio from the default microphone."""
    if not state.enabled:
        return

    with state.lock:
        if state.recording:
            return
        state.recording = True
        state.audio_chunks = []

    play_sound_fn("start")
    print("Recording...")

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[warn] Audio status: {status}", file=sys.stderr)
        with state.lock:
            if state.recording:
                state.audio_chunks.append(indata.copy())

    # Always use the current system default input device.
    default_device = sd.default.device[0] or sd.query_devices(kind="input")["index"]
    state.stream = sd.InputStream(
        device=default_device,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=audio_callback,
        blocksize=1024,
    )
    state.stream.start()


def stop_recording(state: RecorderState, play_sound_fn: Callable[[str], None]) -> io.BytesIO | None:
    """Stop recording and return the audio as a WAV bytes buffer."""
    with state.lock:
        if not state.recording:
            return None
        state.recording = False

    play_sound_fn("stop")

    if state.stream:
        state.stream.stop()
        state.stream.close()
        state.stream = None

    with state.lock:
        chunks = state.audio_chunks
        state.audio_chunks = []

    if not chunks:
        print("[warn] No audio captured")
        return None

    audio_data = np.concatenate(chunks, axis=0)
    duration = len(audio_data) / SAMPLE_RATE
    print(f"[ok] Captured {duration:.1f}s of audio")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_data.tobytes())
    buf.seek(0)
    return buf

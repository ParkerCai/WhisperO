# WhisperO 😮

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](pyproject.toml)
[![Backend](https://img.shields.io/badge/Backend-faster--whisper%20%7C%20whisper.cpp-orange.svg)](https://github.com/SYSTRAN/faster-whisper)

WhisperO is a push-to-talk desktop dictation app.
Hold the hotkey, speak, release, and text is pasted at your cursor.

Local mode is the default. No server is required.
It uses OpenAI's Whisper model for speech recognition, running entirely on your machine.
On first run, WhisperO downloads a speech model to `~/.whispero/models/`.
`large-v3` is the default model and is about 3 GB. Smaller models (`medium`, `small`, `base`, `tiny`) are also available for faster inference on lower-end hardware.

## Features

- **Hold-to-record hotkey** - `Win`+`Ctrl` on Windows, `Cmd`+`Ctrl` on Mac
- **Auto-paste at cursor** without losing clipboard contents
- **Local transcription** with faster-whisper (default), no server needed
- **Optional remote server** via whisper.cpp for multi-machine setups
- **Optional local rewrite** with a GGUF text model via llama.cpp
- **Cross-platform** - macOS, Windows, Linux
- **Custom dictionary** for names and project terms
- **Start/stop sound feedback**
- **System tray** with model switching, dictionary editor, and quick controls

![Dictation demo](assets/demo.gif)

![Model switching and tray menu](assets/model-switch.gif)

## Quick Start (Local Default)

### One-Line Install

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/parkercai/whispero/main/setup.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/parkercai/whispero/main/setup.ps1 | iex
```

The setup script installs Python dependencies and WhisperO in an isolated environment. Run `whispero` when it's done.

### Manual Install

1. **Prerequisites (macOS)**
   ```bash
   brew install python@3.12 portaudio
   ```

2. **Install**
   ```bash
   git clone https://github.com/parkercai/whispero.git
   cd whispero
   pip install .
   ```

   WhisperO works on CPU out of the box. For faster GPU inference on NVIDIA GPUs, install:
   - [CUDA Toolkit 12](https://developer.nvidia.com/cuda-downloads) (includes cuBLAS)
   - [cuDNN 9 for CUDA 12](https://developer.nvidia.com/cudnn)

   Without these, WhisperO still works - just slower.

3. **Run**
   ```bash
   whispero
   ```
   or
   ```bash
   python -m whispero
   ```

That is it. WhisperO starts in local mode and uses model `large-v3`.

4. **Run in background without terminal window (optional)**

   **Windows:**
   ```bash
   pythonw -m whispero
   ```

   To start automatically on login, double-click `scripts\install-startup.bat`.
   To remove: `scripts\uninstall-startup.bat`.

   **macOS:**
   ```bash
   nohup python -m whispero &>/dev/null &
   ```

   For login startup, add WhisperO to System Settings > General > Login Items.

> **macOS permissions:** WhisperO needs Accessibility access (for the hotkey) and Microphone access (for recording). Go to System Settings > Privacy & Security to grant these to your terminal app.

## Advanced: Remote Server

If you want to run transcription on another machine, set server backend:

```bash
export WHISPERO_BACKEND=server
export WHISPERO_SERVER="http://localhost:8080"
```

Server setup guide: [docs/SERVER_SETUP.md](docs/SERVER_SETUP.md)

## Configuration

Config priority:

1. Environment variables
2. `~/.whispero/config.json`
3. Built-in defaults

Supported environment variables:

- `WHISPERO_BACKEND=local|server`
- `WHISPERO_MODEL=large-v3|medium|small|base|tiny`
- `WHISPERO_SERVER=http://host:8080`
- `WHISPERO_REWRITE=true|false`
- `WHISPERO_REWRITE_MODEL_PATH=/path/to/model.gguf`
- `WHISPERO_REWRITE_PROMPT=...`
- `WHISPERO_REWRITE_CONTEXT_WINDOW=2048`
- `WHISPERO_REWRITE_MAX_TOKENS=192`
- `WHISPERO_REWRITE_TEMPERATURE=0.2`
- `WHISPERO_REWRITE_THREADS=0`
- `WHISPERO_REWRITE_GPU_LAYERS=-1`

Default values:

```json
{
  "backend": "local",
  "server": "http://localhost:8080",
  "model": "large-v3",
  "hotkey": {
    "windows": ["win", "ctrl"],
    "mac": ["cmd", "ctrl"]
  },
  "sounds": true,
  "rewrite": {
    "enabled": false,
    "model_path": "",
    "prompt": "Rewrite the dictated text to fix transcription mistakes, grammar, punctuation, casing, spacing, and spoken punctuation words such as comma, period, question mark, and new line while preserving the speaker's meaning. Remove clear false starts and self-correction markers while keeping the final intended meaning. Do not remove meaningful words just because they are conversational. Return only the rewritten text. Do not include explanations, labels, markdown, or reasoning.",
    "context_window": 2048,
    "max_tokens": 192,
    "temperature": 0.2,
    "threads": 0,
    "gpu_layers": -1
  }
}
```

Example `~/.whispero/config.json`:

```json
{
  "backend": "local",
  "model": "medium",
  "server": "http://localhost:8080",
  "hotkey": {
    "windows": ["win", "ctrl"],
    "mac": ["cmd", "ctrl"]
  },
  "sounds": true,
  "rewrite": {
    "enabled": false,
    "model_path": "C:\\Users\\you\\.whispero\\rewrite-models\\model.gguf"
  }
}
```

Dictionary file location:

- `~/.whispero/dictionary.txt`

### Optional Rewrite

Rewrite runs after transcription and before paste. It uses a local GGUF text model through `llama-cpp-python`; it does not send text or audio to a remote API. Rewrite is intended for GPU or Apple Metal systems. If local rewrite fails, WhisperO pastes the original transcript.

The rewrite runtime and model are not bundled in source installs. When you turn rewrite on from the tray menu, WhisperO installs `llama-cpp-python` into the current Python environment if it is missing, downloads the default model into `~/.whispero/rewrite-models/`, then enables rewrite. You can also set `WHISPERO_REWRITE_MODEL_PATH` or `rewrite.model_path` to use your own local `.gguf` file.

You can preinstall the optional local rewrite runtime:

```bash
pip install ".[rewrite]"
```

On Windows with NVIDIA GPUs, WhisperO uses the llama-cpp-python CUDA wheel index when it installs the runtime automatically. To install it manually:

```powershell
pip install "llama-cpp-python>=0.3.32" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

On Apple Silicon, WhisperO sets the Metal build flag when it installs the runtime automatically. To install it manually:

```bash
xcode-select --install
CMAKE_ARGS="-DGGML_METAL=on" pip install -U "llama-cpp-python>=0.3.32" --no-cache-dir
```

Enable rewrite from the system tray menu. The first enable downloads and prepares the default model:

- Repo: `Qwen/Qwen3-1.7B-GGUF`
- File: `Qwen3-1.7B-Q8_0.gguf`
- Size: about 1.83 GB
- Observed GPU memory increase on an RTX 5090: about 2.8 GB with full layer offload

You can also point WhisperO at a model manually.

PowerShell:

```powershell
$env:WHISPERO_REWRITE = "true"
$env:WHISPERO_REWRITE_MODEL_PATH = "$HOME\.whispero\rewrite-models\Qwen3-1.7B-Q8_0.gguf"
```

macOS / Linux:

```bash
export WHISPERO_REWRITE=true
export WHISPERO_REWRITE_MODEL_PATH="$HOME/.whispero/rewrite-models/Qwen3-1.7B-Q8_0.gguf"
```

To smoke-test rewrite later without recording audio:

```bash
python -c "from whispero.config import load_config; from whispero.rewrite import rewrite_text; print(rewrite_text('this is a rough dictated sentence without punctuation', load_config()))"
```

You can turn rewrite off from the system tray menu at any time.

## Architecture

WhisperO is a single-process Python desktop app. `app.py` orchestrates a global hotkey listener, a system tray, and per-dictation worker threads. Audio is captured at 16 kHz mono via `sounddevice`. Transcription runs locally (faster-whisper / CTranslate2) by default; optionally it can call out to a `whisper.cpp` HTTP server with automatic fallback to local. The result is pasted into the active window via a save -> copy -> Cmd+V/Ctrl+V -> restore dance so the user's clipboard is preserved.

### 1. Components

```mermaid
flowchart LR
    subgraph UI["UI / Entry"]
      MAIN["__main__.py<br/>freeze_support + dispatch"]
      APP["app.py<br/>hotkey listener - tray UI - orchestrator"]
    end

    subgraph IO["I/O Layer"]
      AUDIO["audio.py<br/>sounddevice 16 kHz mono int16<br/>RecorderState + lock"]
      CLIP["clipboard.py<br/>save -> copy -> Cmd+V/Ctrl+V -> restore"]
      SND["sounds.py<br/>start/stop WAV cues"]
      DICT["dictionary.py<br/>~/.whispero/dictionary.txt -> ASR prompt"]
    end

    subgraph CFG["Config"]
      CONFIG["config.py<br/>~/.whispero/config.json + env overrides"]
    end

    subgraph ASR["Transcription"]
      TRANS["transcribe.py<br/>backend router"]
      LOCAL["faster-whisper<br/>WhisperModel - CTranslate2<br/>~/.whispero/models/"]
      SERVER["whisper.cpp HTTP<br/>POST /inference multipart<br/>3s connect / 30s read"]
    end

    subgraph LLM["Local Rewrite"]
      RW["rewrite.py<br/>local GGUF text model<br/>llama.cpp"]
    end

    MAIN --> APP
    APP -->|reads| CONFIG
    APP -->|register hotkey| AUDIO
    APP -->|on press| SND
    APP -->|load prompt| DICT
    APP -->|spawn worker thread| TRANS
    APP -->|optional rewrite| RW
    APP -->|paste result| CLIP

    TRANS -->|backend=local| LOCAL
    TRANS -->|backend=server| SERVER
    SERVER -.->|all servers fail| LOCAL
```

### 2. Runtime flow - hotkey -> paste

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant L as pynput Listener<br/>(daemon)
    participant A as app.py<br/>(main)
    participant R as Recorder<br/>(sounddevice cb)
    participant T as Worker Thread<br/>(per dictation)
    participant B as transcribe.py
    participant E as ASR Engine<br/>(local - server)
    participant W as rewrite.py<br/>(optional)
    participant C as clipboard.py
    participant OS as Active Window

    U->>L: hold hotkey (e.g. Cmd+Ctrl)
    L->>A: on_press -> trigger_keys subset of keys_held
    A->>R: start_recording(state)
    A->>A: play start.wav (bg thread)
    par async capture
      R-->>R: 16 kHz mono int16 chunks<br/>append under lock
    end
    U->>L: release hotkey
    L->>A: on_release
    A->>R: stop_recording -> WAV BytesIO
    A->>A: play stop.wav (bg thread)
    A->>T: spawn daemon thread
    T->>B: transcribe(wav, prompt=dictionary)
    alt backend = local
      B->>E: WhisperModel.transcribe(initial_prompt=...)
      E-->>B: text
    else backend = server
      B->>E: POST /inference (multipart wav)
      alt server ok
        E-->>B: text
      else timeout / 5xx
        B->>B: try fallback_servers[]
        B->>E: local fallback
        E-->>B: text
      end
    end
    B-->>T: text
    opt rewrite enabled
      T->>W: local llama.cpp inference
      W-->>T: cleaned text
    end
    T->>C: paste_text(text)
    C->>C: save current clipboard
    C->>C: pyperclip.copy(text)
    C->>OS: pynput Cmd+V / Ctrl+V
    C->>C: 50 ms wait -> restore clipboard
    OS-->>U: text appears in active app
```

### 3. Backend routing & fallback

```mermaid
flowchart TD
    START(["transcribe(wav, prompt)"]) --> CHECK{"config.backend"}

    CHECK -->|local| LOCAL_PATH
    CHECK -->|server| SERVER_PATH

    subgraph LOCAL_PATH["Local path"]
      direction TB
      LM{"_model loaded?"}
      LM -->|no| LOAD["WhisperModel(model_size,<br/>device=auto, compute=auto)<br/>cache: ~/.whispero/models/"]
      LM -->|yes| RUN
      LOAD --> RUN["model.transcribe(<br/>  initial_prompt=dictionary,<br/>  beam_size=5)"]
      PYI{"PyInstaller .exe?"}
      LOAD --> PYI
      PYI -->|yes| FORCE_CPU["force device=cpu<br/>(CT2 CUDA segfault workaround)"]
      FORCE_CPU --> RUN
    end

    subgraph SERVER_PATH["Server path (whisper.cpp)"]
      direction TB
      LASTOK{"_last_working_server set?"}
      LASTOK -->|yes| TRY1["POST {server}/inference<br/>multipart: file + prompt<br/>response_format=text<br/>timeout 3s/30s"]
      LASTOK -->|no| TRY1
      TRY1 -->|2xx| OK["text"]
      TRY1 -->|fail| FB{"fallback_servers[]<br/>more entries?"}
      FB -->|yes| TRY1
      FB -->|no| LOCAL_FB["all servers down<br/>-> run local backend"]
      LOCAL_FB --> RUN
    end

    RUN --> OUT["text"]
    OK --> OUT
    OUT --> END(["return to worker thread"])
```

## Benchmarks

Transcription speed for a 5-second audio clip using `large-v3`. Times exclude model loading (warm GPU).

| Hardware | Backend | Median | Avg |
|---|---|---|---|
| RTX 5090 | faster-whisper (local) | 378ms | 390ms |
| NVIDIA GB10 (DGX Spark) | whisper.cpp (server) | 323ms | 375ms |

Rewrite latency for the default local GGUF model. Download, model load, and warmup time are excluded.

| Model | Runtime | Device | Median | Avg |
|---|---|---|---:|---:|
| Qwen3-1.7B-Q8_0 | llama-cpp-python 0.3.32 | RTX 5090 | 52ms | 50ms |

Run your own benchmark:

```bash
python benchmark.py                    # local mode
python benchmark.py --backend server   # server mode
python benchmark.py --rewrite --runs 10
```

For rewrite, pass `--rewrite-model` to test a custom `.gguf` file, `--rewrite-sample` to add your own dictated text, and `--hardware` to label the output table.

Run the benchmark a few times. The first transcription run warms up GPU memory; rewrite only reports warm runs.

Got a result? PRs with new hardware numbers are welcome.

## Building Standalone Apps

WhisperO includes a PyInstaller build script.

```bash
pip install -r requirements.txt
python build/build.py
```

To include local rewrite support in a standalone build, install the rewrite runtime in the build environment before running the build script. The build script bundles `llama-cpp-python` when it is installed; packaged apps do not install Python wheels at runtime.

Output:

- macOS: `dist/WhisperO.app`
- Windows: `dist/WhisperO/WhisperO.exe`

## Uninstall

```bash
pip uninstall whispero
```

To also remove downloaded models and settings:

```bash
# macOS / Linux
rm -rf ~/.whispero

# Windows
rmdir /s %USERPROFILE%\.whispero
```

## Contributing

PRs are welcome.
Keep behavior stable across both backends.
Please test on your target OS before opening a PR.

## Credits

- [OpenAI Whisper](https://github.com/openai/whisper) - the speech recognition model
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) - CTranslate2 inference engine
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) - C/C++ server backend
- [Google Noto Emoji](https://github.com/googlefonts/noto-emoji) - the 😮 icon (Apache 2.0)

## License

MIT. See [LICENSE](LICENSE).

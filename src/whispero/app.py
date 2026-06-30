from __future__ import annotations

import os
import platform
import signal
import sys
import threading
from pathlib import Path

import requests
from pynput import keyboard

from .audio import RecorderState, start_recording, stop_recording
from .clipboard import paste_text
from .config import load_config, save_config_value, save_rewrite_config, save_rewrite_enabled
from .dictionary import load_dictionary, open_dictionary
from .rewrite import ensure_rewrite_model, ensure_rewrite_runtime, rewrite_text, warm_rewrite_model
from .sounds import play_sound
from .transcribe import transcribe

signal.signal(signal.SIGINT, lambda *_: (print("\n[info] Stopping WhisperO..."), os._exit(0)))

config = load_config()
state = RecorderState()


KEY_MAP = {
    "win": keyboard.Key.cmd,
    "cmd": keyboard.Key.cmd,
    "cmd_r": keyboard.Key.cmd_r,
    "ctrl": keyboard.Key.ctrl_l,
    "ctrl_r": keyboard.Key.ctrl_r,
    "shift": keyboard.Key.shift,
    "shift_r": keyboard.Key.shift_r,
    "alt": keyboard.Key.alt,
    "alt_r": keyboard.Key.alt_r,
}


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def _sounds_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _bundle_dir() / "sounds"
    # Check package assets first, then project root
    pkg_sounds = Path(__file__).resolve().parent / "assets" / "sounds"
    if pkg_sounds.exists():
        return pkg_sounds
    return _bundle_dir() / "assets" / "sounds"


def _dictionary_seed_path() -> Path:
    if getattr(sys, "frozen", False):
        return _bundle_dir() / "dictionary.txt"
    pkg_dict = Path(__file__).resolve().parent / "assets" / "dictionary.txt"
    if pkg_dict.exists():
        return pkg_dict
    return _bundle_dir() / "dictionary.txt"


def _play_sound(name: str) -> None:
    play_sound(name=name, sounds_enabled=bool(config.get("sounds", True)), sounds_dir=_sounds_dir())


def get_trigger_keys() -> set:
    """Get trigger keys from config based on platform."""
    is_mac = platform.system() == "Darwin"
    key_names = config["hotkey"].get("mac" if is_mac else "windows", ["cmd", "ctrl"])
    keys = set()
    for name in key_names:
        if name.lower() in KEY_MAP:
            keys.add(KEY_MAP[name.lower()])
        else:
            print(f"[warn] Unknown key: {name}")
    return keys


def on_hotkey_press() -> None:
    start_recording(state, _play_sound)


def on_hotkey_release() -> None:
    audio_buf = stop_recording(state, _play_sound)
    if audio_buf is None:
        return

    def do_transcribe() -> None:
        prompt = load_dictionary(seed_path=_dictionary_seed_path())
        text = transcribe(audio_buf=audio_buf, config=config, prompt=prompt)
        if text:
            text = rewrite_text(text, config)
            print(f'Transcript: "{text}"')
            paste_text(text)
            print("[ok] Pasted.")
        else:
            print("[warn] No transcription returned")

    threading.Thread(target=do_transcribe, daemon=True).start()


def create_tray_icon():
    """Create and run the system tray icon."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("[warn] pystray/Pillow not installed, running without tray icon")
        return None

    def make_icon():
        # Try to load the app icon from bundled or project icons.
        icon_paths = [
            _bundle_dir() / "icons" / "icon_128.png",
            _bundle_dir() / "icons" / "icon.png",
            Path(__file__).resolve().parents[2] / "icons" / "icon_128.png",
            Path(__file__).resolve().parents[2] / "icons" / "icon.png",
        ]
        for p in icon_paths:
            if p.exists():
                return Image.open(p).resize((64, 64), Image.LANCZOS)
        # Fallback: yellow face icon.
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill="#FFD93D", outline="#2D2D2D", width=3)
        draw.ellipse([20, 22, 28, 30], fill="#2D2D2D")  # left eye
        draw.ellipse([36, 22, 44, 30], fill="#2D2D2D")  # right eye
        draw.ellipse([26, 38, 38, 50], fill="#2D2D2D")  # open mouth
        return img

    MODELS = ["large-v3", "medium", "small", "base", "tiny"]

    def on_toggle(icon, item):
        state.enabled = not state.enabled
        status = "Enabled" if state.enabled else "Disabled"
        print(f"[info] Dictation {status}")

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    def on_edit_dict(icon, item):
        open_dictionary()

    rewrite_download_active = False
    rewrite_download_lock = threading.Lock()

    def get_rewrite_config() -> dict:
        rewrite_config = config.get("rewrite", {})
        if not isinstance(rewrite_config, dict):
            rewrite_config = {}
            config["rewrite"] = rewrite_config
        return rewrite_config

    def rewrite_enabled() -> bool:
        return bool(get_rewrite_config().get("enabled"))

    def rewrite_label(item):
        with rewrite_download_lock:
            rewrite_is_preparing = rewrite_download_active
        if rewrite_is_preparing:
            return "Rewrite: Preparing..."
        return "Rewrite: On" if rewrite_enabled() else "Rewrite: Off"

    def on_toggle_rewrite(icon, item):
        nonlocal rewrite_download_active
        rewrite_config = get_rewrite_config()
        with rewrite_download_lock:
            if rewrite_download_active:
                return

        if bool(rewrite_config.get("enabled")):
            rewrite_config["enabled"] = False
            save_rewrite_enabled(False)
            print("[info] Rewrite disabled")
            icon.update_menu()
            return

        with rewrite_download_lock:
            if rewrite_download_active:
                return
            rewrite_download_active = True
        icon.update_menu()

        def enable_rewrite():
            nonlocal rewrite_download_active
            try:
                ensure_rewrite_runtime()
                model_path = ensure_rewrite_model(rewrite_config)
                if not rewrite_config.get("model_path"):
                    rewrite_config["model_path"] = str(model_path)
                warm_rewrite_model(rewrite_config)
                rewrite_config["enabled"] = True
                save_rewrite_config(
                    {
                        "enabled": True,
                        "model_path": rewrite_config["model_path"],
                    }
                )
                print(f"[ok] Rewrite enabled ({Path(rewrite_config['model_path']).name})")
            except Exception as err:
                rewrite_config["enabled"] = False
                save_rewrite_enabled(False)
                print(f"[error] Failed to enable rewrite: {err}")
            finally:
                with rewrite_download_lock:
                    rewrite_download_active = False
                icon.update_menu()

        threading.Thread(target=enable_rewrite, daemon=True).start()

    def make_model_callback(model_name):
        def callback(icon, item):
            if config.get("model") == model_name:
                return
            config["model"] = model_name
            save_config_value("model", model_name)
            print(f"[info] Switching to {model_name}...")
            if config.get("backend", "local") == "local":
                try:
                    from .transcribe import get_model, is_model_cached
                    if not is_model_cached(model_name):
                        print(f"[info] Downloading {model_name}...")
                    get_model(model_name)
                    print(f"[ok] {model_name} ready")
                except Exception as e:
                    print(f"[error] Failed to load {model_name}: {e}")
        return callback

    def is_current_model(model_name):
        return lambda item: config.get("model", "large-v3") == model_name

    if platform.system() == "Darwin":
        hotkey_label = "Hold Ctrl+Cmd to dictate"
    else:
        hotkey_label = "Hold Win+Ctrl to dictate"

    model_menu = pystray.Menu(
        *[pystray.MenuItem(
            m, make_model_callback(m), checked=is_current_model(m), radio=True
        ) for m in MODELS]
    )

    # Build server list from config (deduplicated, stable order)
    _all_servers = list(dict.fromkeys(
        [config.get("server", "http://localhost:8080")] + config.get("fallback_servers", [])
    ))

    def make_server_callback(url):
        def callback(icon, item):
            config["backend"] = "server"
            config["server"] = url
            save_config_value("backend", "server")
            save_config_value("server", url)
            print(f"[info] Server: {url}")
            icon.update_menu()
        return callback

    def is_current_server(url):
        return lambda item: config.get("backend", "local") == "server" and config.get("server") == url

    def make_backend_callback(backend_name):
        def callback(icon, item):
            config["backend"] = backend_name
            save_config_value("backend", backend_name)
            print(f"[info] Backend: {backend_name}")
            icon.update_menu()
        return callback

    def is_current_backend(backend_name):
        return lambda item: config.get("backend", "local") == backend_name

    menu = pystray.Menu(
        pystray.MenuItem(hotkey_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: "Enabled: On" if state.enabled else "Enabled: Off", on_toggle),
        pystray.MenuItem("Select Backend", pystray.Menu(
            pystray.MenuItem(
                "Local", make_backend_callback("local"),
                checked=is_current_backend("local"), radio=True
            ),
            *[pystray.MenuItem(
                f"Server ({s})", make_server_callback(s),
                checked=is_current_server(s), radio=True
            ) for s in _all_servers],
        )),
        pystray.MenuItem(
            "Select Model", model_menu,
            enabled=lambda item: config.get("backend", "local") == "local"
        ),
        pystray.MenuItem(
            rewrite_label,
            on_toggle_rewrite,
        ),
        pystray.MenuItem("Edit Dictionary", on_edit_dict),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("WhisperO", make_icon(), "WhisperO", menu)
    return icon


def main() -> None:
    backend = config.get("backend", "local")

    if backend == "local":
        try:
            from .transcribe import get_model, is_model_cached
            model_name = config.get("model", "large-v3")
            print(f"WhisperO (local, model: {model_name})")
            if not is_model_cached(model_name):
                print("[info] Downloading model (this may take a few minutes)...")
            else:
                print("[info] Loading model...")
            get_model(model_name)
            print("[ok] Model ready")
        except (ImportError, RuntimeError):
            print("[warn] faster-whisper not available, falling back to server mode")
            backend = "server"
            config["backend"] = "server"
    if backend == "server":
        print(f"WhisperO (server: {config['server']})")
        try:
            response = requests.get(f"{config['server']}/health", timeout=5)
            if response.json().get("status") == "ok":
                print("[ok] Server is healthy")
            else:
                print("[warn] Unexpected server response")
        except Exception:
            print("[error] Cannot reach server, will retry on each recording")

    trigger_keys = get_trigger_keys()
    keys_held = set()
    recording_active = False

    is_mac = platform.system() == "Darwin"
    if is_mac:
        key_names = config["hotkey"].get("mac", ["cmd", "ctrl"])
        print(f"Hotkey: hold [{' + '.join(k.title() for k in key_names)}] to record")
    else:
        key_names = config["hotkey"].get("windows", ["win", "ctrl"])
        print(f"Hotkey: hold [{' + '.join(k.title() for k in key_names)}] to record")
    print("Press Ctrl+C to quit\n")

    def on_press(key):
        nonlocal recording_active
        keys_held.add(key)
        if trigger_keys.issubset(keys_held) and not recording_active:
            recording_active = True
            on_hotkey_press()

    def on_release(key):
        nonlocal recording_active
        if key in trigger_keys and recording_active:
            recording_active = False
            on_hotkey_release()
        keys_held.discard(key)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()

    tray = create_tray_icon()
    if tray:
        if platform.system() == "Windows":
            # Windows: run tray in background thread so Ctrl+C works
            tray_thread = threading.Thread(target=tray.run, daemon=True)
            tray_thread.start()
            try:
                tray_thread.join()
            except KeyboardInterrupt:
                tray.stop()
                print("\nBye.")
        else:
            # macOS/Linux: tray must run on main thread (AppKit requirement)
            tray.run()
    else:
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\nBye.")


if __name__ == "__main__":
    main()

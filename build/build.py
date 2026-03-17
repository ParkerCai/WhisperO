#!/usr/bin/env python3
"""Build WhisperO into a standalone app."""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DIST = ROOT / "dist"
PYI_BUILD = ROOT / ".pyinstaller-build"
ICONS_DIR = SCRIPT_DIR / "icons"
SOUNDS_DIR = ROOT / "assets" / "sounds"
APP_NAME = "WhisperO"
ENTRY_SCRIPT = ROOT / ".whispero_entry.py"


def run(cmd, **kwargs):
    """Run a command and exit on failure."""
    print(f"  → {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"  ❌ Command failed with exit code {result.returncode}")
        sys.exit(1)
    return result


def check_deps() -> None:
    """Check required build dependencies."""
    missing = []
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        missing.append("pyinstaller")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")

    if missing:
        print(f"  ❌ Missing build dependencies: {', '.join(missing)}")
        print(f"  Run: pip install {' '.join(missing)}")
        sys.exit(1)
    print("  ✓ Build dependencies OK")


def generate_icons() -> None:
    """Verify app icons exist."""
    ico = ICONS_DIR / "icon.ico"
    png = ICONS_DIR / "icon.png"
    if ico.exists() and png.exists():
        print(f"  ✓ Icons ready ({ico.stat().st_size // 1024}KB .ico)")
        return
    print("  ❌ Missing icons. Place icon.png and icon.ico in build/icons/")
    sys.exit(1)


def create_icns_mac() -> Path | None:
    """Convert PNG to .icns on macOS using iconutil."""
    icns_path = ICONS_DIR / "icon.icns"
    if icns_path.exists():
        print("  ✓ icon.icns already exists")
        return icns_path

    png_source = ICONS_DIR / "icon_1024.png"
    if not png_source.exists():
        print("  ⚠️  No icon_1024.png, skipping .icns generation")
        return None

    from PIL import Image

    iconset = ICONS_DIR / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(exist_ok=True)

    img = Image.open(png_source)
    for sz in [16, 32, 128, 256, 512]:
        resized = img.resize((sz, sz), Image.LANCZOS)
        resized.save(iconset / f"icon_{sz}x{sz}.png")
        resized2x = img.resize((sz * 2, sz * 2), Image.LANCZOS)
        resized2x.save(iconset / f"icon_{sz}x{sz}@2x.png")

    try:
        run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)])
        print("  ✓ icon.icns created")
    except Exception as exc:
        print(f"  ⚠️  iconutil failed: {exc}")
        return None
    finally:
        shutil.rmtree(iconset, ignore_errors=True)

    return icns_path


def patch_info_plist(app_path: Path) -> None:
    """Add permission descriptions to app Info.plist."""
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        print(f"  ⚠️  No Info.plist found at {plist_path}")
        return

    with plist_path.open("rb") as file:
        plist = plistlib.load(file)

    plist["NSMicrophoneUsageDescription"] = (
        "WhisperO needs microphone access to record your speech for transcription."
    )
    plist["NSAccessibilityUsageDescription"] = (
        "WhisperO needs accessibility access to detect hotkeys and paste transcriptions."
    )
    plist["LSUIElement"] = True

    with plist_path.open("wb") as file:
        plistlib.dump(plist, file)

    print("  ✓ Info.plist patched with permission descriptions")



def clean_build() -> None:
    """Remove old build artifacts."""
    for path in [DIST, PYI_BUILD]:
        if path.exists():
            shutil.rmtree(path)
            print(f"  ✓ Cleaned {path}")

    spec = ROOT / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()


def write_entry_script() -> None:
    ENTRY_SCRIPT.write_text(
        "import multiprocessing\nmultiprocessing.freeze_support()\n\nfrom whispero.app import main\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )


def remove_entry_script() -> None:
    if ENTRY_SCRIPT.exists():
        ENTRY_SCRIPT.unlink()


def build_pyinstaller() -> None:
    """Run PyInstaller to create standalone app."""
    system = platform.system()
    clean_build()
    write_entry_script()

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST),
        "--workpath",
        str(PYI_BUILD),
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        f"{SOUNDS_DIR}{os.pathsep}sounds",
    ]

    # Bundle icons for tray icon
    project_icons = ROOT / "icons"
    if project_icons.exists():
        args += ["--add-data", f"{project_icons}{os.pathsep}icons"]

    dict_file = ROOT / "dictionary.txt"
    if dict_file.exists():
        args += ["--add-data", f"{dict_file}{os.pathsep}."]
    else:
        print("  ⚠️  No dictionary.txt found, app will start with empty dictionary")

    if system == "Darwin":
        icns = create_icns_mac()
        args += [
            "--windowed",
            "--osx-bundle-identifier",
            "com.parkercai.whispero",
            "--hidden-import",
            "pynput.keyboard._darwin",
            "--hidden-import",
            "pynput.mouse._darwin",
        ]
        if icns:
            args += ["--icon", str(icns)]
    elif system == "Windows":
        ico = ICONS_DIR / "icon.ico"
        args += [
            "--console",
            "--hidden-import",
            "pynput.keyboard._win32",
            "--hidden-import",
            "pynput.mouse._win32",
        ]
        if ico.exists():
            args += ["--icon", str(ico)]
    else:
        print(f"  ⚠️  Unsupported platform: {system}")
        remove_entry_script()
        sys.exit(1)

    args += [
        "--hidden-import",
        "sounddevice",
        "--hidden-import",
        "_sounddevice_data",
        "--hidden-import",
        "faster_whisper",
        "--hidden-import",
        "ctranslate2",
        "--collect-all",
        "ctranslate2",
        "--collect-all",
        "faster_whisper",
    ]

    args.append(str(ENTRY_SCRIPT))

    print(f"\n  Building for {system}...")
    try:
        run(args, cwd=str(ROOT))
    finally:
        remove_entry_script()

    if system == "Darwin":
        app_path = DIST / f"{APP_NAME}.app"
        if not app_path.exists():
            alt_path = DIST / APP_NAME / f"{APP_NAME}.app"
            if alt_path.exists():
                shutil.move(str(alt_path), str(app_path))
            else:
                print("  ❌ .app bundle not found. Contents of dist/:")
                for item in DIST.iterdir():
                    print(f"     {item.name}")
                sys.exit(1)

        patch_info_plist(app_path)

        entitlements = SCRIPT_DIR / "entitlements.plist"
        if entitlements.exists():
            print("  Re-signing app with microphone entitlements...")
            macos_dir = app_path / "Contents" / "MacOS"
            for binary in macos_dir.iterdir():
                if binary.is_file():
                    run(
                        [
                            "codesign",
                            "--force",
                            "--deep",
                            "--sign",
                            "-",
                            "--entitlements",
                            str(entitlements),
                            str(binary),
                        ]
                    )
            run(
                [
                    "codesign",
                    "--force",
                    "--deep",
                    "--sign",
                    "-",
                    "--entitlements",
                    str(entitlements),
                    str(app_path),
                ]
            )
            print("  ✓ App signed with microphone entitlements")

        print(f"\n{'=' * 55}")
        print(f"  ✅ Built: dist/{APP_NAME}.app")
        print("  📝 Dictionary: ~/.whispero/dictionary.txt")
        print("")
        print("  To run:")
        print("    Right-click → Open (first time only)")
        print("")
        print("  To install:")
        print(f"    Drag '{APP_NAME}.app' to /Applications/")
        print("    Grant Accessibility + Input Monitoring + Mic")
        print("    in System Settings → Privacy & Security")
        print(f"{'=' * 55}")
    else:
        print(f"\n{'=' * 55}")
        print(f"  ✅ Built: dist/{APP_NAME}/{APP_NAME}.exe")
        print("  📝 Dictionary: ~/.whispero/dictionary.txt")
        print("")
        print(f"  To run: dist\\{APP_NAME}\\{APP_NAME}.exe")
        print("  Edit ~/.whispero/dictionary.txt to add custom words.")
        print(f"{'=' * 55}")


def main() -> None:
    print(f"🔨 {APP_NAME} Build Script\n")
    check_deps()
    generate_icons()
    build_pyinstaller()
    print("\n🎉 Done!")


if __name__ == "__main__":
    main()

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
ROOT_ICONS_DIR = ROOT / "icons"
BUILD_ICONS_DIR = SCRIPT_DIR / "icons"
ICONS_DIR_CANDIDATES = (ROOT_ICONS_DIR, BUILD_ICONS_DIR)
SOUNDS_DIR = ROOT / "assets" / "sounds"
APP_NAME = "WhisperO"
MACOS_BUNDLE_ICON_NAME = f"{APP_NAME}.icns"
ENTRY_SCRIPT = ROOT / ".whispero_entry.py"


def resolve_icons_dir(*required_files: str) -> Path:
    """Prefer the project-level icons directory, with build/icons as fallback."""
    for candidate in ICONS_DIR_CANDIDATES:
        if candidate.exists() and all((candidate / name).exists() for name in required_files):
            return candidate
    for candidate in ICONS_DIR_CANDIDATES:
        if candidate.exists():
            return candidate
    return ROOT_ICONS_DIR


ICONS_DIR = resolve_icons_dir("icon.png", "icon.ico")


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
    icons_dir = resolve_icons_dir("icon.ico", "icon.png")
    ico = icons_dir / "icon.ico"
    png = icons_dir / "icon.png"
    if ico.exists() and png.exists():
        print(f"  ✓ Icons ready in {icons_dir} ({ico.stat().st_size // 1024}KB .ico)")
        return
    searched = ", ".join(str(path) for path in ICONS_DIR_CANDIDATES)
    print(f"  ❌ Missing icons. Place icon.png and icon.ico in one of: {searched}")
    sys.exit(1)


def select_mac_icon_source(icons_dir: Path) -> Path | None:
    """Pick the best PNG source for a macOS .icns bundle."""
    preferred_names = ["icon_1024.png", "icon.png"]
    candidates = [icons_dir / name for name in preferred_names]
    extra_pngs = sorted(
        path
        for path in icons_dir.glob("*.png")
        if path.name not in preferred_names
    )
    candidates.extend(extra_pngs)

    from PIL import Image

    best_small_png: Path | None = None
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            with Image.open(candidate) as img:
                width, height = img.size
        except Exception as exc:
            print(f"  ⚠️  Skipping unreadable icon source {candidate.name}: {exc}")
            continue

        if width == height and width >= 1024:
            return candidate
        if best_small_png is None and width == height:
            best_small_png = candidate

    return best_small_png


def create_icns_mac() -> Path | None:
    """Convert PNG to .icns on macOS using iconutil."""
    existing_icns_dir = resolve_icons_dir("icon.icns")
    icns_path = existing_icns_dir / "icon.icns"
    if icns_path.exists():
        print(f"  ✓ Using existing macOS icon: {icns_path}")
        return icns_path

    icons_dir = resolve_icons_dir()
    png_source = select_mac_icon_source(icons_dir)
    icns_path = icons_dir / "icon.icns"
    if not png_source:
        print("  ⚠️  No PNG icon source found, skipping .icns generation")
        return None

    from PIL import Image

    iconset = icons_dir / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(exist_ok=True)

    try:
        with Image.open(png_source) as img:
            source = img.convert("RGBA")
            source_size = img.size

        if source_size[0] < 1024 or source_size[1] < 1024:
            print(
                f"  ⚠️  Using {png_source.name} ({source_size[0]}x{source_size[1]}) and scaling it up for macOS"
            )
        else:
            print(f"  ✓ Using {png_source.name} for macOS icon generation")

        for sz in [16, 32, 128, 256, 512]:
            resized = source.resize((sz, sz), Image.LANCZOS)
            resized.save(iconset / f"icon_{sz}x{sz}.png")
            resized2x = source.resize((sz * 2, sz * 2), Image.LANCZOS)
            resized2x.save(iconset / f"icon_{sz}x{sz}@2x.png")

        iconutil = shutil.which("iconutil")
        if not iconutil:
            print("  ⚠️  iconutil not found, skipping .icns generation")
            return None

        result = subprocess.run(
            [iconutil, "-c", "icns", str(iconset), "-o", str(icns_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            print(f"  ⚠️  iconutil failed: {stderr}")
            return None
        print(f"  ✓ icon.icns created: {icns_path}")
    finally:
        shutil.rmtree(iconset, ignore_errors=True)

    return icns_path


def inject_macos_bundle_icon(
    app_path: Path,
    icon_source: Path | None,
    bundle_icon_name: str = MACOS_BUNDLE_ICON_NAME,
) -> str | None:
    """Copy a stable .icns into the app bundle and return the plist icon value."""
    if not icon_source:
        print("  ⚠️  No macOS .icns source available for post-build bundle injection")
        return None
    if not icon_source.exists():
        print(f"  ⚠️  macOS icon source not found: {icon_source}")
        return None

    resources_dir = app_path / "Contents" / "Resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    bundled_icon_path = resources_dir / bundle_icon_name
    source_resolved = icon_source.resolve()
    destination_resolved = bundled_icon_path.resolve() if bundled_icon_path.exists() else None
    if destination_resolved != source_resolved:
        shutil.copy2(icon_source, bundled_icon_path)

    print(f"  ✓ Bundled macOS icon as {bundled_icon_path.name}")
    return bundled_icon_path.stem


def patch_info_plist(app_path: Path, bundle_icon_source: Path | None = None) -> None:
    """Add permission descriptions to app Info.plist and force a stable bundle icon."""
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        print(f"  ⚠️  No Info.plist found at {plist_path}")
        return

    bundle_icon_value = inject_macos_bundle_icon(app_path, bundle_icon_source)

    with plist_path.open("rb") as file:
        plist = plistlib.load(file)

    plist["NSMicrophoneUsageDescription"] = (
        "WhisperO needs microphone access to record your speech for transcription."
    )
    plist["NSAccessibilityUsageDescription"] = (
        "WhisperO needs accessibility access to detect hotkeys and paste transcriptions."
    )
    plist["LSUIElement"] = True
    if bundle_icon_value:
        plist["CFBundleIconFile"] = bundle_icon_value

    with plist_path.open("wb") as file:
        plistlib.dump(plist, file)

    if bundle_icon_value:
        print(
            f"  ✓ Info.plist patched with permission descriptions and CFBundleIconFile={bundle_icon_value}"
        )
    else:
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
        if not icns:
            print("  ⚠️  Proceeding without a generated macOS build icon; post-build injection may be skipped")
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

        patch_info_plist(app_path, bundle_icon_source=icns)

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

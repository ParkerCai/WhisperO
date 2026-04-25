#!/usr/bin/env bash
# WhisperO setup script for macOS and Linux
# Usage: ./setup.sh
#   or:  curl -fsSL https://raw.githubusercontent.com/parkercai/whispero/main/setup.sh | bash
set -euo pipefail

WHISPERO_HOME="$HOME/.whispero"
VENV_DIR="$WHISPERO_HOME/venv"
MIN_PYTHON="3.10"
REPO_URL="https://github.com/parkercai/whispero.git"
IS_INTERACTIVE=0
if [[ -t 0 ]]; then
  IS_INTERACTIVE=1
fi

# --- Colors (pastel palette, 256-color) ---
RED='\033[38;5;210m'
GREEN='\033[38;5;114m'
YELLOW='\033[38;5;222m'
CYAN='\033[38;5;117m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}▸${NC} $1"; }
ok()    { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}!${NC} $1"; }
fail()  { echo -e "${RED}✗${NC} $1"; exit 1; }
run_without_stdin() {
  "$@" </dev/null
}

echo ""
echo -e "${BOLD}😮 WhisperO Setup${NC}"
echo "─────────────────────────────"
echo ""

# --- Detect OS ---
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="mac" ;;
  Linux)  PLATFORM="linux" ;;
  *)      fail "Unsupported OS: $OS" ;;
esac
ok "Platform: $PLATFORM"

# --- Check Python ---
# On macOS, prefer 3.12 (pyobjc not yet compatible with 3.13+)
python_version() {
  "$1" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null
}

check_python_candidate() {
  local candidate="$1"
  local resolved=""
  local ver=""
  local major=""
  local minor=""

  if [[ "$candidate" == */* ]]; then
    [ -x "$candidate" ] || return 1
    resolved="$candidate"
  else
    resolved=$(command -v "$candidate" 2>/dev/null) || return 1
  fi

  ver=$(python_version "$resolved") || return 1
  major=$(echo "$ver" | cut -d. -f1)
  minor=$(echo "$ver" | cut -d. -f2)

  if [ "$major" -ne 3 ]; then
    warn "Skipping $resolved (Python $ver). WhisperO needs Python 3." >&2
    return 1
  fi

  if [ "$minor" -lt 10 ]; then
    warn "Skipping $resolved (Python $ver). WhisperO needs Python 3.10+." >&2
    return 1
  fi

  if [ "$PLATFORM" = "mac" ] && [ "$minor" -ge 13 ]; then
    warn "Skipping $resolved (Python $ver). WhisperO currently supports Python 3.10-3.12 on macOS." >&2
    return 1
  fi

  printf '%s\n' "$resolved"
  return 0
}

find_python() {
  local candidate

  if [ "$PLATFORM" = "mac" ]; then
    for candidate in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3.11 python3.10; do
      if check_python_candidate "$candidate"; then
        return 0
      fi
    done
  fi

  for candidate in python3 python; do
    if check_python_candidate "$candidate"; then
      return 0
    fi
  done

  return 1
}

PYTHON=""
if PYTHON=$(find_python); then
  ok "Python: $("$PYTHON" --version 2>&1)"
else
  if [ "$PLATFORM" = "mac" ]; then
    info "Compatible Python not found. WhisperO currently needs Python 3.10-3.12 on macOS."

    if ! command -v brew &>/dev/null; then
      info "Homebrew not found. Installing Homebrew first..."
      if ! curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh | /bin/bash; then
        fail "Homebrew installation failed. Install Homebrew from https://brew.sh and rerun setup.sh."
      fi
    fi

    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"

    info "Installing Python 3.12 via Homebrew..."
    if ! run_without_stdin brew install python@3.12; then
      fail "Homebrew could not install python@3.12. Fix Homebrew or install Python 3.12 manually, then rerun setup.sh."
    fi

    PYTHON=$(find_python) || fail "Installed python@3.12 but could not find a compatible Python executable. Try 'eval \"$(brew shellenv)\"' and rerun setup.sh."
    ok "Python: $("$PYTHON" --version 2>&1)"
  else
    fail "Python 3.10+ not found. Install it with your package manager (e.g. sudo apt install python3)."
  fi
fi

# --- Check portaudio (required by sounddevice on Mac) ---
if [ "$PLATFORM" = "mac" ]; then
  if ! brew list portaudio &>/dev/null 2>&1; then
    info "Installing portaudio (needed for microphone access)..."
    if ! command -v brew &>/dev/null; then
      fail "Homebrew is required to install portaudio. Install Homebrew: https://brew.sh"
    fi
    if ! run_without_stdin brew install portaudio; then
      fail "Homebrew could not install portaudio. Fix Homebrew or install portaudio manually, then rerun setup.sh."
    fi
    ok "portaudio installed"
  else
    ok "portaudio found"
  fi
fi

# --- Determine source directory ---
# If run from inside the repo, use that. Otherwise, clone it.
if [ -f "pyproject.toml" ] && grep -q "whispero" pyproject.toml 2>/dev/null; then
  REPO_DIR="$(pwd)"
  ok "Using local repo: $REPO_DIR"
else
  REPO_DIR="$WHISPERO_HOME/src"
  if [ -d "$REPO_DIR/.git" ]; then
    info "Updating existing clone..."
    run_without_stdin git -C "$REPO_DIR" pull --ff-only || warn "Could not update, using existing version"
  else
    info "Cloning WhisperO..."
    run_without_stdin git clone "$REPO_URL" "$REPO_DIR"
  fi
  ok "Source: $REPO_DIR"
fi

# --- Create virtual environment ---
if [ -d "$VENV_DIR" ]; then
  info "Virtual environment already exists at $VENV_DIR"
  recreate=""
  if [ "$IS_INTERACTIVE" -eq 1 ]; then
    read -rp "   Recreate it? Updating: just press Enter (y/N) " recreate
  else
    info "Non-interactive install detected, keeping existing virtual environment and updating it in place."
  fi
  if [[ "$recreate" =~ ^[Yy]$ ]]; then
    rm -rf "$VENV_DIR"
    $PYTHON -m venv "$VENV_DIR"
    ok "Virtual environment recreated"
  else
    ok "Keeping existing virtual environment"
  fi
else
  info "Creating virtual environment..."
  mkdir -p "$WHISPERO_HOME"
  $PYTHON -m venv "$VENV_DIR"
  ok "Virtual environment created at $VENV_DIR"
fi

# --- Install WhisperO ---
info "Installing WhisperO and dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install "$REPO_DIR" --quiet
ok "WhisperO installed"

# --- Create launcher script ---
LAUNCHER="/usr/local/bin/whispero"
info "Creating launcher at $LAUNCHER..."

LAUNCHER_CONTENT="#!/usr/bin/env bash
exec \"$VENV_DIR/bin/whispero\" \"\$@\"
"

if [ -w "/usr/local/bin" ]; then
  echo "$LAUNCHER_CONTENT" > "$LAUNCHER"
  chmod +x "$LAUNCHER"
  ok "Launcher created: $LAUNCHER"
else
  sudo bash -c "echo '$LAUNCHER_CONTENT' > $LAUNCHER && chmod +x $LAUNCHER"
  ok "Launcher created: $LAUNCHER (with sudo)"
fi

# --- macOS accessibility reminder ---
if [ "$PLATFORM" = "mac" ]; then
  echo ""
  echo -e "${YELLOW}⚠  macOS Permissions${NC}"
  echo "   WhisperO needs two permissions to work:"
  echo ""
  echo "   1. ${BOLD}Accessibility${NC} (for keyboard hotkey)"
  echo "      System Settings → Privacy & Security → Accessibility"
  echo "      Add: Terminal (or your terminal app)"
  echo ""
  echo "   2. ${BOLD}Microphone${NC} (for recording)"
  echo "      macOS will prompt on first use — click Allow"
  echo ""
fi

# --- Done ---
echo ""
echo -e "${GREEN}${BOLD}😮 WhisperO is ready!${NC}"
echo ""
echo "   Run it:    whispero"
echo "   Hotkey:    ⌘ + Ctrl (Mac) or Win + Ctrl (Windows)"
echo "   Config:    ~/.whispero/config.json"
echo ""
echo "   On first run, WhisperO downloads the large-v3 model (~3 GB)."
echo "   For a faster start, use a smaller model:"
echo "   WHISPERO_MODEL=base whispero"
echo ""

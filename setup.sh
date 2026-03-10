#!/usr/bin/env bash
# WhisperO setup script for macOS and Linux
# Usage: ./setup.sh
#   or:  curl -fsSL https://raw.githubusercontent.com/parkercai/whispero/main/setup.sh | bash
set -euo pipefail

WHISPERO_HOME="$HOME/.whispero"
VENV_DIR="$WHISPERO_HOME/venv"
MIN_PYTHON="3.10"
REPO_URL="https://github.com/parkercai/whispero.git"

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
find_python() {
  for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
      local ver
      ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || continue
      local major minor
      major=$(echo "$ver" | cut -d. -f1)
      minor=$(echo "$ver" | cut -d. -f2)
      if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON=""
if PYTHON=$(find_python); then
  ok "Python: $($PYTHON --version)"
else
  if [ "$PLATFORM" = "mac" ]; then
    info "Python 3.10+ not found. Installing via Homebrew..."
    if ! command -v brew &>/dev/null; then
      info "Homebrew not found. Installing Homebrew first..."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
    fi
    brew install python@3.12
    PYTHON=$(find_python) || fail "Python install failed. Please install Python 3.10+ manually."
    ok "Python: $($PYTHON --version)"
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
    brew install portaudio
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
    git -C "$REPO_DIR" pull --ff-only || warn "Could not update, using existing version"
  else
    info "Cloning WhisperO..."
    git clone "$REPO_URL" "$REPO_DIR"
  fi
  ok "Source: $REPO_DIR"
fi

# --- Create virtual environment ---
if [ -d "$VENV_DIR" ]; then
  info "Virtual environment already exists at $VENV_DIR"
  read -rp "   Recreate it? (y/N) " recreate
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

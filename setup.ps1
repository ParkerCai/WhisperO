# WhisperO setup script for Windows
# Usage: Right-click → Run with PowerShell
#   or:  powershell -ExecutionPolicy Bypass -File setup.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$WhisperOHome = "$env:USERPROFILE\.whispero"
$VenvDir = "$WhisperOHome\venv"
$MinPython = [version]"3.10"

# --- Helpers ---
function Info($msg)  { Write-Host "  ▸ " -ForegroundColor Cyan -NoNewline; Write-Host $msg }
function Ok($msg)    { Write-Host "  ✓ " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Warn($msg)  { Write-Host "  ! " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Fail($msg)  { Write-Host "  ✗ " -ForegroundColor Red -NoNewline; Write-Host $msg; exit 1 }

Write-Host ""
Write-Host "  😮 WhisperO Setup" -ForegroundColor White
Write-Host "  ─────────────────────────────"
Write-Host ""

# --- Check Python ---
$PythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parsed = [version]$ver
            if ($parsed -ge $MinPython) {
                $PythonCmd = $cmd
                break
            }
        }
    } catch { continue }
}

if (-not $PythonCmd) {
    Warn "Python 3.10+ not found."
    Write-Host ""
    Write-Host "  Install Python from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    Write-Host ""
    Fail "Please install Python 3.10+ and run this script again."
}

$pyVer = & $PythonCmd --version 2>&1
Ok "Python: $pyVer"

# --- Determine source directory ---
$RepoDir = $null
if (Test-Path "pyproject.toml") {
    $content = Get-Content "pyproject.toml" -Raw
    if ($content -match "whispero") {
        $RepoDir = (Get-Location).Path
        Ok "Using local repo: $RepoDir"
    }
}

if (-not $RepoDir) {
    $RepoDir = "$WhisperOHome\src"
    if (Test-Path "$RepoDir\.git") {
        Info "Updating existing clone..."
        git -C $RepoDir pull --ff-only 2>$null
        if (-not $?) { Warn "Could not update, using existing version" }
    } else {
        Info "Cloning WhisperO..."
        git clone "https://github.com/parkercai/whispero.git" $RepoDir
        if (-not $?) { Fail "Git clone failed. Make sure git is installed." }
    }
    Ok "Source: $RepoDir"
}

# --- Create virtual environment ---
if (Test-Path $VenvDir) {
    Info "Virtual environment already exists at $VenvDir"
    $recreate = Read-Host "   Recreate it? (y/N)"
    if ($recreate -match "^[Yy]$") {
        Remove-Item -Recurse -Force $VenvDir
        & $PythonCmd -m venv $VenvDir
        Ok "Virtual environment recreated"
    } else {
        Ok "Keeping existing virtual environment"
    }
} else {
    Info "Creating virtual environment..."
    New-Item -ItemType Directory -Path $WhisperOHome -Force | Out-Null
    & $PythonCmd -m venv $VenvDir
    Ok "Virtual environment created at $VenvDir"
}

# --- Install WhisperO ---
$pip = "$VenvDir\Scripts\pip.exe"
$whisperoExe = "$VenvDir\Scripts\whispero.exe"

Info "Installing WhisperO and dependencies (this may take a few minutes)..."
& $pip install --upgrade pip --quiet
& $pip install $RepoDir --quiet
Ok "WhisperO installed"

# --- Add to PATH ---
$binDir = "$VenvDir\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")

if ($userPath -notlike "*$binDir*") {
    Info "Adding WhisperO to your PATH..."
    [Environment]::SetEnvironmentVariable("PATH", "$binDir;$userPath", "User")
    $env:PATH = "$binDir;$env:PATH"
    Ok "Added to PATH (restart your terminal for this to take effect)"
} else {
    Ok "Already in PATH"
}

# --- CUDA info ---
Write-Host ""
Write-Host "  💡 GPU Acceleration (optional)" -ForegroundColor Yellow
Write-Host "     WhisperO works on CPU out of the box."
Write-Host "     For faster GPU inference with NVIDIA GPUs, install:"
Write-Host "     - CUDA Toolkit 12: https://developer.nvidia.com/cuda-downloads"
Write-Host "     - cuDNN 9: https://developer.nvidia.com/cudnn"
Write-Host ""

# --- Done ---
Write-Host ""
Write-Host "  😮 WhisperO is ready!" -ForegroundColor Green
Write-Host ""
Write-Host "     Run it:    whispero"
Write-Host "     Hotkey:    Win + Ctrl"
Write-Host "     Config:    $WhisperOHome\config.json"
Write-Host ""
Write-Host "     On first run, WhisperO downloads the large-v3 model (~3 GB)."
Write-Host "     For a faster start, use a smaller model:"
Write-Host "     set WHISPERO_MODEL=base && whispero"
Write-Host ""

# Keep window open if double-clicked
if ($Host.Name -eq "ConsoleHost") {
    Write-Host "  Press any key to close..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}

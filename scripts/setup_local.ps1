$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11+ is required. Install Python, reopen PowerShell, then run this script again."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js 24+ and npm are required."
}

python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'"

if (-not (Test-Path -LiteralPath ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env from .env.example"
}

Push-Location Frontend
try {
    npm install
}
finally {
    Pop-Location
}

Write-Host "Setup complete. See README.md for the three local run commands."

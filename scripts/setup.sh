#!/bin/sh
# Local setup for Orbit.

set -e

echo "=== Orbit local setup ==="

python3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'"
echo "Python version OK"

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
. .venv/bin/activate

python -m pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

cd Frontend
npm install
cd ..

echo "Setup complete. See README.md for the three local run commands."

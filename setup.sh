#!/bin/bash

set -e

echo "Samsung WB250F Camera Transfer Setup"
echo "==================================="

# Find Python
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Python is not installed."
    echo "Install it first using Homebrew:"
    echo "brew install python@3.12"
    exit 1
fi

echo "Using:"
$PYTHON --version

# Create virtual environment if missing
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
fi

# Activate it
source .venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

echo
echo "Setup complete."
echo "Starting Samsung Camera Transfer..."
echo

python SamsungCameraApp.py

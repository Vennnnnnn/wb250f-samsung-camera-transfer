#!/bin/bash

set -e

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found."
    echo "Run ./setup.sh first."
    exit 1
fi

source .venv/bin/activate
python SamsungCameraApp.py

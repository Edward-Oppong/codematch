#!/bin/sh
# CodeMatch on Mac or Linux:  sh start.sh   (first run sets things up; later runs just start)
cd "$(dirname "$0")" || exit 1
if [ ! -x venv/bin/python ]; then
  echo "Setting up CodeMatch for the first time. This takes a minute..."
  python3 -m venv venv || { echo "Python 3 isn't installed. Get it from https://www.python.org/downloads/"; exit 1; }
  venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt || {
    echo "Couldn't install what CodeMatch needs. Check your internet connection and try again."; rm -rf venv; exit 1; }
fi
echo "Starting CodeMatch at http://127.0.0.1:5000 (press Ctrl+C to stop)."
CODEMATCH_OPEN=1 exec venv/bin/python run.py

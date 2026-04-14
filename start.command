#!/bin/bash
# Inspace GTM AI — startup script
# Double-click this file in Finder to launch the app.

# Change to the directory this script lives in
cd "$(dirname "$0")"

echo ""
echo "================================================"
echo "  Inspace GTM AI"
echo "================================================"
echo ""

# ── 1. Check Python ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "ERROR: Python 3 is not installed."
  echo "Download it from https://python.org/downloads and re-run this script."
  read -p "Press Enter to close..."
  exit 1
fi

# ── 2. Create venv if it doesn't exist ───────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "First-time setup: creating Python environment..."
  python3 -m venv venv
fi

# ── 3. Activate venv ─────────────────────────────────────────────────────────
source venv/bin/activate

# ── 4. Install / update dependencies ─────────────────────────────────────────
echo "Checking dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "Installing browser engine (first run may take a few minutes)..."
playwright install chromium

# ── 5. Copy .env if it doesn't exist ─────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "Creating default config file (.env)..."
  cp .env.template .env
fi

# ── 6. Check Ollama is installed ──────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  echo ""
  echo "ERROR: Ollama is not installed."
  echo "Download it from https://ollama.com and re-run this script."
  read -p "Press Enter to close..."
  exit 1
fi

# ── 7. Start Ollama if not already running ───────────────────────────────────
if curl -s --connect-timeout 2 http://localhost:11434/api/tags &>/dev/null; then
  echo "Ollama already running."
else
  echo "Starting Ollama..."
  ollama serve &>/dev/null &
  # Wait for the server to be ready
  for i in {1..10}; do
    if curl -s --connect-timeout 1 http://localhost:11434/api/tags &>/dev/null; then
      break
    fi
    sleep 1
  done
fi

# ── 8. Pull the AI model if not already downloaded ───────────────────────────
MODEL="llama3.1:8b"
if ! ollama list 2>/dev/null | grep -q "$MODEL"; then
  echo ""
  echo "Downloading AI model ($MODEL) — this takes 10–20 minutes on first run..."
  ollama pull "$MODEL"
fi

# ── 9. LinkedIn login check + Chrome quit ────────────────────────────────────
echo ""
echo "BEFORE CONTINUING:"
echo "  1. Open Google Chrome and log into LinkedIn (https://www.linkedin.com)"
echo "  2. Once logged in, quit Chrome completely (Cmd+Q — not just close the window)"
echo ""
read -p "Press Enter once Chrome is quit and you are logged into LinkedIn..."

# Wait until Chrome is actually closed
while pgrep -f "Google Chrome" &>/dev/null; do
  echo "Chrome is still running. Please quit it with Cmd+Q, then press Enter."
  read -p ""
done

# ── 10. Open the app in the browser ──────────────────────────────────────────
echo ""
echo "Starting Inspace GTM AI..."
echo "Opening http://localhost:8000 in your browser..."
echo ""
echo "To stop the app, press Ctrl+C in this window."
echo ""

sleep 1
open "http://localhost:8000" &

# ── 11. Start the server (foreground — keeps Terminal open) ──────────────────
uvicorn main:app --host 127.0.0.1 --port 8000

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo ""
echo "App stopped."

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
echo "  Python ........ OK"

# ── 2. Check Chrome ──────────────────────────────────────────────────────────
if [ ! -d "/Applications/Google Chrome.app" ]; then
  echo ""
  echo "ERROR: Google Chrome is not installed."
  echo "Download it from https://google.com/chrome and re-run this script."
  read -p "Press Enter to close..."
  exit 1
fi
echo "  Chrome ........ OK"

# ── 3. Check Ollama ──────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  echo ""
  echo "ERROR: Ollama is not installed (or hasn't been opened yet)."
  echo ""
  echo "  1. Download it from https://ollama.com"
  echo "  2. After installing, open the Ollama app once"
  echo "     (a llama icon will appear in your menu bar)"
  echo "  3. Re-run this script"
  echo ""
  read -p "Press Enter to close..."
  exit 1
fi
echo "  Ollama ........ OK"
echo ""

# ── 4. Create venv if it doesn't exist ───────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "First-time setup: creating Python environment..."
  python3 -m venv venv
fi

# ── 5. Activate venv ─────────────────────────────────────────────────────────
source venv/bin/activate

# ── 6. Install / update dependencies ─────────────────────────────────────────
echo "Installing dependencies (first run may take a few minutes)..."
pip install --upgrade pip 2>&1 | tail -1
pip install -r requirements.txt 2>&1 | tail -1
echo "Installing browser engine..."
playwright install chromium

# ── 7. Copy .env if it doesn't exist ─────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "Creating default config file (.env)..."
  cp .env.template .env
fi

# ── 8. Start Ollama if not already running ───────────────────────────────────
if curl -s --connect-timeout 2 http://localhost:11434/api/tags &>/dev/null; then
  echo "Ollama already running."
else
  echo "Starting Ollama..."
  ollama serve &>/dev/null &
  # Wait for the server to be ready
  for i in {1..15}; do
    if curl -s --connect-timeout 1 http://localhost:11434/api/tags &>/dev/null; then
      break
    fi
    sleep 1
  done
  if ! curl -s --connect-timeout 1 http://localhost:11434/api/tags &>/dev/null; then
    echo ""
    echo "ERROR: Ollama failed to start."
    echo "Try opening the Ollama app from your Applications folder, then re-run this script."
    read -p "Press Enter to close..."
    exit 1
  fi
fi

# ── 9. Pull the AI model if not already downloaded ───────────────────────────
MODEL="llama3.1:8b"
if ! ollama list 2>/dev/null | grep -q "$MODEL"; then
  echo ""
  echo "Downloading AI model ($MODEL) — this takes 10–20 minutes on first run..."
  echo "Please be patient and do not close this window."
  echo ""
  ollama pull "$MODEL"
fi

# ── 10. LinkedIn login check + Chrome quit ───────────────────────────────────
echo ""
echo "================================================"
echo "  BEFORE CONTINUING:"
echo "  1. Open Google Chrome"
echo "  2. Go to https://www.linkedin.com and log in"
echo "  3. Quit Chrome completely (Cmd+Q)"
echo "================================================"
echo ""
read -p "Press Enter once Chrome is quit and you are logged into LinkedIn..."

# Wait until Chrome is actually closed
while pgrep -f "Google Chrome" &>/dev/null; do
  echo "Chrome is still running. Please quit it with Cmd+Q, then press Enter."
  read -p ""
done

# ── 11. Start the server and open browser ────────────────────────────────────
echo ""
echo "Starting Inspace GTM AI..."
echo ""
echo "To stop the app, press Ctrl+C in this window."
echo ""

# Open browser after a short delay so the server is ready
(sleep 2 && open "http://localhost:8000") &

uvicorn main:app --host 127.0.0.1 --port 8000

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo ""
echo "App stopped."

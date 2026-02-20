# LinkedIn Automator

Sends personalized LinkedIn connection requests via Sales Navigator with AI-generated notes.
Runs locally on **macOS** or Ubuntu. Chrome profile is auto-detected.

---

## macOS Setup

### 1. Install dependencies

```bash
cd ~/linkedin-automator
pip3 install -r requirements.txt
playwright install chromium
```

### 2. Set up Ollama (local AI - recommended)

```bash
# Install Ollama
brew install ollama

# Pull the model (one-time, ~5GB download)
ollama pull llama3.1:8b

# Start Ollama (keep this running in a separate terminal tab)
ollama serve
```

> **No Homebrew?** Install from https://brew.sh or download Ollama directly from https://ollama.com

### 3. Configure

```bash
cp .env.template .env
# Default settings work out of the box on macOS - no edits needed unless using Gemini
```

### 4. Make sure Chrome is installed and you're logged into LinkedIn

The app uses your existing Chrome session. You must be logged into LinkedIn in Chrome before running.

### 5. Run

```bash
# In one terminal: keep ollama serve running
# In another terminal:
cd ~/linkedin-automator
uvicorn main:app --host 127.0.0.1 --port 8000
```

Then open **http://localhost:8000** in your browser.

---

## Ubuntu Setup

### 1. Install dependencies

```bash
cd ~/linkedin-automator
pip install -r requirements.txt
playwright install chromium
```

### 2. Set up Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b
ollama serve   # keep running in a separate terminal
```

### 3. Configure & run

```bash
cp .env.template .env
uvicorn main:app --host 127.0.0.1 --port 8000
```

---

## Note Template Variables

| Variable | Description |
|---|---|
| `{{first_name}}` | Prospect's first name |
| `{{company}}` | Their company name |
| `{{role}}` | Their job title |
| `{{ai_hook}}` | AI-generated personalized sentence (1 sentence) |

**Example template:**
```
Hi {{first_name}}, {{ai_hook}} Would love to connect and swap ideas. — Your Name
```

> LinkedIn limits connection notes to **300 characters**. The UI will warn you if you go over.

---

## Configuration (.env)

| Key | Default | Description |
|---|---|---|
| `AI_PROVIDER` | `ollama` | `ollama` or `gemini` |
| `OLLAMA_MODEL` | `llama3.1:8b` | Any installed Ollama model |
| `GEMINI_API_KEY` | — | Required only if using Gemini |
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | Gemini model name |
| `DAILY_CAP` | `20` | Max requests per day |
| `TOTAL_HOURS` | `10` | Spread requests over N hours |
| `FUZZY_MATCH_THRESHOLD` | `80` | Company match strictness (0–100) |
| `CHROME_PROFILE_PATH` | auto | Leave blank — auto-detected |

---

## Auto-detected Chrome paths

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Google/Chrome` |
| Ubuntu | `~/.config/google-chrome` |

If auto-detection fails, set `CHROME_PROFILE_PATH` manually in `.env`.

---

## Switching to Gemini

```bash
# In .env:
AI_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
```

---

## Tips

- Click **Test AI** in the UI before your first run to confirm Ollama is working
- The first connection request shows a **note preview** with a 5-second window to stop if the AI output looks off
- Use **Pause** if you need to step away mid-session — it resumes where it left off
- If LinkedIn shows a CAPTCHA, the tool stops automatically and alerts you

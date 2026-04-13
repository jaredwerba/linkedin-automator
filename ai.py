import os
import re
from dotenv import load_dotenv

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

# Cache scored titles within a run — key includes profile so different profiles
# don't share scores (a "VP Engineering" scores differently for cloud vs VC).
_title_score_cache: dict[tuple, int] = {}

# ── Outreach Profiles ────────────────────────────────────────────────────────

PROFILE_NAMES = {
    1: "GENERAL OUTREACH",
    2: "SENIOR FOCUS",
    3: "DECISION MAKERS",
}

# Seniority-based scoring prompt — works for any job title search
_SCORE_PROMPT = """Rate this job title by seniority and decision-making authority.

Job title: "{role}"

Scoring guide:
9-10 = C-suite (CEO, CTO, COO, CFO, CPO), President, Founder, Owner, Managing Partner, General Partner, VP
7-8 = Director, Head of, Senior Director, Managing Director
5-6 = Manager, Senior Manager, Principal, Partner, Lead
3-4 = Associate, Analyst, Specialist, Coordinator, Consultant
1-2 = Entry-level, Junior, Assistant, Intern
0 = Student, unemployed, or clearly irrelevant

Reply with a single integer from 0 to 10. Nothing else."""

_SCORE_PROMPTS = {1: _SCORE_PROMPT, 2: _SCORE_PROMPT, 3: _SCORE_PROMPT}

# Phrases that signal an AI-written message — any output containing these is retried.
_BAD_PHRASES = [
    "i've seen", "i noticed", "i came across", "i've managed",
    "i have seen", "i have noticed", "i have come across",
    "our solutions", "your team's growth", "how our ", "explore how",
    "support your", "i'd love to explore", "i would love to explore",
    "i've been following", "i have been following",
]

# Safe fallback hook used when all retries fail — generic, never AI-sounding.
_NOTE_FALLBACK = "always looking to expand my professional network and connect with interesting people."

_NOTE_FALLBACKS = {1: _NOTE_FALLBACK, 2: _NOTE_FALLBACK, 3: _NOTE_FALLBACK}

# Few-shot note prompt — generic networking tone, works for any title
_NOTE_PROMPT = """Write ONE short opening sentence for a LinkedIn connection note.

Rules:
- About their role or field only — never make any claim about their specific company
- Do NOT start with "I've seen", "I noticed", "I came across", or "I've managed"
- No sales language — no "solutions", "growth initiatives", "support your team"
- Casual and direct, like a real person wrote it
- Under 18 words

Examples:
Role: Operations Manager → Always good to connect with people running the operational side of things.
Role: Director of Sales → Sales leaders with real pipeline experience are exactly who I like to know.
Role: Workspace Manager → Workplace and facilities folks have such an underrated view of how orgs actually work.
Role: VP of Finance → Finance leaders who've scaled orgs are always interesting to learn from.
Role: Product Manager → Love connecting with PMs who are deep in the weeds on what actually ships.
Role: Founder → Always happy to connect with founders — the perspective is unlike anything else.

Now write one opener for this person:
Role: {role}

Output only the sentence. Nothing else."""

_NOTE_PROMPTS = {1: _NOTE_PROMPT, 2: _NOTE_PROMPT, 3: _NOTE_PROMPT}


async def score_title_ai(role: str, profile: int = 1) -> int:
    """
    Use the AI to score a job title for relevance.
    Profile determines scoring criteria (cloud infra vs VC vs etc.).
    Returns an integer 0–10.

    Falls back to 0 (caller should use keyword scorer as fallback) if AI
    is unavailable or returns an unparseable response.
    """
    if not role or not role.strip():
        return 0

    cache_key = (role.strip().lower(), profile)
    if cache_key in _title_score_cache:
        return _title_score_cache[cache_key]

    score_template = _SCORE_PROMPTS.get(profile, _SCORE_PROMPTS[1])
    prompt = score_template.replace('"{role}"', f'"{role}"')

    try:
        if AI_PROVIDER == "gemini":
            raw = await _generate_gemini(prompt, max_tokens=5, temperature=0.1)
        else:
            raw = await _generate_ollama(prompt, max_tokens=5, temperature=0.1)

        # Extract first integer found in response
        match = re.search(r'\b(\d{1,2})\b', raw)
        if match:
            score = min(10, max(0, int(match.group(1))))
            _title_score_cache[cache_key] = score
            return score
    except Exception:
        pass  # Silently fall back — keyword scorer will be used

    _title_score_cache[cache_key] = 0
    return 0


def clear_title_score_cache():
    """Clear the cache between runs."""
    _title_score_cache.clear()


MAX_NOTE_CHARS = 280  # LinkedIn hard limit is 300 — stay safely under


def _build_hook_prompt(role: str, profile: int = 1) -> str:
    """
    Build a few-shot prompt asking only for the hook sentence.
    Uses concrete examples to drive the model toward natural, human-sounding output.
    Role only — company name is intentionally excluded to prevent hallucination.
    """
    template = _NOTE_PROMPTS.get(profile, _NOTE_PROMPTS[1])
    return template.replace("{role}", role.strip() if role else "professional")


def _is_clean(hook: str) -> bool:
    """Return True if the hook contains none of the AI-sounding banned phrases."""
    lower = hook.lower()
    return not any(p in lower for p in _BAD_PHRASES)


async def generate_connection_note(first_name: str, company: str, role: str, profile: int = 1) -> str:
    """
    Generate a short, personalised LinkedIn connection request note.
    Final format: "Hi {first_name}, {ai_hook} Would love to connect."
    Retries up to 3 times if the hook contains banned phrases.
    Falls back to a safe static hook if all retries fail or AI is unavailable.
    Guaranteed to be under MAX_NOTE_CHARS.
    """
    fallback_hook = _NOTE_FALLBACKS.get(profile, _NOTE_FALLBACKS[1])
    fallback_note = f"Hi {first_name}, {fallback_hook} Would love to connect."

    try:
        prompt = _build_hook_prompt(role, profile)
        ai_hook = None

        for _ in range(3):
            if AI_PROVIDER == "gemini":
                raw = await _generate_gemini(prompt, max_tokens=50, temperature=0.4)
            else:
                raw = await _generate_ollama(prompt, max_tokens=50, temperature=0.4)

            # Strip surrounding quotes / whitespace the model might add
            raw = raw.strip().strip('"\'')

            # Keep only the first sentence
            if ". " in raw:
                raw = raw.split(". ")[0] + "."

            # Accept on first clean, long-enough result
            if _is_clean(raw) and len(raw) > 10:
                ai_hook = raw
                break

        if not ai_hook:
            return fallback_note

        note = f"Hi {first_name}, {ai_hook} Would love to connect."

        if len(note) > MAX_NOTE_CHARS:
            note = note[:MAX_NOTE_CHARS].rsplit(" ", 1)[0]

        return note

    except Exception:
        return fallback_note


async def _generate_ollama(prompt: str, max_tokens: int = 100, temperature: float = 0.7) -> str:
    """Generate text using local Ollama."""
    try:
        import ollama as ollama_client
        response = ollama_client.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        )
        return response["response"].strip()
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}. Is Ollama running? Try: ollama serve")


async def _generate_gemini(prompt: str, max_tokens: int = 100, temperature: float = 0.7) -> str:
    """Generate text using Google Gemini API."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        )
        return response.text.strip()
    except Exception as e:
        raise RuntimeError(f"Gemini error: {e}. Check your GEMINI_API_KEY in .env")


async def test_ai_connection() -> dict:
    """Test that the AI provider is reachable."""
    try:
        result = await generate_connection_note(
            first_name="Alex",
            company="Acme Corp",
            role="VP of Engineering",
        )
        return {"success": True, "provider": AI_PROVIDER, "sample": result}
    except Exception as e:
        return {"success": False, "provider": AI_PROVIDER, "error": str(e)}

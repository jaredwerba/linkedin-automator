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
    1: "CLOUD INFRA · GENERAL",
    2: "CLOUD INFRA · OCI SAVINGS",
    3: "VENTURE CAPITAL",
}

# Per-profile scoring prompts
_SCORE_PROMPTS = {
    1: """Rate this job title for how likely this person makes decisions about cloud infrastructure, DevOps, or platform engineering at their company.

Job title: "{role}"

Scoring guide:
10 = Clear decision maker (CTO, VP Engineering, VP Infrastructure, Head of Cloud)
7-9 = Strong influencer (Director of Engineering, Director of Platform, Engineering Manager, Cloud Architect, Principal Engineer)
4-6 = Relevant practitioner (DevOps Engineer, SRE, Platform Engineer, Staff Engineer, Solutions Architect)
1-3 = Tangential (Software Engineer, Product Manager, Designer, Sales, Marketing)
0 = Not relevant (HR, Finance, Legal, Admin, Student, Intern)

Reply with a single integer from 0 to 10. Nothing else.""",

    2: """Rate this job title for how likely this person makes decisions about cloud infrastructure, DevOps, or platform engineering at their company.

Job title: "{role}"

Scoring guide:
10 = Clear decision maker (CTO, VP Engineering, VP Infrastructure, Head of Cloud)
7-9 = Strong influencer (Director of Engineering, Director of Platform, Engineering Manager, Cloud Architect, Principal Engineer)
4-6 = Relevant practitioner (DevOps Engineer, SRE, Platform Engineer, Staff Engineer, Solutions Architect)
1-3 = Tangential (Software Engineer, Product Manager, Designer, Sales, Marketing)
0 = Not relevant (HR, Finance, Legal, Admin, Student, Intern)

Reply with a single integer from 0 to 10. Nothing else.""",

    3: """Rate this job title for how likely this person is a venture capital investor, angel investor, or startup ecosystem participant who could provide funding or feedback to an early-stage SaaS startup.

Job title: "{role}"

Scoring guide:
10 = GP, Managing Partner, General Partner, or Partner at a VC firm
7-9 = Principal, Associate, Venture Partner, Angel Investor, Entrepreneur in Residence
4-6 = Portfolio operations, Investor Relations, accelerator/incubator staff, Startup advisor
1-3 = Corporate Innovation, M&A, Growth Equity, Private Equity — tangential
0 = Not relevant (Software Engineer, HR, Finance, Legal, Admin, Student, Intern)

Reply with a single integer from 0 to 10. Nothing else.""",
}

# Per-profile system context injected into the note-generation prompt
_NOTE_PERSONAS = {
    1: "You are helping a cloud infrastructure sales professional write a LinkedIn connection request note. The goal is a natural, role-specific opening line.",
    2: "You are helping a cloud infrastructure sales professional specializing in Oracle Cloud Infrastructure (OCI) cost optimization write a LinkedIn connection request note. The ai_hook should angle toward infrastructure economics, cloud cost reduction, or OCI-specific value relevant to the prospect's role.",
    3: "You are helping a bootstrapped, profitable AI-native SaaS founder write a LinkedIn connection request note to a venture capital investor. The founder is beginning the process of raising their first institutional round and wants to network, share early traction, and get VC perspective. The ai_hook should be genuine, founder-to-investor in tone — not a pitch, just an authentic reason to connect.",
}


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


def _build_prompt(template: str, first_name: str, company: str, role: str, profile: int = 1) -> str:
    """Build the prompt for the AI to fill in the {{ai_hook}} variable."""
    persona = _NOTE_PERSONAS.get(profile, _NOTE_PERSONAS[1])
    return f"""{persona}

The note template is:
{template}

Fill in ONLY the {{{{ai_hook}}}} field. The other fields will be filled separately.

Prospect details:
- First name: {first_name}
- Company: {company}
- Role: {role}

Rules:
- Write 1 sentence only for the ai_hook
- Be specific to their role and company
- Sound natural and human, not salesy
- Do not send any message with brackets or curly braces Check for these at the end of message
- Do not mention you are an AI
- Do not include greetings or sign-offs
- Return ONLY the ai_hook sentence, nothing else
"""


def _fill_static_fields(template: str, first_name: str, company: str, role: str, ai_hook: str) -> str:
    """Replace all template variables with their values."""
    note = template
    note = note.replace("{{first_name}}", first_name)
    note = note.replace("{{company}}", company)
    note = note.replace("{{role}}", role)
    note = note.replace("{{ai_hook}}", ai_hook.strip())
    return note


async def generate_note(template: str, first_name: str, company: str, role: str, profile: int = 1) -> str:
    """Generate a personalized connection note using the configured AI provider."""
    prompt = _build_prompt(template, first_name, company, role, profile)

    if AI_PROVIDER == "gemini":
        ai_hook = await _generate_gemini(prompt)
    else:
        ai_hook = await _generate_ollama(prompt)

    return _fill_static_fields(template, first_name, company, role, ai_hook)


# Fixed template used for all connection request notes (Option A)
_NOTE_TEMPLATE = "Hi {{first_name}}, {{ai_hook}} Would love to connect."

MAX_NOTE_CHARS = 280  # LinkedIn hard limit is 300 — stay safely under


async def generate_connection_note(first_name: str, company: str, role: str, profile: int = 1) -> str:
    """
    Generate a short, personalised LinkedIn connection request note.
    Uses the fixed template: "Hi {first_name}, {ai_hook} Would love to connect."
    Profile controls the note persona/angle (cloud infra general, OCI savings, VC).
    Guaranteed to be under MAX_NOTE_CHARS. Falls back to a plain note on error.
    """
    try:
        note = await generate_note(
            template=_NOTE_TEMPLATE,
            first_name=first_name,
            company=company,
            role=role,
            profile=profile,
        )
        # Hard trim — never exceed LinkedIn's 300-char limit
        if len(note) > MAX_NOTE_CHARS:
            note = note[:MAX_NOTE_CHARS].rsplit(" ", 1)[0]
        return note
    except Exception:
        # Graceful fallback — plain note with no AI hook
        return f"Hi {first_name}, I came across your profile and would love to connect."


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
        result = await generate_note(
            template="Hi {{first_name}}, {{ai_hook}} Would love to connect.",
            first_name="Alex",
            company="Acme Corp",
            role="VP of Sales"
        )
        return {"success": True, "provider": AI_PROVIDER, "sample": result}
    except Exception as e:
        return {"success": False, "provider": AI_PROVIDER, "error": str(e)}

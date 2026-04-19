"""
app/ai/agent_service.py
────────────────────────
Async wrapper around the Ollama-based prescription agent logic.

Exposes two functions the backend services use:
  - explain_medicines(medicines)  → explanation string
  - chat_reply(user_message, history, medicines)  → reply string

All Ollama calls are made in a thread-pool executor so they don't block
the async event loop.
"""

import asyncio
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

from loguru import logger

warnings.filterwarnings("ignore")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_MODEL = "qwen2.5:3b"

# Add agent folder to path so tools/synonyms can be imported
# Assumes agent files are copied into app/ai/agent/
_AGENT_DIR = Path(__file__).parent / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

SYSTEM_PROMPT = """You are a friendly assistant helping someone understand their prescription medicines.

Your style:
- Talk like a helpful friend, not a doctor
- Use simple everyday words — no medical jargon
- Keep things short and easy to read
- Don't scare the user — mention warnings gently, not dramatically
- Never suggest extra medicines or diagnose anything
- If something needs a doctor, say so briefly and move on

You help the user understand what their medicines are for and how to take them. That's it."""

FREQ_LABELS = {
    "1-0-0": "once in the morning",
    "0-1-0": "once in the afternoon",
    "0-0-1": "once at night",
    "1-1-0": "morning and afternoon",
    "1-0-1": "morning and night",
    "0-1-1": "afternoon and night",
    "1-1-1": "three times a day",
}


# ── Ollama availability check ─────────────────────────────────────────────────

def _check_ollama() -> bool:
    try:
        import ollama
        models     = ollama.list()
        available  = [m.model for m in models.models]
        base_avail = [m.split(":")[0] for m in available]
        base_req   = OLLAMA_MODEL.split(":")[0]
        return base_req in base_avail or OLLAMA_MODEL in available
    except Exception:
        return False


# ── RAG context builder ───────────────────────────────────────────────────────

def _build_rag_context(medicines: list[dict]) -> str:
    """Build the RAG context string from local drug_db + FAISS."""
    try:
        import agent.tools as tools # from app/ai/agent/tools.py
        sections = []
        for med in medicines:
            sections.append(tools.format_drug_summary(med))
        interactions = tools.check_interactions([m["name"] for m in medicines])
        return "\n".join(sections), interactions
    except Exception as exc:
        logger.warning(f"RAG context build failed: {exc}")
        return "", []


# ── Blocking Ollama calls (run in executor) ───────────────────────────────────

def _ollama_call(messages: list[dict]) -> str:
    import ollama
    try:
        resp = ollama.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            options={"temperature": 0.3, "num_predict": 400},
        )
        return resp.message.content.strip()
    except Exception as exc:
        logger.error(f"Ollama call failed: {exc}")
        return "Sorry, I couldn't generate a response right now."


def _build_explanation_messages(medicines: list[dict]) -> list[dict]:
    """Build the LLM message list for initial medicine explanation."""
    rag_context, interactions = _build_rag_context(medicines)

    freq_list = "\n".join(
        f"  - {m['name']} {m.get('dosage', '')} — "
        f"{FREQ_LABELS.get(m.get('frequency', ''), m.get('frequency', ''))}"
        for m in medicines
    )

    interaction_note = (
        "Heads up — there may be interactions between some of these medicines. "
        "Please double check with your doctor.\n  " + "\n  ".join(interactions)
        if interactions else ""
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"The patient has these medicines:\n{freq_list}\n\n"
                f"Reference info:\n{rag_context}\n\n"
                f"{interaction_note}\n\n"
                f"Explain each medicine in plain language — what it's for, how to take it, "
                f"one key thing to watch out for, and any food tips. Keep it friendly and brief."
            ),
        },
    ]


# ── Public async API ──────────────────────────────────────────────────────────

async def explain_medicines(medicines: list[dict]) -> tuple[str, list[str]]:
    """
    Generate a friendly explanation for a list of medicines.
    Returns (explanation_text, interaction_warnings_list).
    """
    if not medicines:
        return "No medicines found to explain.", []

    _, interactions = _build_rag_context(medicines)
    messages = _build_explanation_messages(medicines)

    loop = asyncio.get_event_loop()
    explanation = await loop.run_in_executor(None, _ollama_call, messages)
    return explanation, interactions


async def chat_reply(
    user_message: str,
    history: list[dict],
    medicines: Optional[list[dict]] = None,
) -> str:
    """
    Generate a reply to a user chat message.

    history: list of {"role": "user"|"assistant", "content": str}
             This is the FULL history from SQLite, already ordered oldest→newest.
    medicines: optional list of the user's current medicines for context.
    """
    # Build system + optional medicine context
    system_content = SYSTEM_PROMPT
    if medicines:
        med_names = ", ".join(m.get("name", "") for m in medicines)
        system_content += f"\n\nThe user's current medicines are: {med_names}."

    messages = [{"role": "system", "content": system_content}]

    # Inject history (last 20 turns max to stay within context window)
    for turn in history[-20:]:
        messages.append({
            "role": turn["role"],
            "content": turn["content"],
        })

    # Append current user message
    messages.append({"role": "user", "content": user_message})

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _ollama_call, messages)


async def search_pharmeasy(medicines: list[dict]) -> list[dict]:
    """
    Run parallel PharmEasy scraper for a list of medicines.
    Returns list of results with top 3 links each.
    """
    try:
        import agent.pharmeasy_scraper as pharmeasy_scraper  # from app/ai/agent/pharmeasy_scraper.py
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            pharmeasy_scraper.search_all_parallel,
            medicines,
            3,
        )
        return results
    except Exception as exc:
        logger.error(f"PharmEasy search failed: {exc}")
        return [{"medicine": m["name"], "links": [], "error": str(exc)} for m in medicines]
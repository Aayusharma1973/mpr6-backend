"""
app/ai/agent_service.py
────────────────────────
Async wrapper around the Ollama-based prescription agent logic.

Exposes:
  - explain_medicines(medicines)                        → (explanation_str, interactions_list)
  - chat_reply(user_message, history, medicines)        → ChatReplyResult

Tool-calling loop:
  Every ollama.chat() call passes tools=[PHARMEASY_TOOL].
  If Ollama returns tool_calls:
    1. Execute the tool (pharmeasy_scraper.search_all_parallel)
    2. Append the tool result to messages as role="tool"
    3. Call ollama.chat() again so the LLM can form a final reply
  Loops until no more tool_calls (max 3 rounds, safety cap).

Return shape from chat_reply():
  ChatReplyResult(
      content="Here are your medicines on PharmEasy!",   # plain text, no URLs
      pharmeasy_results=[                                 # None if tool wasn't called
          {
              "medicine": "Metformin",
              "results": [
                  {"title": "Glycomet Sr 500mg ...", "url": "https://pharmeasy.in/..."},
                  ...
              ]
          },
          ...
      ]
  )
"""

import asyncio
import json
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

warnings.filterwarnings("ignore")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_MODEL    = "qwen2.5:3b"
MAX_TOOL_ROUNDS = 3   # safety cap — prevents infinite loops

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Add agent folder to path so tools/synonyms/pharmeasy_scraper can be imported
_AGENT_DIR = Path(__file__).parent / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))


# ── Structured return type ────────────────────────────────────────────────────

@dataclass
class ChatReplyResult:
    """
    Structured return from chat_reply().

    content           — friendly text the assistant says after any tool calls
                        (no URLs, no links). Saved to SQLite as the bot message.
    pre_tool_content  — the LLM's first response text BEFORE it made a tool call
                        (e.g. answering questions while also deciding to search).
                        None when no tool was called (content already has everything).
    pharmeasy_results — populated only when search_pharmeasy was called.
                        None otherwise so the frontend knows not to render a
                        medicine card section.
    """
    content: str
    pre_tool_content: Optional[str] = field(default=None)
    pharmeasy_results: Optional[list[dict]] = field(default=None)


# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are RxGuardian, a friendly assistant helping someone understand their prescription medicines and manage them easily.
 
Your style:
- Talk like a helpful friend, not a doctor
- Use simple everyday words — no medical jargon
- Keep things short and easy to read
- Never scare the user — mention warnings gently
- Never suggest extra medicines or diagnose anything
 
You have ONE tool: search_pharmeasy.
 
TOOL CALL RULES — read carefully:
- Call search_pharmeasy ONLY when the user explicitly says words like:
  "order", "buy", "purchase", "find on pharmeasy", "get me a link", "where can i buy"
- Do NOT call the tool for ANY of these — answer them yourself in plain text:
  - questions about what medicines are ("what is this?", "what are these?")
  - questions about how to take medicine ("when do I take this?")
  - questions about a prescription image ("what does my prescription say?")
  - general questions about side effects, dosage, interactions
  - anything that is a question, not a purchase request
- If you are unsure whether to call the tool, do NOT call it. Answer in text instead.
 
AFTER the tool runs:
- Write ONE short friendly sentence only (e.g. "Here are your medicines on PharmEasy!")
- NEVER include URLs, links, or product names in your text reply
- The app displays the medicine cards automatically"""

FREQ_LABELS = {
    "1-0-0": "once in the morning",
    "0-1-0": "once in the afternoon",
    "0-0-1": "once at night",
    "1-1-0": "morning and afternoon",
    "1-0-1": "morning and night",
    "0-1-1": "afternoon and night",
    "1-1-1": "three times a day",
}

# ── Tool definition (Ollama function-calling format) ─────────────────────────
PHARMEASY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_pharmeasy",
        "description": (
            "Search PharmEasy for the user's medicines and return product links. "
            "Call this when the user wants to order, buy, find or search for medicines. "
            "Always pass all medicines from the user's prescription."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "medicines": {
                    "type": "array",
                    "description": "List of medicines to search for",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":   {"type": "string", "description": "Medicine name"},
                            "dosage": {"type": "string", "description": "Dosage e.g. 500mg"},
                        },
                        "required": ["name"],
                    },
                }
            },
            "required": ["medicines"],
        },
    },
}

ALL_TOOLS = [PHARMEASY_TOOL]


# ── Tool executor ─────────────────────────────────────────────────────────────

# Module-level store so _ollama_with_tools can retrieve the raw structured
# results after the LLM finishes its tool-call loop.
_last_pharmeasy_results: Optional[list[dict]] = None


def _execute_tool(tool_name: str, tool_args: dict) -> str:
    """
    Run the requested tool synchronously (called inside a thread executor).
    Stores raw results in _last_pharmeasy_results for the caller to pick up.
    Returns a compact JSON summary string that goes back to the LLM as the
    tool result — deliberately stripped of URLs so the LLM doesn't paste them
    into its text reply.
    """
    global _last_pharmeasy_results

    if tool_name == "search_pharmeasy":
        try:
            from app.ai.agent import pharmeasy_scraper
            medicines = tool_args.get("medicines", [])
            if not medicines:
                return json.dumps({"error": "No medicines provided to search."})

            logger.info(f"[tool] search_pharmeasy called for: {[m['name'] for m in medicines]}")
            raw_results = pharmeasy_scraper.search_all_parallel(medicines, top_n=3)

            # ── Build the structured output stored for the API response ───────
            structured: list[dict] = []
            for r in raw_results:
                structured.append({
                    "medicine": r["medicine"],
                    "results": [
                        {"title": link["title"], "url": link["url"], "image": link.get("image")}
                        for link in r.get("links", [])
                    ],
                })
            _last_pharmeasy_results = structured

            # ── Give the LLM a URL-free summary so it doesn't paste links ─────
            llm_summary = []
            for r in raw_results:
                links = r.get("links", [])
                err   = r.get("error")
                
                # If no links but we have an error, log it
                if not links and err:
                    logger.warning(f"[tool] search_pharmeasy failed for '{r['medicine']}': {err}")

                llm_summary.append({
                    "medicine": r["medicine"],
                    "found":    bool(links),
                    "count":    len(links),
                    "error":    err if not links else None,
                    # Only product titles — no URLs — so LLM won't repeat them
                    "products": [link["title"] for link in links],
                })
            return json.dumps(llm_summary, ensure_ascii=False)

        except Exception as exc:
            logger.error(f"[tool] search_pharmeasy failed: {exc}")
            _last_pharmeasy_results = None
            return json.dumps({"error": str(exc)})

    # Unknown tool
    return json.dumps({"error": f"Tool '{tool_name}' is not available."})


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

def _build_rag_context(medicines: list[dict]) -> tuple[str, list[str]]:
    """Build the RAG context string from local drug_db + FAISS."""
    try:
        from app.ai.agent import tools
        sections = []
        for med in medicines:
            sections.append(tools.format_drug_summary(med))
        interactions = tools.check_interactions([m["name"] for m in medicines])
        return "\n".join(sections), interactions
    except Exception as exc:
        logger.warning(f"RAG context build failed: {exc}")
        return "", []


# ── Core blocking Ollama call with tool-call loop ─────────────────────────────

def _ollama_with_tools(messages: list[dict]) -> tuple[str, Optional[list[dict]]]:
    """
    Call Ollama with the tool list and handle the tool-call loop.
    Returns (content_text, pharmeasy_results_or_None).

    Flow:
      1. Reset _last_pharmeasy_results
      2. Call ollama.chat(messages, tools=ALL_TOOLS)
      3. If response has tool_calls:
           a. Execute each tool call (populates _last_pharmeasy_results)
           b. Append assistant message + tool results to messages
           c. Call ollama.chat() again
      4. Repeat up to MAX_TOOL_ROUNDS
      5. Return (final_text, _last_pharmeasy_results)
    """
    import ollama

    global _last_pharmeasy_results
    _last_pharmeasy_results = None   # reset before each request

    current_messages = list(messages)  # don't mutate caller's list
    last_content = ""
    pre_tool_content: Optional[str] = None  # first LLM text before any tool call

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            client = ollama.Client(host=OLLAMA_HOST)
            resp = client.chat(
                model=OLLAMA_MODEL,
                messages=current_messages,
                tools=ALL_TOOLS,
                options={"temperature": 0.3, "num_predict": 600},
            )
            # ── Log the complete LLM response for debugging ──────────────────
            logger.info(f"[agent] Full LLM Response: {resp}")
        except Exception as exc:
            logger.error(f"Ollama call failed (round {round_num + 1}): {exc}")
            return "Sorry, I couldn't reach the assistant right now. Please try again.", None, None

        msg = resp.message
        last_content = (msg.content or "").strip()

        # ── No tool calls → plain text reply, done ───────────────────────────
        if not msg.tool_calls:
            return last_content, pre_tool_content, _last_pharmeasy_results

        # ── Tool calls present → execute, then loop ──────────────────────────
        logger.info(f"[agent] Round {round_num + 1}: {len(msg.tool_calls)} tool call(s)")

        # Capture the LLM's text from the FIRST round as pre_tool_content
        # (subsequent rounds are post-tool summaries, not the "answering" text)
        if round_num == 0 and last_content:
            pre_tool_content = last_content

        # Append the assistant message that contains the tool_calls
        current_messages.append({
            "role":       "assistant",
            "content":    msg.content or "",
            "tool_calls": [
                {
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute each tool and append result as role="tool"
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            tool_args = (
                tc.function.arguments
                if isinstance(tc.function.arguments, dict)
                else json.loads(tc.function.arguments)
            )

            tool_result = _execute_tool(tool_name, tool_args)
            logger.debug(f"[tool result] {tool_name}: {tool_result[:200]}")

            current_messages.append({
                "role":    "tool",
                "name":    tool_name,
                "content": tool_result,
            })
        
        current_messages.append({
    "role":    "user",
    "content": (
        "The search is done. Reply in ONE short friendly sentence confirming "
        "the medicines were found and are ready to order. "
        "Do NOT include any URLs, links, or product names in your reply."
    ),
})

    # Safety cap hit
    logger.warning(f"[agent] Hit MAX_TOOL_ROUNDS ({MAX_TOOL_ROUNDS}) — returning last content")
    return last_content or "Something went wrong. Please try again.", pre_tool_content, _last_pharmeasy_results


# ── Build message list helpers ────────────────────────────────────────────────

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
    Tool-calling is not used here — explanation is a one-shot call.
    """
    if not medicines:
        return "No medicines found to explain.", []

    _, interactions = _build_rag_context(medicines)
    messages = _build_explanation_messages(medicines)

    loop = asyncio.get_event_loop()
    explanation = await loop.run_in_executor(
        None,
        lambda: __import__("ollama").chat(
            model=OLLAMA_MODEL,
            messages=messages,
            options={"temperature": 0.3, "num_predict": 400},
        ).message.content.strip()
    )
    return explanation, interactions


async def chat_reply(
    user_message: str,
    history: list[dict],
    medicines: Optional[list[dict]] = None,
) -> ChatReplyResult:
    """
    Generate a reply to a user chat message.
    Returns a ChatReplyResult with:
      .content           — text reply (no URLs)
      .pharmeasy_results — structured medicine links, or None

    history:   [{"role": "user"|"assistant", "content": str}, ...]  oldest→newest
    medicines: the user's current medicine list — injected into system context
    """
    system_content = SYSTEM_PROMPT
    if medicines:
        med_lines = "\n".join(
            f"  - {m.get('name', '?')} {m.get('dosage', '')}".strip()
            for m in medicines
        )
        system_content += (
            f"\n\nThe user currently has these medicines on their prescription:\n{med_lines}\n"
            f"When they ask to order or find medicines, call search_pharmeasy with this list."
        )

    messages: list[dict] = [{"role": "system", "content": system_content}]

    for turn in history[-20:]:
        messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": user_message})

    loop = asyncio.get_event_loop()
    content, pre_tool_content, pharmeasy_results = await loop.run_in_executor(
        None, _ollama_with_tools, messages
    )
    return ChatReplyResult(
        content=content,
        pre_tool_content=pre_tool_content or None,
        pharmeasy_results=pharmeasy_results,
    )


async def search_pharmeasy(medicines: list[dict]) -> list[dict]:
    """
    Directly run the PharmEasy scraper without going through the LLM.
    Kept for routes that need raw results (e.g. medicine_routes scan-only).
    """
    try:
        from app.ai.agent import pharmeasy_scraper
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


async def generate_interaction_alert(context_data: dict) -> str:
    """
    AI Task: Check if the new_medicine is safe. If not, suggest a generic alternative.
    """
    system_message = (
        "You are the RxGuardian AI safety validator. You will receive a JSON object with a user's profile and medications.\n"
        "- Task: Check if the 'new_medicine' is safe given the user's allergies and 'current_medications'.\n"
        "- If a conflict is found, start the message with '⚠️ Interaction Warning'.\n"
        "- Suggest a generic alternative if the medicine is unsafe.\n"
        "- Always respond in Markdown. Use Bold for medicine names.\n"
        "- Keep responses under 150 words.\n"
        "- Always include the safety disclaimer at the end."
    )
    return await _call_ollama_generic(system_message, context_data)


async def generate_ai_suggestions(context_data: dict) -> str:
    """
    AI Task: Provide 3 tips for better results (bioavailability and timing).
    """
    system_message = (
        "You are the RxGuardian AI medical assistant. You will receive a user's medical profile and medication list.\n"
        "- Task: Provide 3 tips for better results with their current medications.\n"
        "- Focus on bioavailability (e.g., 'Take with water, not milk') and lifestyle timing.\n"
        "- Always respond in Markdown. Use Lists for suggestions.\n"
        "- Keep responses under 150 words.\n"
        "- Always include the safety disclaimer at the end."
    )
    return await _call_ollama_generic(system_message, context_data)


async def generate_ai_insights(context_data: dict) -> str:
    """
    AI Task: Predict the next missed dose based on tracking history.
    """
    system_message = (
        "You are the RxGuardian AI health analyst. You will receive a user's weekly tracking history and medication list.\n"
        "- Task: Analyze the 'missed' patterns in the tracking grid and predict the next likely missed dose.\n"
        "- Be encouraging but precise in your prediction.\n"
        "- Always respond in Markdown.\n"
        "- Keep responses under 150 words.\n"
        "- Always include the safety disclaimer at the end."
    )
    return await _call_ollama_generic(system_message, context_data)


async def generate_side_effects(context_data: dict) -> str:
    """
    AI Task: Provide common side effects for a specific medicine.
    """
    system_message = (
        "You are the RxGuardian AI clinical assistant. You will receive a medicine's name, dosage, and instructions.\n"
        "- Task: List the common side effects for this specific medicine.\n"
        "- Mention which side effects are minor and which require contacting a doctor.\n"
        "- Always respond in Markdown. Use Bold for medicine names and Lists for side effects.\n"
        "- Keep responses under 150 words.\n"
        "- Always include the safety disclaimer at the end."
    )
    return await _call_ollama_generic(system_message, context_data)


async def _call_ollama_generic(system_message: str, context_data: dict) -> str:
    """Internal helper to call Ollama with a specific system prompt."""
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": f"Data: {json.dumps(context_data)}"}
    ]

    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(
            None,
            lambda: __import__("ollama").chat(
                model=OLLAMA_MODEL,
                messages=messages,
                options={"temperature": 0.3, "num_predict": 300},
            ).message.content.strip()
        )
        return response
    except Exception as exc:
        logger.error(f"AI call failed: {exc}")
        return "⚠️ I encountered an error while processing your request. Please try again later.\n\n*Safety Disclaimer: This is an AI-generated response. Always consult with a healthcare professional before making any medical decisions.*"
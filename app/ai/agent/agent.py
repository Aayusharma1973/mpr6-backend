"""
agent.py — Prescription Assistant CLI
Powered by Ollama (qwen2.5:3b) + PharmEasy search + RAG drug info

Usage:
    python agent.py
    python agent.py --model qwen2.5:3b

Setup:
    1. Install Ollama: https://ollama.com/download
    2. ollama pull qwen2.5:3b
    3. pip install ollama requests selenium webdriver-manager
    4. python agent.py
"""

import json
import logging
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import argparse

try:
    import ollama
except ImportError:
    print("Error: ollama not installed. Run:  pip install ollama")
    sys.exit(1)

import tools

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_MODEL = "qwen2.5:3b"

FREQ_LABELS = {
    "1-0-0": "once in the morning",
    "0-1-0": "once in the afternoon",
    "0-0-1": "once at night",
    "1-1-0": "morning and afternoon",
    "1-0-1": "morning and night",
    "0-1-1": "afternoon and night",
    "1-1-1": "three times a day",
}

SYSTEM_PROMPT = """You are a friendly assistant helping someone understand their prescription medicines.

Your style:
- Talk like a helpful friend, not a doctor
- Use simple everyday words — no medical jargon
- Keep things short and easy to read
- Don't scare the user — mention warnings gently, not dramatically
- Never suggest extra medicines or diagnose anything
- If something needs a doctor, say so briefly and move on

You help the user understand what their medicines are for and how to take them. That's it."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def check_ollama(model: str) -> bool:
    try:
        models     = ollama.list()
        available  = [m.model for m in models.models]
        base_avail = [m.split(":")[0] for m in available]
        base_req   = model.split(":")[0]
        if base_req not in base_avail and model not in available:
            print(f"\nModel '{model}' not pulled yet.")
            print(f"Run:  ollama pull {model}")
            print(f"\nAvailable: {', '.join(available) or 'none'}")
            return False
        return True
    except Exception:
        print("\nOllama isn't running.")
        print("Start it:  ollama serve")
        print("Then pull: ollama pull qwen2.5:3b")
        return False


def parse_prescription_input(text: str) -> list[dict] | None:
    """Parse JSON prescription from user input."""
    json_match = None
    for pattern in [r'\{.*\}', r'\[.*\]']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            json_match = match.group()
            break

    if not json_match:
        return None

    try:
        parsed = json.loads(json_match)
        if isinstance(parsed, dict):
            meds = parsed.get("medicines", [])
        elif isinstance(parsed, list):
            meds = parsed
        else:
            return None

        if not meds or not isinstance(meds[0], dict):
            return None

        return meds
    except json.JSONDecodeError:
        return None


def ask_llm(messages: list[dict], model: str) -> str:
    """Call Ollama and return response text."""
    try:
        resp = ollama.chat(
            model=model,
            messages=messages,
            options={"temperature": 0.3, "num_predict": 400},
        )
        return resp.message.content.strip()
    except Exception as e:
        return f"[LLM error: {e}]"


def print_header():
    print("\n" + "═" * 60)
    print("  💊  Prescription Assistant")
    print("  Powered by Ollama + PharmEasy")
    print("═" * 60)


def print_separator():
    print("\n" + "─" * 60)


# ── Main conversation flow ────────────────────────────────────────────────────

def run_agent(model: str):
    print_header()

    if not check_ollama(model):
        sys.exit(1)

    print(f"\n  Model : {model}")
    print("  Type  : 'quit' or 'exit' to stop\n")

    # ── Step 1: Get prescription JSON ────────────────────────────────────────
    print("Paste your prescription JSON and press Enter twice:\n")

    lines = []
    try:
        while True:
            line = input()
            if line.strip().lower() in ("quit", "exit"):
                print("\nGoodbye! 👋")
                sys.exit(0)
            if line == "" and lines:
                break
            lines.append(line)
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye! 👋")
        sys.exit(0)

    raw_input = "\n".join(lines).strip()
    medicines = parse_prescription_input(raw_input)

    if not medicines:
        print("\nCouldn't read that. Expected format:")
        print('  {"medicines": [{"name": "Metformin", "dosage": "500mg", "frequency": "1-0-1"}]}')
        sys.exit(1)

    print(f"\n✓ Got {len(medicines)} medicine(s) from your prescription.\n")

    # ── Step 2: RAG lookup + LLM explanation ─────────────────────────────────
    print_separator()
    print("\n  Looking up your medicines...\n")

    rag_sections = []
    for med in medicines:
        summary = tools.format_drug_summary(med)
        rag_sections.append(summary)

    med_names    = [m["name"] for m in medicines]
    interactions = tools.check_interactions(med_names)

    freq_list = "\n".join(
        f"  - {m['name']} {m.get('dosage', '')} — "
        f"{FREQ_LABELS.get(m.get('frequency', ''), m.get('frequency', ''))}"
        for m in medicines
    )

    rag_context = "\n".join(rag_sections)
    interaction_note = (
        "Heads up — there may be interactions between some of these medicines. "
        "Please double check with your doctor.\n  " + "\n  ".join(interactions)
        if interactions else ""
    )

    llm_messages = [
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

    explanation = ask_llm(llm_messages, model)
    print(explanation)

    if interactions:
        print()
        for w in interactions:
            print(f"  {w}")

    # ── Step 3: Q&A loop ──────────────────────────────────────────────────────
    print_separator()
    llm_messages.append({"role": "assistant", "content": explanation})

    print("\n  Got any questions about these medicines?")
    print("  (Type your question, or just press Enter to skip)\n")

    try:
        while True:
            question = input("You: ").strip()

            if not question:
                break
            if question.lower() in ("quit", "exit"):
                print("\nGoodbye! 👋")
                sys.exit(0)
            if question.lower() in ("no", "nope", "n", "done", "skip"):
                break

            llm_messages.append({"role": "user", "content": question})
            answer = ask_llm(llm_messages, model)
            print(f"\nAssistant: {answer}\n")
            llm_messages.append({"role": "assistant", "content": answer})

    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye! 👋")
        sys.exit(0)

    # ── Step 4: Offer to find on PharmEasy ───────────────────────────────────
    print_separator()
    try:
        order_choice = input("\nWant me to find these medicines on PharmEasy? (yes/no): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye! 👋")
        sys.exit(0)

    if order_choice not in ("yes", "y"):
        print("\nNo worries! Show this prescription to your local pharmacist.")
        print("Take care! 👋\n")
        sys.exit(0)

    # ── Step 5: Parallel PharmEasy search ────────────────────────────────────
    results = tools.search_medicines_pharmeasy(medicines, top_n=3)

    # ── Step 6: Display links ─────────────────────────────────────────────────
    print_separator()
    print("\n  Here are the top results from PharmEasy:\n")
    print(tools.format_pharmeasy_results(results))

    found_count = sum(1 for r in results if r.get("links"))
    not_found   = [r["medicine"] for r in results if not r.get("links")]

    print_separator()
    print(f"\n  ✓ Found results for {found_count}/{len(medicines)} medicine(s).")

    if not_found:
        print(f"\n  Not found on PharmEasy: {', '.join(not_found)}")
        print("  Try searching these on pharmeasy.in or at your local pharmacy.")

    print("\n  → Open any link above to view the product and add it to your cart.")
    print("  → You can pay with COD, UPI, or card at checkout.")
    print("\n  Take care and get well soon! 💊\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Prescription Assistant — understand your medicines + find them on PharmEasy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  1. Install Ollama: https://ollama.com/download
  2. ollama pull qwen2.5:3b
  3. pip install ollama requests selenium webdriver-manager
  4. python agent.py

Example prescription JSON:
  {"medicines": [
    {"name": "Metformin",    "dosage": "500mg", "frequency": "1-0-1"},
    {"name": "Atorvastatin", "dosage": "10mg",  "frequency": "0-0-1"}
  ]}
        """
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_MODEL})"
    )
    args = parser.parse_args()
    run_agent(args.model)


if __name__ == "__main__":
    main()